"""D21：脚本模型驱动真实读取/编辑，再由外部验收器检查文件与补丁。"""

import asyncio
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import shutil
from time import perf_counter
from unittest.mock import patch

from evals.d21_acceptance import judge_workspace
from evals.d21_preview import ROOT, SCRIPTED_SUMMARY, load_case, rows, seed_history
from evals.logs import save_json
from mini_pi.auto_compaction import AutoCompactionSettings
from mini_pi.bootstrap import ToolBundle
from mini_pi.cli import _wait_for_command_idle
from mini_pi.context import FullHistoryContext, ReadOutputContext
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context_size import estimate_qwen_input, estimate_qwen_item
from mini_pi.harness import Harness, RunBudget
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy
from mini_pi.tools.read_file import ReadFileExecutor
from mini_pi.tools.tool_router import ToolRouter


def scripted_answer(case, claim_only=False):
    if claim_only:
        return MockProvider([Message("assistant", "已经完成修改。", stop_reason="stop")])

    def final_answer(history, tools):
        succeeded = any(isinstance(item, ToolResult) and item.tool_call_id == "d21-edit-target"
                        and item.error is None for item in history)
        return Message("assistant", "工具已成功编辑目标文件。" if succeeded else "编辑未成功，不能宣称完成。", stop_reason="stop")

    return MockProvider([
        Message("assistant", "读取目标文件。", [ToolCall("d21-read-target", "read_file", {"path": case["target_file"]})], stop_reason="tool_calls"),
        Message("assistant", "按约定执行替换。", [ToolCall("d21-edit-target", "edit_file", {
            "path": case["target_file"], "old_text": "world", "new_text": "testing",
        })], stop_reason="tool_calls"),
        final_answer,
    ])


def captured_requests(provider):
    return [{"request_number": index + 1, "messages": rows(messages),
             "tools": [asdict(tool) for tool in provider.tool_requests[index]],
             "input_estimate": asdict(estimate_qwen_input(messages, provider.tool_requests[index]))}
            for index, messages in enumerate(provider.requests)]


async def run_case(directory, name, case, *, max_answer_turns, claim_only=False,
                   answer_provider=None, summary_provider=None, run_config=None,
                   mode="scripted_full_task", telemetry=None):
    config = {"read_output_chars": 1024, "compaction_trigger_tokens": 500,
              "keep_recent_tokens": 1, "context_window_tokens": 8192,
              "reserved_output_tokens": 512, "safety_margin_tokens": 256,
              "total_timeout_seconds": 30, **(run_config or {})}
    scripted = mode == "scripted_full_task"
    if not scripted and (answer_provider is None or telemetry is None):
        raise ValueError("真实入口必须提供真实模型和用量记录入口")
    directory.mkdir()
    workspace = directory / "workspace"
    shutil.copytree(ROOT / case["initial_directory"], workspace)
    notes = (workspace / case["constructed_history"]["background_file"]).read_text(encoding="utf-8")
    seed = seed_history(case, notes)
    original = deepcopy(seed + [Message("user", case["continuation_prompt"])])
    path = directory / "session.jsonl"
    seed_store = SessionStore(path, "constructed-seed")
    for item in seed:
        seed_store.append_item(item)
    reader = ReadFileExecutor(workspace)
    editor = EditFileExecutor(EditPolicy(workspace, case["tools"]["editable_files"]))
    router = ToolRouter({"read_file": reader, "edit_file": editor})
    tools = ToolBundle(router, [reader.definition, editor.definition], frozenset({"read_file"}))
    answer = answer_provider if answer_provider is not None else scripted_answer(case, claim_only)
    summary = summary_provider if summary_provider is not None else MockProvider([Message("assistant", SCRIPTED_SUMMARY, stop_reason="stop")])
    if answer_provider is None:
        answer.max_completion_tokens = 512
    if summary_provider is None:
        summary.max_completion_tokens = 512
    window = ContextWindowBudget(config["context_window_tokens"], config["reserved_output_tokens"], config["safety_margin_tokens"])
    options = dict(budget=RunBudget(max_model_turns=max_answer_turns, total_timeout_seconds=config["total_timeout_seconds"]),
                   context_builder=FullHistoryContext() if name == "A" else ReadOutputContext(config["read_output_chars"]),
                   input_estimator=estimate_qwen_input, window_budget=window)
    if name == "C":
        options.update(auto_compaction=AutoCompactionSettings(config["compaction_trigger_tokens"], config["keep_recent_tokens"]), summary_provider=summary,
                       summary_window=window, summary_estimator=estimate_qwen_input, item_estimator=estimate_qwen_item)
    harness = Harness(answer, tools, **options)
    started = perf_counter()
    result = None
    exception = None
    with patch.object(router, "execute", wraps=router.execute) as execute:
        try:
            outcome = await harness.resume(case["continuation_prompt"], SessionStore(path, "dry-run-" + name))
            result = outcome.run_result
        except asyncio.CancelledError:
            exception = {"type": "CancelledError", "message": "offline case cancelled"}
        except Exception as error:
            exception = {"type": type(error).__name__, "message": str(error)}
        finally:
            if harness.agent.is_running:
                harness.agent.abort()
                await _wait_for_command_idle(harness)
        executed_ids = [item.args[0].id for item in execute.await_args_list]
    elapsed = perf_counter() - started
    loaded = seed_store.load()
    new_items = loaded.history[len(original):]
    calls = [call for item in new_items if isinstance(item, Message) for call in item.tool_calls]
    feedback = [item for item in new_items if isinstance(item, ToolResult)]
    answer_records = captured_requests(answer)
    summary_records = captured_requests(summary)
    save_json(directory / "requests.json", {"answer": answer_records, "summary": summary_records})
    save_json(directory / "tool-results.json", [asdict(item) for item in feedback])
    save_json(directory / "original-input.json", rows(original))
    live_telemetry = telemetry() if telemetry is not None else {}
    if live_telemetry:
        save_json(directory / "provider-requests.json", live_telemetry["provider_requests"])
    verdict = judge_workspace(workspace, case, feedback, directory / "patch-validation")
    status = result.status if result is not None else "cancelled" if exception and exception["type"] == "CancelledError" else "exception"
    pipeline_checks = {
        "run_finished": status == "finished",
        "history_matches_returned_result": result is not None and loaded.history == result.messages,
        "original_history_preserved": loaded.history[:len(original)] == original,
        "no_historical_call_replay": case["constructed_history"]["historical_read_call_id"] not in executed_ids,
        "new_calls_executed_and_results_paired": [call.id for call in calls] == executed_ids == [item.tool_call_id for item in feedback],
        "actual_feedback_reached_answer_model": all(any(item in request for request in answer.requests) for item in feedback),
        "summary_policy_exercised": len(summary.requests) == (1 if name == "C" else 0),
        "agent_idle": not harness.agent.is_running,
    }
    report = {"variant": name, "mode": mode, "claim_only_control": claim_only,
              "run_status": status, "run_task_passed": result.task_passed if result is not None else None,
              "exception": exception, "error": result.error if result is not None else None,
              "pipeline_checks": pipeline_checks, "pipeline_checks_passed": all(pipeline_checks.values()),
              "executed_call_ids": executed_ids, "tool_results": [asdict(item) for item in feedback],
              "compaction_records": sum(item["type"] == "compaction" for item in loaded.records),
              "answer_requests": len(answer.requests), "summary_requests": len(summary.requests),
              "answer_script_calls": len(answer.requests) if scripted else 0,
              "summary_script_calls": len(summary.requests) if scripted else 0,
              "answer_input_estimated_tokens": [item["input_estimate"]["estimated_input_tokens"] for item in answer_records],
              "summary_input_estimated_tokens": [item["input_estimate"]["estimated_input_tokens"] for item in summary_records],
              "run_elapsed_seconds": round(elapsed, 6),
              "elapsed_offline_run_seconds": round(elapsed, 6) if scripted else None,
              "actual_usage": None, "real_model_requests": 0 if scripted else None, "effectiveness_verified": False,
              "workspace": str(workspace.resolve()), "session_path": str(path.resolve()), **verdict}
    report.update(live_telemetry)
    save_json(directory / "result.json", report)
    return report


