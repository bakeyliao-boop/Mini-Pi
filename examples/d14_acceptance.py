"""D14辅助验收：每次使用新副本，离线排演不冒充真实模型自主修复。"""

import argparse
import asyncio
from dataclasses import asdict
import difflib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

from mini_pi.bootstrap import build_tools
from mini_pi.harness import Harness, RunBudget
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore


TASK = (
    "请修复这个小项目的折扣计算。rate表示减免比例，例如100元减免20%应实付80元。"
    "先读取代码和测试，用run_tests运行程序预设的测试命令，再修复并验证。"
    "只允许修改discount.py，不得修改或绕过test_discount.py，不新增文件。"
    "通过list_files/read_file/edit_file/run_tests四个工具完成；"
    "最后根据实际测试结果总结，不把运行结束当作验收通过。"
)


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run_fixed_tests(project, command, output_path):
    completed = subprocess.run(command, cwd=project, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=30)
    output_path.write_bytes(completed.stdout)
    return {"exit_code": completed.returncode, "output_path": str(output_path)}


def scripted_provider():
    """答案来自助手脚本，只验证真实文件/进程/JSONL接线。"""
    return MockProvider([
        Message("assistant", "先读取并验证失败", [
            ToolCall("read_code", "read_file", {"path": "discount.py"}),
            ToolCall("read_tests", "read_file", {"path": "test_discount.py"}),
            ToolCall("before_tests", "run_tests", {}),
        ]),
        Message("assistant", "按减免比例修复", [ToolCall("edit", "edit_file", {
            "path": "discount.py", "old_text": "return price * rate",
            "new_text": "return price * (1 - rate)",
        })]),
        Message("assistant", "验证修改", [ToolCall("after_tests", "run_tests", {})]),
        Message("assistant", "固定测试通过。此轮为脚本排演。", stop_reason="stop"),
    ])


def request_contains_passing_test_feedback(records, passed_call_ids):
    """按调用ID配对，并解开API外壳和测试输出两层JSON，不靠原始文本匹配。"""
    for record in records:
        for message in record.get("request_body", {}).get("messages", []):
            if message.get("role") != "tool" or message.get("tool_call_id") not in passed_call_ids:
                continue
            try:
                envelope = json.loads(message["content"])
                if not isinstance(envelope, dict) or envelope.get("error") is not None:
                    continue
                payload = json.loads(envelope["output"])
            except (KeyError, TypeError, ValueError):
                continue
            if isinstance(payload, dict) and payload.get("outcome") == "tests_passed" and payload.get("exit_code") == 0:
                return True
    return False


