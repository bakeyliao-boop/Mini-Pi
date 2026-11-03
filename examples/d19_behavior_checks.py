"""D19：离线运行既有行为测试，并用内存反例验证截断保护测试。"""

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import importlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    "工具反馈与执行前保护": (
        "test_loop.py", "test_read_file.py", "test_tool_hooks.py",
        "test_loop_truncated_batch.py", "test_truncated_call_conversion.py",
    ),
    "运行控制与资源收尾": (
        "test_loop_budget.py", "test_loop_timeout.py", "test_loop_cancel.py",
        "test_agent_abort.py", "test_agent_idle.py", "test_agent_resources.py",
        "test_list_cancel.py",
    ),
    "会话恢复": (
        "test_session_resume.py", "test_session_recovery.py",
        "test_session_resume_gate.py", "test_harness_resume.py",
    ),
    "请求副本与摘要": (
        "test_read_output_context.py", "test_memory_read_output_integration.py",
        "test_harness_compaction_resume.py", "test_auto_compaction_loop.py",
        "test_harness_auto_compaction.py", "test_compaction_continuation.py",
    ),
}


def test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_ids(item)
        else:
            yield item.id()


def git_text(*arguments):
    completed = subprocess.run(
        ["git", *arguments], cwd=ROOT, text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True,
    )
    return completed.stdout.strip()


def check_counterexample():
    """仅替换测试进程内的函数；不改写项目源码。"""
    loop_module = importlib.import_module("mini_pi.loop")
    cases = importlib.import_module("test_loop_truncated_batch")
    source_path = ROOT / "mini_pi" / "loop.py"
    original = source_path.read_text(encoding="utf-8")
    guard = '        if message.stop_reason == "length":'
    if original.count(guard) != 1:
        raise RuntimeError("无法唯一定位截断保护，停止反例验证")
    namespace = vars(loop_module).copy()
    changed = original.replace(guard, "        if False:  # D19 内存反例", 1)
    exec(compile(changed, str(source_path), "exec"), namespace)
    case = cases.LoopTruncatedBatchTests(
        "test_valid_json_calls_are_all_rejected_before_executor"
    )
    output = io.StringIO()
    with patch.object(cases, "run_loop", namespace["run_loop"]):
        result = unittest.TextTestRunner(stream=output, verbosity=2).run(case)
    observation = case.observation
    source_unchanged = source_path.read_text(encoding="utf-8") == original
    expected_failure = (
        result.testsRun == 1 and len(result.failures) == 1 and not result.errors
        and observation.get("executed_call_ids") == ["edit_001", "read_001"]
        and observation.get("file_contents") == "value = 2\n"
        and source_unchanged
    )
    return {
        "expected_failure_observed": expected_failure,
        "source_file_unchanged": source_unchanged,
        "observation": observation,
        "test_output": output.getvalue(),
    }


def main():
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))
    output_base = ROOT / "local-learning" / "evidence" / "d19-checks"
    output_base.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    output_dir = Path(tempfile.mkdtemp(
        prefix=started.strftime("%Y%m%dT%H%M%SZ-"), dir=output_base,
    ))
    output_path = output_dir / "output.txt"
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    selected = []
    for group, filenames in GROUPS.items():
        for filename in filenames:
            cases = loader.discover(str(ROOT / "tests"), pattern=filename)
            names = list(test_ids(cases))
            if not names:
                raise RuntimeError(f"测试文件没有发现用例：{filename}")
            selected.append({"group": group, "file": f"tests/{filename}", "tests": names})
            suite.addTests(cases)
    print(f"D19：{len(selected)} 个测试文件，{suite.countTestCases()} 项测试", flush=True)
    with output_path.open("w", encoding="utf-8", newline="") as output:
        with redirect_stdout(output), redirect_stderr(output):
            result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
            # 原实现全部通过后，再确认同一测试能发现停用保护后的错误。
            counterexample = check_counterexample() if result.wasSuccessful() else None
            if counterexample is not None:
                output.write("\nD19 受控反例（这里应当发现失败）：\n")
                output.write(counterexample["test_output"])
    report = {
        "schema": "mini-pi-d19-checks/v1",
        "started_at_utc": started.isoformat(),
        "python": platform.python_version(),
        "git_head": git_text("rev-parse", "HEAD"),
        "working_tree_status": git_text("status", "--short"),
        "selection": selected,
        "tests_run": result.testsRun,
        "failures": [{"test": case.id(), "traceback": details} for case, details in result.failures],
        "errors": [{"test": case.id(), "traceback": details} for case, details in result.errors],
        "skipped": [{"test": case.id(), "reason": reason} for case, reason in result.skipped],
        "expected_failures": [case.id() for case, _ in result.expectedFailures],
        "unexpected_successes": [case.id() for case in result.unexpectedSuccesses],
        "normal_tests_successful": result.wasSuccessful(),
        "counterexample": counterexample,
        "output_file": str(output_path),
    }
    successful = result.wasSuccessful() and counterexample is not None and counterexample["expected_failure_observed"]
    report["successful"] = successful
    result_path = output_dir / "result.json"
    result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "tests_run": result.testsRun,
        "failures": len(result.failures), "errors": len(result.errors),
        "skipped": len(result.skipped),
        "counterexample_detected": bool(counterexample and counterexample["expected_failure_observed"]),
        "successful": successful,
        "report": str(result_path), "output": str(output_path),
    }, ensure_ascii=False, indent=2))
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
