"""D21辅助演示：经现有Harness捕获三组首个请求；仅脚本响应，不执行修改任务。"""

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import shutil
from unittest.mock import patch

from evals.logs import save_json
from mini_pi.auto_compaction import AutoCompactionSettings
from mini_pi.bootstrap import ToolBundle
from mini_pi.compaction_restore import read_saved_compaction
from mini_pi.context import FullHistoryContext, ReadOutputContext
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context_size import estimate_qwen_input, estimate_qwen_item
from mini_pi.harness import Harness, RunBudget
from mini_pi.memory.context_helpers import check_complete_messages
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy
from mini_pi.tools.read_file import ReadFileExecutor
from mini_pi.tools.tool_router import ToolRouter


ROOT = Path(__file__).resolve().parents[1]
SCRIPTED_SUMMARY = (
    "待办：把 edit-test.txt 中的 world 换成 testing，保留其余文字和标点；"
    "只修改 edit-test.txt，不新增或删除文件。过程记录已读取，目标尚未修改。"
)


def load_case():
    return json.loads((ROOT / "evals/cases/d21_edit_history.json").read_text(encoding="utf-8"))


def seed_history(case, notes):
    call_id = case["constructed_history"]["historical_read_call_id"]
    return [
        Message("user", case["earlier_user_message"]),
        Message("assistant", "先读取过程记录，暂不修改目标文件。", [
            ToolCall(call_id, "read_file", {"path": case["constructed_history"]["background_file"]}),
        ], stop_reason="tool_calls"),
        ToolResult(call_id, "read_file", notes),
        Message("assistant", "过程记录已读取，目标文件尚未修改。", stop_reason="stop"),
    ]


def rows(messages):
    return [{"type": "tool_result" if isinstance(item, ToolResult) else "message", "data": asdict(item)}
            for item in messages]


def has_goal(text, case):
    return all(term in text for term in (case["target_file"], "world", "testing"))


async def run_variant(directory, name, case, *, read_limit, trigger, scripted_summary):
    directory.mkdir()
    workspace = directory / "workspace"
    shutil.copytree(ROOT / case["initial_directory"], workspace)
    before = {path.name: path.read_bytes() for path in workspace.iterdir()}
    notes = before[case["constructed_history"]["background_file"]].decode("utf-8")
    seed = seed_history(case, notes)
    original = deepcopy(seed + [Message("user", case["continuation_prompt"])])
    path = directory / "session.jsonl"
    old_store = SessionStore(path, "constructed-seed")
    for item in seed:
        old_store.append_item(item)

    reader = ReadFileExecutor(workspace)
    editor = EditFileExecutor(EditPolicy(workspace, case["tools"]["editable_files"]))
    router = ToolRouter({"read_file": reader, "edit_file": editor})
    tools = ToolBundle(router, [reader.definition, editor.definition], frozenset({"read_file"}))
    answer = MockProvider([Message("assistant", "离线输入预览结束，未执行修改任务。", stop_reason="stop")])
    summary = MockProvider([Message("assistant", scripted_summary, stop_reason="stop")])
    answer.max_completion_tokens = summary.max_completion_tokens = 512
    window = ContextWindowBudget(8192, 512, 256)
    options = dict(budget=RunBudget(max_model_turns=1, total_timeout_seconds=10),
                   context_builder=FullHistoryContext() if name == "A" else ReadOutputContext(read_limit),
                   input_estimator=estimate_qwen_input, window_budget=window)
    if name == "C":
        options.update(auto_compaction=AutoCompactionSettings(trigger, 1), summary_provider=summary,
                       summary_window=window, summary_estimator=estimate_qwen_input,
                       item_estimator=estimate_qwen_item)
    harness = Harness(answer, tools, **options)
    with patch.object(router, "execute", wraps=router.execute) as execute:
        outcome = await harness.resume(case["continuation_prompt"], SessionStore(path, "preview-" + name))
    loaded = SessionStore(path).load()
    request = answer.requests[0] if answer.requests else []
    check_complete_messages(request)
    saved = read_saved_compaction(loaded)
    cut = saved[1].cut_index if saved is not None else None
    summary_text = saved[0] if saved is not None else None
    source = json.loads(summary.requests[0][1].content) if summary.requests else []
    source_notes = [row["data"]["output"] for row in source if row["type"] == "tool_result"]
    reads = [item.output for item in request if isinstance(item, ToolResult)]
    estimate = estimate_qwen_input(request, tools.definitions)
    after = {item.name: item.read_bytes() for item in workspace.iterdir()}
    save_json(directory / "original-input.json", rows(original))
    save_json(directory / "answer-request.json", {"messages": rows(request), "tools": [asdict(item) for item in tools.definitions]})
    save_json(directory / "summary-request.json", [rows(item) for item in summary.requests])
    if summary.requests:
        save_json(directory / "summary-source.json", source)
    result = {
        "variant": name, "run_status": outcome.run_result.status if outcome.run_result is not None else "not_ready",
        "error": outcome.run_result.error if outcome.run_result is not None else None,
        "answer_script_calls": len(answer.requests), "scripted_summary_calls": len(summary.requests),
        "compaction_records": sum(row["type"] == "compaction" for row in loaded.records),
        "cut_index": cut, "summary_origin": "scripted_fixture" if summary.requests else None,
        "scripted_summary": summary_text,
        "old_user_goal_in_answer_as_original_message": any(item == seed[0] for item in request),
        "goal_in_scripted_summary": isinstance(summary_text, str) and has_goal(summary_text, case),
        "goal_in_summary_source": bool(source) and source[0]["data"]["content"] == case["earlier_user_message"],
        "summary_source_has_complete_notes": source_notes == [notes],
        "recent_original_contains_old_goal": cut is not None and seed[0] in original[cut:],
        "old_goal_inside_summary_range": cut is not None and cut > 0,
        "read_result_chars_in_answer": [len(item) for item in reads],
        "read_result_full_in_answer": reads == [notes],
        "read_result_shortened_in_answer": len(reads) == 1 and len(reads[0]) == read_limit and notes.startswith(reads[0].split("\n[后续内容")[0]),
        "answer_input_estimate": asdict(estimate),
        "summary_input_estimate": asdict(estimate_qwen_input(summary.requests[0], [])) if summary.requests else None,
        "original_history_preserved": loaded.history[:len(original)] == original,
        "continuation_preserved": Message("user", case["continuation_prompt"]) in request,
        "same_tool_definitions": answer.tool_requests == [tools.definitions],
        "within_answer_window": estimate.estimated_input_tokens + window.reserved_output_tokens + window.safety_margin_tokens <= window.context_window_tokens,
        "executed_tool_calls": execute.await_count,
        "workspace_unchanged": before == after,
        "actual_usage": None, "real_model_requests": 0, "task_evaluated": False,
    }
    save_json(directory / "result.json", result)
    return result


