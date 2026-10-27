"""发送前预算门禁：估算最终内容，超限或取消时不进入实际Provider。"""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, AsyncMock

from mini_pi.context import ContextProvider, FullHistoryContext, ReadOutputContext
from mini_pi.context_budget import ContextBudgetError, ContextWindowBudget
from mini_pi.context_size import InputSizeEstimate, estimate_qwen_input
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolDefinition, ToolResult


class ContextProviderBudgetTests(unittest.IsolatedAsyncioTestCase):
    def history(self):
        return [Message("user", "读取文件"),
                Message("assistant", "", [ToolCall("r1", "read_file", {"path": "a.py"})]),
                ToolResult("r1", "read_file", "正文" * 1000)]

    def test_paired_configuration_and_callable_are_required(self):
        provider = MockProvider([])
        budget = ContextWindowBudget(100, 15, 5)
        for options in ({"window_budget": budget}, {"input_estimator": estimate_qwen_input},
                        {"input_estimator": 12, "window_budget": budget}):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    ContextProvider(provider, FullHistoryContext(), **options)
        self.assertEqual(provider.requests, [])

    def test_construction_does_not_estimate_build_or_send(self):
        builder = SimpleNamespace(build=AsyncMock())
        estimator = Mock(return_value=InputSizeEstimate(4, 1, "fixture"))
        provider = MockProvider([])
        wrapped = ContextProvider(provider, builder, input_estimator=estimator,
                                  window_budget=ContextWindowBudget(100, 15, 5))
        self.assertIsNone(wrapped.last_estimate)
        estimator.assert_not_called()
        builder.build.assert_not_called()
        self.assertEqual(provider.requests, [])

    async def test_exact_budget_sends_once_and_records_estimate(self):
        size = InputSizeEstimate(320, 80, "fixture")
        estimator = Mock(return_value=size)
        provider = MockProvider([Message("assistant", "完成")])
        wrapped = ContextProvider(provider, FullHistoryContext(), input_estimator=estimator,
                                  window_budget=ContextWindowBudget(100, 15, 5))
        await wrapped.generate(self.history(), [])
        self.assertEqual(len(provider.requests), 1)
        estimator.assert_called_once()
        self.assertEqual(wrapped.last_estimate, size)

    async def test_one_token_over_budget_keeps_estimate_without_sending(self):
        original = self.history()
        before = deepcopy(original)
        size = InputSizeEstimate(324, 81, "fixture")
        provider = MockProvider([])
        wrapped = ContextProvider(provider, FullHistoryContext(),
                                  input_estimator=Mock(return_value=size),
                                  window_budget=ContextWindowBudget(100, 15, 5))
        with self.assertRaises(ContextBudgetError):
            await wrapped.generate(original, [])
        self.assertEqual(provider.requests, [])
        self.assertEqual(wrapped.last_estimate, size)
        self.assertEqual(original, before)

    async def test_estimator_receives_built_messages_and_same_tools_as_provider(self):
        original = self.history()
        tools = [ToolDefinition("read_file", "读取", {"type": "object"})]
        before = deepcopy((original, tools))
        estimator = Mock(wraps=estimate_qwen_input)
        provider = MockProvider([Message("assistant", "完成")])
        wrapped = ContextProvider(provider, ReadOutputContext(120), input_estimator=estimator,
                                  window_budget=ContextWindowBudget(10000, 100, 10))
        await wrapped.generate(original, tools)
        measured_messages, measured_tools = estimator.call_args.args
        self.assertEqual(len(measured_messages[-1].output), 120)
        self.assertEqual(measured_messages, provider.requests[0])
        self.assertEqual(measured_tools, provider.tool_requests[0])
        self.assertEqual((original, tools), before)

    async def test_large_tool_definitions_block_request(self):
        messages = [Message("user", "短问题")]
        base = estimate_qwen_input(messages, [])
        provider = MockProvider([])
        wrapped = ContextProvider(provider, FullHistoryContext(), input_estimator=estimate_qwen_input,
                                  window_budget=ContextWindowBudget(base.estimated_input_tokens + 10, 10))
        large_tools = [ToolDefinition("read_file", "工具说明" * 1000, {"type": "object"})]
        with self.assertRaises(ContextBudgetError):
            await wrapped.generate(messages, large_tools)
        self.assertEqual(provider.requests, [])

    async def test_tools_are_snapshotted_before_async_build(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def build(items):
            started.set()
            await release.wait()
            return items
        messages = self.history()
        tools = [ToolDefinition("read_file", "原说明", {"type": "object"})]
        before = deepcopy((messages, tools))
        provider = MockProvider([Message("assistant", "完成")])
        estimator = Mock(wraps=estimate_qwen_input)
        wrapped = ContextProvider(provider, SimpleNamespace(build=build), input_estimator=estimator,
                                  window_budget=ContextWindowBudget(10000, 100))
        task = asyncio.create_task(wrapped.generate(messages, tools))
        try:
            await asyncio.wait_for(started.wait(), 1)
            messages[0].content = "外部更新"
            tools[0].parameters["type"] = "外部更新"
            release.set()
            await asyncio.wait_for(task, 1)
            self.assertEqual(provider.requests[0], before[0])
            self.assertEqual(provider.tool_requests[0], before[1])
            self.assertEqual(estimator.call_args.args[1], before[1])
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_cancel_after_estimation_blocks_provider(self):
        def estimate(messages, tools):
            asyncio.current_task().cancel()
            return InputSizeEstimate(4, 1, "cancel-fixture")
        provider = MockProvider([])
        wrapped = ContextProvider(provider, FullHistoryContext(), input_estimator=estimate,
                                  window_budget=ContextWindowBudget(100, 10))
        task = asyncio.create_task(wrapped.generate(self.history(), []))
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(provider.requests, [])

    async def test_failed_next_build_clears_previous_estimate(self):
        history = self.history()
        builder = SimpleNamespace(build=AsyncMock(side_effect=[history, RuntimeError("构建失败")]))
        provider = MockProvider([Message("assistant", "完成")])
        wrapped = ContextProvider(provider, builder,
                                  input_estimator=Mock(return_value=InputSizeEstimate(4, 1, "fixture")),
                                  window_budget=ContextWindowBudget(100, 10))
        await wrapped.generate(history, [])
        self.assertIsNotNone(wrapped.last_estimate)
        with self.assertRaisesRegex(RuntimeError, "构建失败"):
            await wrapped.generate(history, [])
        self.assertIsNone(wrapped.last_estimate)
        self.assertEqual(len(provider.requests), 1)

    async def test_estimator_error_blocks_provider_without_recording_stale_size(self):
        provider = MockProvider([])
        wrapped = ContextProvider(provider, FullHistoryContext(),
                                  input_estimator=Mock(side_effect=ValueError("无法估算")),
                                  window_budget=ContextWindowBudget(100, 10))
        with self.assertRaisesRegex(ValueError, "无法估算"):
            await wrapped.generate(self.history(), [])
        self.assertIsNone(wrapped.last_estimate)
        self.assertEqual(provider.requests, [])


if __name__ == "__main__":
    unittest.main()
