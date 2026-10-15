"""助手准备：真实启动本次测试进程树，核对取消/超时/正常退出后的存活状态。"""

import asyncio
import ctypes
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_recovery import find_pending_calls
from mini_pi.session_store import SessionStore
from mini_pi.tools import managed_process
from mini_pi.tools.run_tests import RunTestsExecutor


TREE_SCRIPT = '''import json, os, subprocess, sys, time
from pathlib import Path
marker = Path(sys.argv[1])
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
print('tree ready', flush=True)
temporary = marker.with_suffix('.tmp')
temporary.write_text(json.dumps([os.getpid(), child.pid]), encoding='utf-8')
temporary.replace(marker)
if sys.argv[2] != 'exit':
    time.sleep(60)
'''


def process_is_running(pid):
    """检查已记录的本次 PID；Windows 用进程句柄是否已收到退出信号。"""
    if os.name == "nt":
        from ctypes import wintypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.CloseHandle.restype = wintypes.BOOL
        handle = api.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: PID 已不存在
                return False
            raise ctypes.WinError(error)
        try:
            result = api.WaitForSingleObject(handle, 0)
            if result == 0:
                return False
            if result == 258:
                return True
            raise ctypes.WinError(ctypes.get_last_error())
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = Path(f"/proc/{pid}/stat")
    if stat.exists() and stat.read_text().split(") ", 1)[1].startswith("Z"):
        return False
    return True


class ProcessCleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_process_cleanup_", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.marker = self.root / "pids.json"
        self.script = self.root / "process_fixture.py"
        self.script.write_text(TREE_SCRIPT, encoding="utf-8")
        self.evidence = self.root / "evidence"
        self.store = SessionStore(self.root / "session.jsonl", "run_A")

    def executor(self, mode="wait", timeout=30):
        return RunTestsExecutor(
            self.root, (sys.executable, "-X", "utf8", str(self.script), str(self.marker), mode),
            self.evidence, timeout_seconds=timeout,
        )

    async def settle(self, task):
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    def start(self, operation):
        task = asyncio.create_task(operation)
        self.addAsyncCleanup(self.settle, task)
        return task

    async def ready(self, task):
        async with asyncio.timeout(5):
            while not self.marker.exists():
                if task.done():
                    task.result()
                    self.fail("测试进程在创建存活证据之前结束")
                await asyncio.sleep(0.01)
        pids = json.loads(self.marker.read_text(encoding="utf-8"))
        self.assertTrue(all(process_is_running(pid) for pid in pids))
        return pids

    def assert_tree_stopped(self, outcome):
        traces = list(self.evidence.glob("run-tests-process-*.json"))
        traces = [path for path in traces if not path.name.endswith(".worker.json")]
        self.assertEqual(len(traces), 1)
        trace = json.loads(traces[0].read_text(encoding="utf-8"))
        self.assertEqual(trace["outcome"], outcome)
        self.assertTrue(trace["waiter_done"])
        if os.name == "nt":
            self.assertTrue(trace["tree_empty"])
        pids = [trace["supervisor_pid"]]
        if self.marker.exists():
            pids += json.loads(self.marker.read_text(encoding="utf-8"))
        self.assertFalse(any(process_is_running(pid) for pid in pids))
        return trace

    async def test_own_timeout_stops_real_test_and_descendant(self):
        task = self.start(self.executor(timeout=1).execute(ToolCall("tests_001", "run_tests", {})))
        await self.ready(task)
        async with asyncio.timeout(5):
            result = await task
        self.assertEqual(json.loads(result.output)["outcome"], "timeout")
        self.assertIn("超时", result.error or "")
        self.assert_tree_stopped("timeout")

    async def test_direct_cancellation_cleans_tree_before_propagating(self):
        task = self.start(self.executor().execute(ToolCall("tests_001", "run_tests", {})))
        await self.ready(task)
        task.cancel()
        async with asyncio.timeout(5):
            with self.assertRaises(asyncio.CancelledError):
                await task
        trace = self.assert_tree_stopped("cancelled")
        self.assertIn("tree ready", Path(trace["output_path"]).read_text(encoding="utf-8"))

    def loop_task(self, total_timeout=None):
        calls = [ToolCall("tests_001", "run_tests", {}), ToolCall("tests_002", "run_tests", {})]
        provider = MockProvider([Message("assistant", "依次测试。", calls)])
        executor = self.executor()
        task = self.start(run_loop(
            provider, executor, [Message("user", "运行固定测试。")], [executor.definition],
            self.store, total_timeout_seconds=total_timeout,
        ))
        return task, provider

    def assert_loop_end(self, result, status, provider):
        self.assertEqual(result.status, status)
        self.assertIsNone(result.task_passed)
        self.assertFalse(any(isinstance(item, ToolResult) for item in result.messages))
        loaded = self.store.load()
        self.assertEqual(loaded.history, result.messages)
        self.assertEqual(loaded.records[-1]["type"], "run_end")
        self.assertEqual(loaded.records[-1]["data"]["status"], status)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual([item.call.id for item in find_pending_calls(loaded)], ["tests_001", "tests_002"])

    async def test_loop_cancellation_waits_for_real_process_tree(self):
        task, provider = self.loop_task()
        await self.ready(task)
        task.cancel()
        async with asyncio.timeout(5):
            result = await task
        self.assert_loop_end(result, "cancelled", provider)
        self.assert_tree_stopped("cancelled")

    async def test_loop_total_timeout_cleans_tree_before_returning_timeout(self):
        task, provider = self.loop_task(total_timeout=1)
        await self.ready(task)
        async with asyncio.timeout(5):
            result = await task
        self.assert_loop_end(result, "timeout", provider)
        # 总时限的取消信号先到进程辅助层，再由 await_before_deadline 转换。
        self.assert_tree_stopped("cancelled")

    async def test_normal_exit_also_cleans_remaining_descendant(self):
        result = await self.executor(mode="exit").execute(ToolCall("tests_001", "run_tests", {}))
        self.assertIsNone(result.error)
        self.assertEqual(json.loads(result.output)["outcome"], "tests_passed")
        self.assertTrue(self.marker.exists())
        self.assert_tree_stopped("completed")

    async def test_second_cancel_cannot_skip_cleanup(self):
        cleaning = asyncio.Event()
        release = asyncio.Event()
        real_cleanup = managed_process._stop_and_wait

        async def pause_after_stopping(*args):
            await real_cleanup(*args)
            cleaning.set()
            await release.wait()

        with patch.object(managed_process, "_stop_and_wait", pause_after_stopping):
            task = self.start(self.executor().execute(ToolCall("tests_001", "run_tests", {})))
            await self.ready(task)
            task.cancel()
            async with asyncio.timeout(5):
                await cleaning.wait()
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        self.assert_tree_stopped("cancelled")

    async def test_attach_failure_does_not_start_actual_test(self):
        with patch.object(managed_process.ProcessTree, "attach", side_effect=OSError("测试绑定失败")):
            result = await self.executor().execute(ToolCall("tests_001", "run_tests", {}))
        self.assertEqual(json.loads(result.output)["outcome"], "execution_error")
        self.assertFalse(self.marker.exists())
        self.assert_tree_stopped("execution_error")


if __name__ == "__main__":
    unittest.main()
