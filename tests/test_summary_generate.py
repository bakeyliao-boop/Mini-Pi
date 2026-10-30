"""摘要调用：记录实际尝试、停止边界和清理。"""

import asyncio
import unittest
from unittest.mock import Mock

from mini_pi.compaction import SummaryError, generate_summary
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context_size import InputSizeEstimate
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message
from mini_pi.run_deadline import RunDeadlineExceeded
from mini_pi.summary_call_budget import SummaryCallBudget, SummaryCallBudgetExceeded


class SummaryGenerateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.history = [Message("user", "修复登录"), Message("assistant", "测试失败")]
        self.estimator = Mock(return_value=InputSizeEstimate(4, 1, "test"))
        self.window = ContextWindowBudget(100, 10)
        self.budget = SummaryCallBudget(1)

    def provider(self, response):
        provider = MockProvider([response])
        provider.max_completion_tokens = 10
        return provider

    async def test_success_then_exhaustion_counts_once_and_never_retries(self):
        provider = self.provider(Message("assistant", "测试失败，待排查", stop_reason="stop"))
        summary, estimate = await generate_summary(self.history, provider, self.estimator, self.window, self.budget)
        self.assertEqual(summary, "测试失败，待排查")
        self.assertEqual(estimate.estimated_input_tokens, 1)
        self.assertEqual(self.budget.used_calls, 1)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(provider.tool_requests[0], [])
        with self.assertRaises(SummaryCallBudgetExceeded):
            await generate_summary(self.history, provider, self.estimator, self.window, self.budget)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(self.budget.used_calls, 1)

    async def test_truncated_response_counts_as_attempt_but_is_not_accepted(self):
        provider = self.provider(Message("assistant", "部分", stop_reason="length"))
        with self.assertRaises(SummaryError):
            await generate_summary(self.history, provider, self.estimator, self.window, self.budget)
        self.assertEqual(self.budget.used_calls, 1)
        self.assertEqual(len(provider.requests), 1)

    async def test_expired_deadline_does_not_start_or_consume_call(self):
        provider = self.provider(Message("assistant", "完成", stop_reason="stop"))
        deadline = asyncio.get_running_loop().time() - 1
        with self.assertRaises(RunDeadlineExceeded):
            await generate_summary(self.history, provider, self.estimator, self.window, self.budget,
                                   deadline=deadline)
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.budget.used_calls, 0)
        self.estimator.assert_not_called()

    async def test_cancellation_waits_for_provider_cleanup(self):
        started, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class WaitingProvider:
            max_completion_tokens = 10

            async def generate(self, messages, tools):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    closing.set()
                    await release.wait()

        task = asyncio.create_task(generate_summary(self.history, WaitingProvider(), self.estimator,
                                                    self.window, self.budget))
        try:
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            await asyncio.wait_for(closing.wait(), 1)
            self.assertFalse(task.done())
            self.assertEqual(self.budget.used_calls, 1)
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
