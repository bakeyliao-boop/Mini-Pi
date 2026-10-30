"""直接发送已组装请求：不重复处理并保留最终门禁。"""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from mini_pi.context import ContextProvider
from mini_pi.context_budget import ContextBudgetError, ContextWindowBudget
from mini_pi.context_size import estimate_qwen_input
from mini_pi.memory.errors import MemoryContextError
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolDefinition, ToolResult
from mini_pi.run_deadline import RunDeadlineExceeded


class SendPreparedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.messages = [Message("system", "规则"), Message("user", "参考资料"), Message("user", "摘要"),
                         Message("assistant", "读取", [ToolCall("r", "read_file", {"path": "a"})]),
                         ToolResult("r", "read_file", "已缩短的内容")]
        self.tools = [ToolDefinition("read_file", "读取", {"type": "object"})]

    async def test_sends_exact_prepared_request_without_rebuilding(self):
        builder = SimpleNamespace(build=AsyncMock())
        model = MockProvider([Message("assistant", "回答")])
        estimator = Mock(wraps=estimate_qwen_input)
        provider = ContextProvider(model, builder, input_estimator=estimator,
                                   window_budget=ContextWindowBudget(10000, 100))
        before = deepcopy((self.messages, self.tools))
        result = await provider.send_prepared(self.messages, self.tools, max_context_chars=10000)
        self.assertEqual(result.content, "回答")
        self.assertEqual(model.requests[0], before[0])
        self.assertEqual(model.tool_requests[0], before[1])
        self.assertEqual(estimator.call_args.args, before)
        self.assertEqual((self.messages, self.tools), before)
        builder.build.assert_not_awaited()

    async def test_over_budget_or_deadline_never_calls_model(self):
        model = MockProvider([])
        provider = ContextProvider(model, SimpleNamespace(build=AsyncMock()), input_estimator=estimate_qwen_input,
                                   window_budget=ContextWindowBudget(50, 10))
        with self.assertRaises(ContextBudgetError):
            await provider.send_prepared(self.messages, self.tools)
        with self.assertRaises(MemoryContextError):
            await provider.send_prepared(self.messages, self.tools, max_context_chars=1)
        with self.assertRaises(RunDeadlineExceeded):
            await provider.send_prepared(self.messages, self.tools, deadline=asyncio.get_running_loop().time() - 1)
        self.assertEqual(model.requests, [])

    async def test_cancellation_waits_for_model_cleanup(self):
        started, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        class WaitingModel:
            async def generate(self, messages, tools):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaning.set()
                    await release.wait()
        provider = ContextProvider(WaitingModel(), SimpleNamespace(build=AsyncMock()), input_estimator=estimate_qwen_input,
                                   window_budget=ContextWindowBudget(10000, 100))
        task = asyncio.create_task(provider.send_prepared(self.messages, self.tools))
        try:
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            await asyncio.wait_for(cleaning.wait(), 1)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
