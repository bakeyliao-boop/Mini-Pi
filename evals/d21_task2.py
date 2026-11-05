"""D21第二任务：诊断长读取尾部信息丢失，仅运行脚本模型和真实本地工具。"""

from dataclasses import asdict
import json
from pathlib import Path
import re

from evals.d21_dry_run import run_case
from evals.d21_preview import ROOT
from evals.logs import save_json
from mini_pi.context_output import shorten_read_result
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult


OFFLINE_CONFIG = {
    "read_output_chars": 4096, "compaction_trigger_tokens": 1300,
    "keep_recent_tokens": 1, "context_window_tokens": 8192,
    "reserved_output_tokens": 512, "safety_margin_tokens": 256,
    "total_timeout_seconds": 30,
}
SCRIPTED_SUMMARY = (
    "用户要求按release-notes.txt的批准值修改app.conf的channel=preview。"
    "工具记录中的配置数据为approved_channel=qa-east-7。"
    "只修改该项，保留其他字符、LF和末尾换行，不增删文件。"
    "背景记录已读取；旧助手声明目标尚未修改，待实际读取后编辑。"
)
MISSING_FACT_SUMMARY = (
    "用户要求按release-notes.txt的批准值修改app.conf的channel=preview。"
    "只修改该项，保留其他字符、LF和末尾换行，不增删文件；尚待实际编辑。"
)
WRONG_FACT_SUMMARY = SCRIPTED_SUMMARY.replace("qa-east-7", "qa-west-9")


def load_task2():
    return json.loads((ROOT / "evals/cases/d21_config_tail.json").read_text(encoding="utf-8"))


def visible_approved_value(history):
    # 只看实际交给脚本模型的文字，不读取expected_content或独立验收答案。
    texts = [item.output if isinstance(item, ToolResult) and item.error is None
             else item.content if isinstance(item, Message) else "" for item in history]
    values = set(re.findall(r"(?<![a-zA-Z0-9_])approved_channel=([a-z0-9-]+)(?![a-zA-Z0-9_-])", "\n".join(texts)))
    return next(iter(values)) if len(values) == 1 else None


def scripted_answer(case):
    def step(history, tools):
        results = {item.tool_call_id: item for item in history if isinstance(item, ToolResult)}
        if "task2-edit" in results:
            ok = results["task2-edit"].error is None
            return Message("assistant", "已按工具结果完成替换。" if ok else "编辑失败，不能声称完成。", stop_reason="stop")
        if "task2-read-target" not in results:
            return Message("assistant", "读取当前配置。", [ToolCall("task2-read-target", "read_file", {"path": case["target_file"]})], stop_reason="tool_calls")
        if results["task2-read-target"].error is not None:
            return Message("assistant", "目标读取失败，停止编辑。", stop_reason="stop")
        value = visible_approved_value(history)
        if value is not None:
            return Message("assistant", "按当前可见的批准值修改。", [ToolCall("task2-edit", "edit_file", {
                "path": case["target_file"], "old_text": "channel=preview", "new_text": "channel=" + value,
            })], stop_reason="tool_calls")
        if "task2-reread-notes" not in results:
            return Message("assistant", "缺少批准值，尝试重新读取记录。", [ToolCall("task2-reread-notes", "read_file", {
                "path": case["constructed_history"]["background_file"],
            })], stop_reason="tool_calls")
        return Message("assistant", "可见内容中仍没有批准值，保留原文件，不能猜测或声称完成。", stop_reason="stop")

    provider = MockProvider([step] * 4)
    provider.max_completion_tokens = 256
    return provider


def inspect_requests(directory, report, case, notes):
    requests = json.loads((directory / "requests.json").read_text(encoding="utf-8"))
    answer = requests["answer"]
    first = answer[0]["messages"] if answer else []
    source = json.loads(requests["summary"][0]["messages"][1]["data"]["content"]) if requests["summary"] else []
    value = case["task_data"]["approved_value"]
    marker = "approved_channel=" + value
    first_reads = [item["data"]["output"] for item in first if item["type"] == "tool_result"]
    source_reads = [item["data"]["output"] for item in source if item["type"] == "tool_result"]
    rereads = [item["data"]["output"] for request in answer for item in request["messages"]
               if item["type"] == "tool_result" and item["data"]["tool_call_id"] == "task2-reread-notes"]
    # 复用真正的裁剪函数核对发送副本；不能要求裁剪后的反馈与原文对象完全相等。
    projected_feedback = []
    for data in report["tool_results"]:
        feedback = ToolResult(**data)
        projected = feedback if report["variant"] == "A" else shorten_read_result(feedback, OFFLINE_CONFIG["read_output_chars"])
        projected_feedback.append(any(item["type"] == "tool_result" and item["data"] == asdict(projected)
                                      for request in answer for item in request["messages"]))
    return {
        "first_answer_has_approved_value": marker in json.dumps(first, ensure_ascii=False),
        "original_read_chars": len(notes), "first_answer_read_chars": [len(text) for text in first_reads],
        "summary_source_has_full_read": source_reads == [notes],
        "summary_source_has_approved_value": marker in json.dumps(source, ensure_ascii=False),
        "reread_still_missing_approved_value": bool(rereads) and all(marker not in text for text in rereads),
        "feedback_projection_matches_context_policy": all(projected_feedback),
        "all_requests_within_common_estimated_window": all(
            request["input_estimate"]["estimated_input_tokens"] + 512 + 256 <= 8192
            for phase in requests.values() for request in phase),
    }


