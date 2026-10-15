"""助手准备：真实固定进程配合模拟模型，保存预算、总时限和主动取消轨迹。"""

import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_recovery import find_pending_calls
from mini_pi.session_store import SessionStore
from mini_pi.tools.run_tests import RunTestsExecutor
from tests.test_process_cleanup import TREE_SCRIPT, process_is_running


async def run_case(root, kind):
    root.mkdir()
    marker = root / "pids.json"
    if kind == "budget_exhausted":
        command = (sys.executable, "-X", "utf8", "-c", "print('fixed process completed', flush=True)")
        responses = [
            Message("assistant", "运行固定命令。", [ToolCall("tests_001", "run_tests", {})]),
            Message("assistant", "再次运行固定命令。", [ToolCall("tests_002", "run_tests", {})]),
            Message("assistant", "预算应阻止第三次请求。"),
        ]
    else:
        script = root / "process_fixture.py"
        script.write_text(TREE_SCRIPT, encoding="utf-8")
        command = (sys.executable, "-X", "utf8", str(script), str(marker), "wait")
        responses = [Message("assistant", "提出两个测试调用。", [
            ToolCall("tests_001", "run_tests", {}), ToolCall("tests_002", "run_tests", {}),
        ])]
    executor = RunTestsExecutor(root, command, root / "logs", timeout_seconds=30)
    provider = MockProvider(responses)
    store = SessionStore(root / "session.jsonl", f"run_{kind}")
    task = asyncio.create_task(run_loop(
        provider, executor, [Message("user", "验证本次运行的执行控制。")],
        [executor.definition], store,
        max_model_turns=2 if kind == "budget_exhausted" else None,
        total_timeout_seconds=1 if kind == "timeout" else None,
    ))
    try:
        async with asyncio.timeout(10):
            if kind != "budget_exhausted":
                while not marker.exists():
                    if task.done():
                        task.result()
                        raise AssertionError("进程未产生启动证据便结束")
                    await asyncio.sleep(0.01)
                pids = json.loads(marker.read_text(encoding="utf-8"))
                assert all(process_is_running(pid) for pid in pids)
                if kind == "cancelled":
                    task.cancel()
            result = await task
    finally:
        if not task.done():
            task.cancel()
            await task
    loaded = store.load()
    traces = [json.loads(path.read_text(encoding="utf-8"))
              for path in (root / "logs").glob("run-tests-process-*.json")
              if not path.name.endswith(".worker.json")]
    pids = [trace["supervisor_pid"] for trace in traces]
    if marker.exists():
        pids += json.loads(marker.read_text(encoding="utf-8"))
    results = [item for item in result.messages if isinstance(item, ToolResult)]
    checks = {
        "运行返回预期状态": result.status == kind,
        "没有自动宣称任务验收通过": result.task_passed is None,
        "内存与已存历史一致": loaded.history == result.messages,
        "结束事件状态一致": loaded.records[-1]["type"] == "run_end" and loaded.records[-1]["data"]["status"] == kind,
        "本次所有记录PID均已停止": not any(process_is_running(pid) for pid in pids),
        "进程等待线程任务已收尾": all(trace["waiter_done"] for trace in traces),
        "模型及进程启动次数受控": len(provider.requests) == len(traces) == (2 if kind == "budget_exhausted" else 1),
        "只保存实际取得的工具结果": len(results) == (2 if kind == "budget_exhausted" else 0),
    }
    if os.name == "nt":
        checks["Windows受控Job活动进程为零"] = all(trace["tree_empty"] for trace in traces)
    summary = {
        "status": result.status, "task_passed": result.task_passed,
        "model_requests": len(provider.requests),
        "pending_calls": [asdict(item) for item in find_pending_calls(loaded)],
        "process_traces": traces, "recorded_pids": pids,
        "checks": checks,
    }
    (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    assert all(checks.values()), checks
    return summary


async def main():
    root = Path(__file__).resolve().parents[1] / "local-learning" / "evidence" / f"d12-control-{uuid4().hex}"
    root.mkdir(parents=True)
    scenarios = [await run_case(root / kind, kind) for kind in ("budget_exhausted", "timeout", "cancelled")]
    report = {
        "scope": "助手准备场景，模拟模型配合真实固定进程。预算场景只打印退出，不运行业务测试；超时与取消场景实际启动长等待程序及子进程，并验证回收。未请求真实模型服务。",
        "platform": sys.platform,
        "scenarios": scenarios,
    }
    (root / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"证据目录：{root}")
    for scenario in scenarios:
        print(f"{scenario['status']}: model={scenario['model_requests']}, "
              f"process_trees={len(scenario['process_traces'])}, checks=PASS")


if __name__ == "__main__":
    asyncio.run(main())