async def run_preview(directory, *, read_limit=1024, trigger=500, scripted_summary=SCRIPTED_SUMMARY):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    case = load_case()
    save_json(directory / "protocol.json", {
        "case": case, "mode": "offline_input_preview", "preview_only_not_frozen_live_budget": True,
        "read_limit_chars": read_limit, "compaction_trigger_estimated_tokens": trigger, "keep_recent_tokens": 1,
        "common_window_tokens": 8192, "reserved_output_tokens": 512, "safety_margin_tokens": 256,
        "max_answer_turns": 1, "run_timeout_seconds": 10,
        "scripted_summary": scripted_summary, "real_model_requests": 0,
    })
    groups = {name: await run_variant(directory / name, name, case, read_limit=read_limit,
                                      trigger=trigger, scripted_summary=scripted_summary) for name in ("A", "B", "C")}
    a, b, c = (groups[name] for name in ("A", "B", "C"))
    checks = {
        "all_runs_finished_and_captured_one_answer": all(item["run_status"] == "finished" and item["answer_script_calls"] == 1 for item in groups.values()),
        "A_full_read_and_old_goal": a["read_result_full_in_answer"] and a["old_user_goal_in_answer_as_original_message"],
        "B_shortened_read_and_old_goal": b["read_result_shortened_in_answer"] and b["old_user_goal_in_answer_as_original_message"],
        "A_B_no_summary": a["scripted_summary_calls"] == b["scripted_summary_calls"] == a["compaction_records"] == b["compaction_records"] == 0,
        "C_triggered_after_read_shortening": b["answer_input_estimate"]["estimated_input_tokens"] > trigger and c["scripted_summary_calls"] == c["compaction_records"] == 1,
        "C_old_goal_was_summarized_not_kept_recent": c["old_goal_inside_summary_range"] and not c["recent_original_contains_old_goal"] and not c["old_user_goal_in_answer_as_original_message"],
        "C_source_uses_raw_old_history": c["goal_in_summary_source"] and c["summary_source_has_complete_notes"],
        "C_scripted_summary_contains_goal": c["goal_in_scripted_summary"],
        "all_original_history_and_workspaces_unchanged": all(item["original_history_preserved"] and item["workspace_unchanged"] for item in groups.values()),
        "no_historical_tool_replay": all(item["executed_tool_calls"] == 0 for item in groups.values()),
        "same_tools_continuation_and_common_window": all(item["same_tool_definitions"] and item["continuation_preserved"] and item["within_answer_window"] for item in groups.values()),
    }
    report = {"stage": "offline_input_preview", "preview_checks_passed": all(checks.values()), "checks": checks,
              "groups": groups, "real_model_requests": 0, "actual_usage": None, "task_evaluated": False,
              "effectiveness_verified": False, "summary_quality_verified": False}
    save_json(directory / "result.json", report)
    text = ["# D21：三组输入的离线核对", "", "本次只捕获输入，不修改目标文件。C使用预设摘要，不代表真实摘要质量或任务成功。", "",
            "| 组别 | 旧要求在哪里 | 长读取结果字符数 | 完整请求估算tokens | 脚本摘要次数 |",
            "| --- | --- | --- | --- | --- |"]
    for name, item in groups.items():
        location = "预设摘要（非真实模型生成）" if name == "C" and item["scripted_summary"] is not None else "较早用户原文"
        text.append(f"| {name} | {location} | {item['read_result_chars_in_answer'] or '不在近期原文中'} | {item['answer_input_estimate']['estimated_input_tokens']} | {item['scripted_summary_calls']} |")
    text.extend(["", "较早用户要求：" + case["earlier_user_message"], "", "当前问题：" + case["continuation_prompt"],
                 "", "C的预设摘要：" + (c["scripted_summary"] or "未触发摘要"), "",
                 "C已保存预设摘要，来源与保留段以result.json实际检查为准。" if c["scripted_summary"] is not None else "C未生成或保存摘要，本轮不能据此比较摘要策略。",
                 "", "原始历史和目标文件保持原样。真实usage未获得；这里的tokens来自字符启发式估算。",
                 "", "下一步仍需实际任务验收与完整离线演练，再落实真实对比的固定预算。"])
    (directory / "input-review.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    return report