async def run_task2(directory, *, scripted_summary=SCRIPTED_SUMMARY):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    case = load_task2()
    notes = (ROOT / case["initial_directory"] / case["constructed_history"]["background_file"]).read_text(encoding="utf-8")
    save_json(directory / "protocol.json", {"case": case, "mode": "offline_task2_diagnostic",
              "run_config": OFFLINE_CONFIG, "max_answer_turns": 4, "summary_call_cap": 1,
              "scripted_summary": scripted_summary, "real_model_requests": 0,
              "live_protocol_prepared": False, "note": "预设摘要及依赖实际输入的脚本回答，仅验证接线与独立验收；不证明真实摘要质量或策略效果。"})
    groups = {}
    for name in ("A", "B", "C"):
        summary = MockProvider([Message("assistant", scripted_summary, stop_reason="stop")])
        summary.max_completion_tokens = 256
        item = await run_case(directory / name, name, case, max_answer_turns=4,
                              answer_provider=scripted_answer(case), summary_provider=summary,
                              run_config=OFFLINE_CONFIG)
        item.update(inspect_requests(directory / name, item, case, notes))
        save_json(directory / name / "result.json", item)
        groups[name] = item
    a, b, c = (groups[name] for name in ("A", "B", "C"))
    value = case["task_data"]["approved_value"]
    checks = {
        "fixture_value_only_in_tail_read": notes.count("approved_channel=" + value) == 1
            and notes.index("approved_channel=" + value) >= OFFLINE_CONFIG["read_output_chars"]
            and value not in case["earlier_user_message"] + case["continuation_prompt"],
        "A_sees_fact_B_loses_fact_C_script_keeps_fact": a["first_answer_has_approved_value"]
            and not b["first_answer_has_approved_value"] and c["first_answer_has_approved_value"],
        "C_summary_source_is_full_original_read": c["summary_source_has_full_read"] and c["summary_source_has_approved_value"]
            and c["summary_requests"] == c["compaction_records"] == 1,
        "B_reread_cannot_recover_tail": b["reread_still_missing_approved_value"]
            and not any(item["tool_name"] == "edit_file" for item in b["tool_results"]),
        "file_oracle_distinguishes_missing_fact": a["case_verdict"] == c["case_verdict"] == "passed" and b["case_verdict"] == "failed",
        "all_runs_finish_with_paired_projected_feedback": all(item["run_status"] == "finished"
            and item["pipeline_checks"]["new_calls_executed_and_results_paired"]
            and item["feedback_projection_matches_context_policy"] and item["pipeline_checks"]["agent_idle"] for item in groups.values()),
        "original_history_preserved_without_replay": all(item["pipeline_checks"]["original_history_preserved"]
            and item["pipeline_checks"]["no_historical_call_replay"] for item in groups.values()),
        "all_requests_fit_common_estimated_window": all(item["all_requests_within_common_estimated_window"] for item in groups.values()),
    }
    report = {"mode": "offline_task2_diagnostic", "case_id": case["id"], "groups": groups, "checks": checks,
              "preparation_checks_passed": all(checks.values()), "real_model_requests": 0, "actual_usage": None,
              "effectiveness_verified": False, "summary_quality_verified": False, "live_protocol_prepared": False}
    save_json(directory / "result.json", report)
    lines = ["# D21第二任务：长记录尾部批准值的离线演练", "", "脚本回答只使用实际请求中可见的批准值；C摘要为预设文字。所有文件修改、工具返回和补丁验收实际执行，真实请求0次。", "",
             "| 组别 | 首次回答看得到批准值 | 运行终态 | 文件验收 |",
             "| --- | --- | --- | --- |"]
    lines += [f"| {name} | {item['first_answer_has_approved_value']} | {item['run_status']} | {item['case_verdict']} |" for name, item in groups.items()]
    lines += ["", "B再次读取同一文件仍会丢掉尾部；没有按行读取或历史回查工具，不能把省略提示当成已有回查能力。B未修改文件，文件任务失败不等于接线失败。",
              "", "保留共享报告中的原反馈相等检查；长结果合法裁剪后该检查会为false，本任务另按工具ID、错误及实际裁剪副本核对反馈。",
              "", "C预设摘要保留关键值的成功只验证组件接通，真实模型可能遗漏或改错批准值，尚未执行真实对比。",
              "", "本任务诊断当前固定前段裁剪缺少回查能力，不能代表一般任务或证明摘要普遍更好。新真实协议、重复次数及API授权尚未准备；第一任务10次授权不延用。"]
    (directory / "review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
