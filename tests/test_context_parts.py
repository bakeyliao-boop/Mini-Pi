"""D17：检查历史与临时资料在构建阶段保持分离。"""

from copy import deepcopy
import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from mini_pi.context import ContextParts, ContextProvider, build_separate_context, check_request_chars
from mini_pi.context_budget import ContextBudgetError, ContextWindowBudget
from mini_pi.context_size import InputSizeEstimate
from mini_pi.memory.context_helpers import messages_char_count
from mini_pi.memory.errors import MemoryContextError
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolResult
from mini_pi.run_deadline import RunDeadlineExceeded


class ContextPartsTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_receives_combined_request_after_builder_and_budget(self):
        parts = ContextParts([Message("user", "原始历史")], [Message("user", "临时资料")])
        before = deepcopy(parts)
        builder = type("Builder", (), {"build": AsyncMock(side_effect=lambda history: history)})()
        estimator = Mock(return_value=InputSizeEstimate(20, 5, "test"))
        provider = MockProvider([Message("assistant", "完成")])
        wrapped = ContextProvider(provider, builder, input_estimator=estimator,
                                  window_budget=ContextWindowBudget(100, 10))
        await wrapped.generate(parts, [], max_context_chars=10000)
        self.assertEqual(builder.build.call_args.args[0], before.history)
        self.assertEqual(provider.requests[0], before.references + before.history)
        self.assertEqual(estimator.call_args.args[0], provider.requests[0])
        self.assertEqual(parts, before)

    async def test_invalid_or_over_budget_requests_never_reach_provider(self):
        parts = ContextParts([Message("user", "历史")], [Message("user", "资料")])
        provider = MockProvider([])
        builder = type("Builder", (), {"build": AsyncMock(side_effect=lambda history: history)})()
        estimator = Mock(return_value=InputSizeEstimate(100, 91, "test"))
        wrapped = ContextProvider(provider, builder, input_estimator=estimator,
                                  window_budget=ContextWindowBudget(100, 10))
        with self.assertRaises(MemoryContextError):
            await wrapped.generate(parts, [], max_context_chars=1)
        estimator.assert_not_called()
        with self.assertRaises(ContextBudgetError):
            await wrapped.generate(parts, [], max_context_chars=10000)
        with self.assertRaises(ValueError):
            await wrapped.generate(parts, [], max_context_chars=True)
        with self.assertRaises(MemoryContextError):
            await wrapped.generate(ContextParts([ToolResult("missing", "read", "x")], []),
                                   [], max_context_chars=10000)
        with self.assertRaises(RunDeadlineExceeded):
            await wrapped.generate(parts, [], max_context_chars=10000,
                                   deadline=asyncio.get_running_loop().time() - 1)
        self.assertEqual(provider.requests, [])

    def test_character_limit_applies_to_complete_combined_request(self):
        messages = [Message("user", "历史"), Message("user", "参考资料")]
        size = messages_char_count(messages)
        check_request_chars(messages, size)
        with self.assertRaises(MemoryContextError):
            check_request_chars(messages, size - 1)
        for limit in (0, -1, True):
            with self.subTest(limit=limit), self.assertRaises(MemoryContextError):
                check_request_chars(messages, limit)

    async def test_builder_receives_only_history_and_cannot_mutate_inputs(self):
        parts = ContextParts(
            history=[Message("system", "规则"), Message("user", "同一段文字")],
            references=[Message("user", "同一段文字")],
        )
        original = deepcopy(parts)

        class RecordingBuilder:
            async def build(self, history):
                self.seen = deepcopy(history)
                history[1].content = "整理后的历史"
                return history

        builder = RecordingBuilder()
        messages = await build_separate_context(builder, parts)
        self.assertEqual(builder.seen, original.history)
        self.assertEqual(parts, original)
        self.assertEqual([m.content for m in messages], ["规则", "同一段文字", "整理后的历史"])


if __name__ == "__main__":
    unittest.main()
