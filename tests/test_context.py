"""请求上下文必须可替换、隔离原始历史，并传播错误和取消。"""

import asyncio
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock

from mini_pi.context import ContextProvider, FullHistoryContext
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolDefinition, ToolResult


class ContextTests(unittest.IsolatedAsyncioTestCase):
    def history(self):
        return [Message("user", "读文件"),
                Message("assistant", "", [ToolCall("r1", "read_file", {"path": "a.py"})]),
                ToolResult("r1", "read_file", "完整结果")]

    async def test_default_preserves_order_tool_pair_and_definitions(self):
        raw = self.history()
        before = deepcopy(raw)
        tools = [ToolDefinition("read_file", "读取", {"type": "object"})]
        provider = MockProvider([Message("assistant", "完成")])
        wrapped = ContextProvider(provider, FullHistoryContext())
        reply = await wrapped.generate(raw, tools)
        self.assertEqual(reply, Message("assistant", "完成"))
        self.assertEqual(provider.requests, [before])
        self.assertEqual(provider.tool_requests, [tools])
        self.assertEqual(raw, before)

    async def test_builder_runs_each_request_and_cannot_mutate_raw_items(self):
        raw = self.history()
        before = deepcopy(raw)
        class Builder:
            async def build(self, items):
                items[0].content = "仅请求可见"
                items[1].tool_calls[0].arguments["path"] = "request-only.py"
                items[-1].output = "请求副本"
                return list(items)
        builder = Builder()
        builder.build = AsyncMock(wraps=builder.build)
        provider = MockProvider([Message("assistant", "一"), Message("assistant", "二")])
        wrapped = ContextProvider(provider, builder)
        await wrapped.generate(raw, [])
        await wrapped.generate(raw, [])
        self.assertEqual(builder.build.await_count, 2)
        self.assertEqual(raw, before)
        self.assertEqual(provider.requests[0][0].content, "仅请求可见")
        self.assertEqual(provider.requests[1][-1].output, "请求副本")

    async def test_construction_does_not_build_or_request(self):
        builder = AsyncMock()
        provider = MockProvider([])
        ContextProvider(provider, builder)
        builder.build.assert_not_called()
        self.assertEqual(provider.requests, [])

    async def test_builder_error_propagates_before_provider(self):
        builder = AsyncMock()
        builder.build.side_effect = RuntimeError("组装失败")
        provider = MockProvider([])
        wrapped = ContextProvider(provider, builder)
        with self.assertRaisesRegex(RuntimeError, "组装失败"):
            await wrapped.generate(self.history(), [])
        self.assertEqual(provider.requests, [])

    async def test_cancel_during_build_cleans_up_without_provider_request(self):
        entered, cleaned = asyncio.Event(), asyncio.Event()
        class Builder:
            async def build(self, history):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaned.set()
        provider = MockProvider([])
        wrapped = ContextProvider(provider, Builder())
        task = asyncio.create_task(wrapped.generate(self.history(), []))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(cleaned.is_set())
            self.assertEqual(provider.requests, [])
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