async def execute_case(mode, provider, project, run, command):
    tools = build_tools(project, ["discount.py"], command, run / "tool-evidence")
    harness = Harness(provider, tools, budget=RunBudget(
        max_model_turns=6, total_timeout_seconds=120))
    store = SessionStore(run / "session.jsonl")
    before = (project / "discount.py").read_bytes()
    fixed_tests = (project / "test_discount.py").read_bytes()
    try:
        result = await harness.run(TASK, store)
    except asyncio.CancelledError:
        harness.agent.abort()
        await harness.agent.wait_for_idle()
        raise
    after = (project / "discount.py").read_bytes()
    (run / "discount.before.py").write_bytes(before)
    (run / "discount.after.py").write_bytes(after)
    (run / "change.diff").write_text("".join(difflib.unified_diff(
        before.decode().splitlines(keepends=True), after.decode().splitlines(keepends=True),
        fromfile="before/discount.py", tofile="after/discount.py")), encoding="utf-8")
    final_tests = run_fixed_tests(project, command, run / "independent-tests.txt")
    feedback = []
    passed_call_ids = set()
    successful_edit = False
    read_code = False
    model_observed_test_feedback = False
    for item in result.messages:
        if isinstance(item, ToolResult):
            read_code |= item.tool_name == "read_file" and item.error is None
            successful_edit |= item.tool_name == "edit_file" and item.error is None
            if item.tool_name == "run_tests" and item.error is None:
                payload = json.loads(item.output)
                feedback.append(payload)
                if payload.get("outcome") == "tests_passed" and payload.get("exit_code") == 0:
                    passed_call_ids.add(item.tool_call_id)
    records = getattr(provider, "request_records", None)
    if records is not None:
        save_json(run / "model-requests.json", records)
        model_observed_test_feedback = request_contains_passing_test_feedback(records, passed_call_ids)
    else:
        save_json(run / "mock-requests.json", [[asdict(item) for item in request]
                                                for request in provider.requests])
        for request in provider.requests:
            for item in request:
                if isinstance(item, ToolResult) and item.tool_name == "run_tests" and item.error is None:
                    model_observed_test_feedback |= json.loads(item.output).get("outcome") == "tests_passed"
    checks = {
        "run_finished": result.status == "finished",
        "real_file_changed": before != after,
        "test_file_unchanged": (project / "test_discount.py").read_bytes() == fixed_tests,
        "no_extra_source_files": sorted(p.name for p in project.iterdir() if p.is_file()) == ["discount.py", "test_discount.py"],
        "read_feedback_recorded": read_code,
        "successful_edit_recorded": successful_edit,
        "tool_recorded_failing_tests": any(x.get("outcome") == "tests_failed" for x in feedback),
        "tool_recorded_passing_tests": bool(feedback) and feedback[-1].get("outcome") == "tests_passed",
        "model_saw_passing_test_feedback": model_observed_test_feedback,
        "independent_fixed_tests_pass": final_tests["exit_code"] == 0,
        "jsonl_matches_returned_history": store.load().history == result.messages,
        "agent_idle": not harness.agent.is_running,
    }
    report = {"mode": mode, "status": result.status, "task_passed_in_run_result": result.task_passed,
              "checks": checks, "pipeline_checks_passed": all(checks.values()),
              "real_model_acceptance": mode == "live" and all(checks.values()),
              "independent_tests": final_tests, "session_path": str(store.path),
              "model_requests": len(records) if records is not None else len(provider.requests),
              "usage": [] if records is None else [r.get("usage") for r in records],
              "boundary": "offline为预设答案排演；真实自主修复只由live报告判断。RunResult不被外部验收器改写。"}
    save_json(run / "acceptance.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("prepare", "offline", "live"), default="prepare")
    options = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    run = repo / "local-learning/evidence" / ("d14-" + options.mode + "-" + uuid4().hex[:12])
    project = run / "project"
    project.mkdir(parents=True)
    fixture = Path(__file__).resolve().parent / "fixtures/d14_discount"
    for name in ("discount.py", "test_discount.py"):
        shutil.copy2(fixture / name, project / name)
    command = [sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", ".", "-p", "test_discount.py", "-v"]
    baseline = run_fixed_tests(project, command, run / "baseline-tests.txt")
    if baseline["exit_code"] != 1:
        raise RuntimeError("修复前测试未按预期失败，停止运行")
    config = {"mode": options.mode, "task": TASK, "workdir": str(project),
              "allowed_files": ["discount.py"], "test_command": command,
              "baseline": baseline, "model": "qwen3.8-flash" if options.mode == "live" else None,
              "max_model_turns": 6, "max_completion_tokens": 1024,
              "total_timeout_seconds": 120, "test_timeout_seconds": 30,
              "paid_model_selected": options.mode == "live"}
    save_json(run / "config.json", config)
    if options.mode == "prepare":
        print(json.dumps({"mode": "prepare", "evidence": str(run), "baseline": baseline,
                          "real_model_requests": 0}, ensure_ascii=False))
        return 0
    if options.mode == "live":
        from mini_pi.qwen_client import QwenProvider
        provider = QwenProvider(model="qwen3.8-flash", max_requests=6, max_completion_tokens=1024)
    else:
        provider = scripted_provider()
    report = asyncio.run(execute_case(options.mode, provider, project, run, command))
    print(json.dumps({"evidence": str(run), **report}, ensure_ascii=False))
    return 0 if report["pipeline_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