async def run_dry_run(directory, *, max_answer_turns=3):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    case = load_case()
    save_json(directory / "protocol.json", {
        "case": case, "mode": "scripted_full_task", "real_model_requests": 0,
        "common_context_window": 8192, "reserved_output_tokens": 512, "safety_margin_tokens": 256,
        "max_answer_turns": max_answer_turns, "total_timeout_seconds": 30,
        "read_output_chars": 1024, "compaction_trigger_tokens": 500, "keep_recent_tokens": 1,
        "summary_call_cap": 1, "scripted_summary": SCRIPTED_SUMMARY,
        "note": "预设回答与摘要驱动真实工具；独立验收不信任模型的完成声明，不据此比较模型效果或速度。",
    })
    groups = {}
    for name in ("A", "B", "C"):
        groups[name] = await run_case(directory / name, name, case, max_answer_turns=max_answer_turns)
        if groups[name]["run_status"] == "cancelled":
            break
    control = None
    if len(groups) == 3 and all(item["run_status"] != "cancelled" for item in groups.values()):
        control = await run_case(directory / "claim-only", "A", case, max_answer_turns=max_answer_turns, claim_only=True)
    passed = len(groups) == 3 and all(item["case_verdict"] == "passed" and item["pipeline_checks_passed"] for item in groups.values())
    control_expected = control is not None and control["run_status"] == "finished" and control["case_verdict"] == "failed"
    report = {"mode": "scripted_full_task", "groups": groups, "claim_only_control": control,
              "control_rejected_as_expected": control_expected, "dry_run_checks_passed": passed and control_expected,
              "real_model_requests": 0, "actual_usage": None, "effectiveness_verified": False}
    save_json(directory / "result.json", report)
    lines = ["# D21：完整离线演练", "", "回答和摘要来自脚本；文件修改及补丁重建实际执行。真实模型请求0次，不代表模型自主完成任务或策略效果。", "",
             "| 组别 | 运行状态 | 实际文件 | 独立任务验收 | 回答脚本请求 | 摘要脚本请求 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for name, item in groups.items():
        lines.append(f"| {name} | {item['run_status']} | `{item['actual_content']}` | {item['case_verdict']} | {item['answer_script_calls']} | {item['summary_script_calls']} |")
    if control is not None:
        lines.append(f"| 只声称成功的对照 | {control['run_status']} | `{control['actual_content']}` | {control['case_verdict']}（符合预期） | {control['answer_script_calls']} | 0 |")
    lines += ["", "通过依据：实际文件内容正确、其他文件未变、文件清单未变，实际成功编辑返回的补丁可以独立重建最终内容。",
              "", "运行状态与任务验收分开记录；脚本模型说完成不足以通过。",
              "", "计时是本地脚本、真实工具及收尾的耗时，不作为模型速度或不同策略优劣的证据。"]
    (directory / "review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
