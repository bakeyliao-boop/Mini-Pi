"""助手准备：外部取消等待中的循环，验证清理、结果保存和后续调用边界。"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock

from mini_pi.executor import ToolExecutor
from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_recovery import find_pending_calls
from mini_pi.session_store import SessionStore


class CancellableProvider:
    """started 确认已经进入等待；cleaned 确认协程的 finally 已执行。"""

    def __init__(self):
        self.started = asyncio.Event()
        self.requests = 0
        self.cleaned = False

    async def generate(self, history, tools):
        self.requests += 1
        self.started.set()
        try:
            await asyncio.Future()
        finally:
            self.cleaned = True


class CancellableSecondExecutor:
    """第一项返回结果，第二项等待外部取消；第三项不应启动。"""

    def __init__(self):
        self.started = asyncio.Event()
        self.calls = []
        self.cleaned = False

    async def execute(self, call):
        self.calls.append(call.id)
        if len(self.calls) == 1:
            return ToolResult(call.id, call.name, "第一项已完成的结果")
        self.started.set()
        try:
            await asyncio.Future()
        finally:
            self.cleaned = True


class LoopCancelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_cancel_", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "session.jsonl"
        self.initial = [Message("user", "运行可取消的测试场景。")]

    async def _settle_task(self, task):
        """测试断言失败时也收尾，避免留下测试自身的异步任务。"""
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    async def _cancel_after_started(self, operation, started):
        task = asyncio.create_task(operation)
        self.addAsyncCleanup(self._settle_task, task)
        # 同步事件替代猜测 sleep 时间；看门狗只约束测试本身。
        async with asyncio.timeout(2):
            await started.wait()
            self.assertFalse(task.done())
            self.assertTrue(task.cancel())
            result = await task
        self.assertTrue(task.done())
        return result

    def assert_cancelled_result(self, result, store=None):
        self.assertEqual(result.status, "cancelled")
        self.assertIsNone(result.task_passed)
        self.assertIsNone(result.error)
        if store is None:
            return None
        loaded = store.load()
        self.assertEqual(loaded.history, result.messages)
        ends = [record for record in loaded.records if record["type"] == "run_end"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]["data"], {
            "status": "cancelled", "task_passed": None, "error": None,
        })
        return loaded

    async def test_cancel_waiting_model_preserves_history_and_records_end(self):
        provider = CancellableProvider()
        executor = AsyncMock(spec=ToolExecutor)
        store = SessionStore(self.path, "run_A")
        result = await self._cancel_after_started(
            run_loop(
                provider, executor, self.initial, [], store,
                total_timeout_seconds=10,
            ),
            provider.started,
        )
        self.assertTrue(provider.cleaned)
        self.assertEqual(provider.requests, 1)
        executor.execute.assert_not_called()
        self.assertEqual(result.messages, self.initial)
        self.assert_cancelled_result(result, store)

    async def test_cancel_waiting_model_without_store_still_returns_result(self):
        provider = CancellableProvider()
        executor = AsyncMock(spec=ToolExecutor)
        result = await self._cancel_after_started(
            run_loop(provider, executor, self.initial, []), provider.started,
        )
        self.assertTrue(provider.cleaned)
        self.assertEqual(provider.requests, 1)
        executor.execute.assert_not_called()
        self.assertEqual(result.messages, self.initial)
        self.assert_cancelled_result(result)
        self.assertFalse(self.path.exists())

    async def test_cancel_waiting_tool_preserves_completed_result_and_pending(self):
        calls = [
            ToolCall("read_001", "read_file", {"path": "one.txt"}),
            ToolCall("read_002", "read_file", {"path": "two.txt"}),
            ToolCall("read_003", "read_file", {"path": "three.txt"}),
        ]
        provider = MockProvider([Message("assistant", "依次读取三个文件。", calls)])
        executor = CancellableSecondExecutor()
        store = SessionStore(self.path, "run_A")
        result = await self._cancel_after_started(
            run_loop(
                provider, executor, self.initial, [], store,
                total_timeout_seconds=10,
            ),
            executor.started,
        )
        self.assertTrue(executor.cleaned)
        self.assertEqual(executor.calls, ["read_001", "read_002"])
        self.assertEqual(len(provider.requests), 1)
        results = [item for item in result.messages if isinstance(item, ToolResult)]
        self.assertEqual(results, [ToolResult("read_001", "read_file", "第一项已完成的结果")])
        loaded = self.assert_cancelled_result(result, store)
        self.assertEqual([item.call.id for item in find_pending_calls(loaded)], [
            "read_002", "read_003",
        ])


if __name__ == "__main__":
    unittest.main()
