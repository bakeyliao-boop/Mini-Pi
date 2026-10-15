"""助手准备：D12 总时限的配置和异步等待边界，接入前行为测试待验收。"""

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


class WaitingProvider:
    """模拟没有响应的模型；finally 标记协程已经清理。"""

    def __init__(self):
        self.requests = 0
        self.cleaned = False

    async def generate(self, history, tools):
        self.requests += 1
        try:
            await asyncio.Future()
        finally:
            self.cleaned = True


class WaitingSecondExecutor:
    """第一个结果正常返回；第二个调用持续等待，取消时标记清理。"""

    def __init__(self):
        self.calls = []
        self.cleaned = False

    async def execute(self, call):
        self.calls.append(call.id)
        if len(self.calls) == 1:
            return ToolResult(call.id, call.name, "第一项已完成的结果")
        try:
            await asyncio.Future()
        finally:
            self.cleaned = True


class LoopTimeoutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_timeout_", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "session.jsonl"
        self.initial = [Message("user", "执行测试场景。")]

    async def test_invalid_timeout_stops_before_any_side_effect(self):
        for value in (0, -1, True, "1", float("nan"), float("inf")):
            with self.subTest(value=value):
                provider = MockProvider([Message("assistant", "不应请求模型。")])
                executor = AsyncMock(spec=ToolExecutor)
                with self.assertRaisesRegex(ValueError, "total_timeout_seconds"):
                    await run_loop(
                        provider, executor, self.initial, [],
                        SessionStore(self.path, "run_A"), total_timeout_seconds=value,
                    )
                self.assertEqual(provider.requests, [])
                executor.execute.assert_not_called()
                self.assertFalse(self.path.exists())

    def assert_timeout_record(self, store, result):
        self.assertEqual(result.status, "timeout")
        self.assertIsNone(result.task_passed)
        loaded = store.load()
        self.assertEqual(loaded.history, result.messages)
        ends = [record for record in loaded.records if record["type"] == "run_end"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]["data"]["status"], "timeout")
        self.assertIsNone(ends[0]["data"]["task_passed"])
        return loaded

    async def test_waiting_model_times_out_and_cleans_up(self):
        provider = WaitingProvider()
        executor = AsyncMock(spec=ToolExecutor)
        store = SessionStore(self.path, "run_A")
        # 独立测试看门狗：未接入超时的实现也不会让测试无限等待。
        async with asyncio.timeout(2):
            result = await run_loop(
                provider, executor, self.initial, [], store,
                total_timeout_seconds=0.03,
            )
        self.assertEqual(provider.requests, 1)
        self.assertTrue(provider.cleaned)
        executor.execute.assert_not_called()
        self.assertEqual(result.messages, self.initial)
        self.assert_timeout_record(store, result)

    async def test_waiting_tool_preserves_completed_result_and_unknown_call(self):
        calls = [
            ToolCall("read_001", "read_file", {"path": "one.txt"}),
            ToolCall("read_002", "read_file", {"path": "two.txt"}),
            ToolCall("read_003", "read_file", {"path": "three.txt"}),
        ]
        provider = MockProvider([Message("assistant", "依次读取三个文件。", calls)])
        executor = WaitingSecondExecutor()
        store = SessionStore(self.path, "run_A")
        async with asyncio.timeout(2):
            result = await run_loop(
                provider, executor, self.initial, [], store,
                total_timeout_seconds=0.03,
            )
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(executor.calls, ["read_001", "read_002"])
        self.assertTrue(executor.cleaned)
        results = [item for item in result.messages if isinstance(item, ToolResult)]
        self.assertEqual(results, [ToolResult("read_001", "read_file", "第一项已完成的结果")])
        loaded = self.assert_timeout_record(store, result)
        self.assertEqual([item.call.id for item in find_pending_calls(loaded)], [
            "read_002", "read_003",
        ])

    async def test_fast_response_with_a_time_limit_finishes_normally(self):
        provider = MockProvider([Message("assistant", "正常回答。")])
        executor = AsyncMock(spec=ToolExecutor)
        result = await run_loop(
            provider, executor, self.initial, [], total_timeout_seconds=1.0,
        )
        self.assertEqual(result.status, "finished")
        self.assertEqual(len(provider.requests), 1)
        executor.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
