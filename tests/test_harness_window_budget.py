"""D16跨层：Harness两入口的窗口预算、真实截止时间和取消收尾。"""

import asyncio
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mini_pi.bootstrap import build_tools
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context_size import InputSizeEstimate
from mini_pi.harness import Harness, RunBudget
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message
from mini_pi.session_store import SessionStore


class HarnessWindowBudgetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="d16-window-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.tools = build_tools(self.root, [], [sys.executable, "-c", "pass"], self.root / "evidence")

    def session(self, resume):
        store = SessionStore(self.root / ("resume.jsonl" if resume else "new.jsonl"), "current")
        before = b""
        if resume:
            old = SessionStore(store.path, "old")
            old.append_entry("run_start", {"status": "running"})
            old.append_item(Message("user", "旧问题"))
            old.append_item(Message("assistant", "旧回答"))
            old.append_entry("run_end", {"status": "finished"})
            before = store.path.read_bytes()
        return store, before

    async def submit(self, harness, store, resume):
        if resume:
            outcome = await harness.resume("继续", store)
            self.assertEqual(outcome.plan.state, "ready")
            return outcome.run_result
        return await harness.run("新问题", store)

    def check_finished(self, harness, store, before, result, status):
        self.assertEqual(result.status, status)
        self.assertIsNone(result.task_passed)
        self.assertFalse(harness.agent.is_running)
        loaded = store.load()
        self.assertEqual(loaded.history, result.messages)
        rows = [r for r in loaded.records if r["run_id"] == "current" and r["type"] == "run_end"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["data"]["status"], status)
        self.assertEqual(rows[0]["data"]["error"], result.error)
        self.assertTrue(store.path.read_bytes().startswith(before))

    async def test_both_entries_send_when_exact_budget_fits(self):
        for resume in (False, True):
            with self.subTest(resume=resume):
                provider = MockProvider([Message("assistant", "完成")])
                estimator = Mock(return_value=InputSizeEstimate(320, 80, "fixture"))
                hook = AsyncMock()
                harness = Harness(provider, self.tools, input_estimator=estimator,
                                  window_budget=ContextWindowBudget(100, 15, 5), on_run_end=hook)
                store, before = self.session(resume)
                result = await self.submit(harness, store, resume)
                self.check_finished(harness, store, before, result, "finished")
                self.assertEqual(len(provider.requests), 1)
                self.assertEqual(estimator.call_args.args[0], provider.requests[0])
                self.assertEqual(estimator.call_args.args[1], provider.tool_requests[0])
                hook.assert_awaited_once_with(result, None)

    async def test_both_entries_record_budget_exhausted_without_model_or_tool_calls(self):
        for resume in (False, True):
            with self.subTest(resume=resume):
                provider = MockProvider([])
                hook = AsyncMock()
                harness = Harness(provider, self.tools,
                                  input_estimator=Mock(return_value=InputSizeEstimate(324, 81, "fixture")),
                                  window_budget=ContextWindowBudget(100, 15, 5), on_run_end=hook)
                execute = AsyncMock(side_effect=AssertionError("预算失败后不能执行工具"))
                harness.agent._executor = SimpleNamespace(execute=execute)
                store, before = self.session(resume)
                result = await self.submit(harness, store, resume)
                self.check_finished(harness, store, before, result, "budget_exhausted")
                self.assertIn("101", result.error)
                self.assertEqual(provider.requests, [])
                execute.assert_not_awaited()
                hook.assert_awaited_once_with(result, None)

    async def test_sync_build_overrun_is_timeout_before_actual_model_send(self):
        async def slow_build(items):
            time.sleep(0.04)
            return items
        for resume in (False, True):
            with self.subTest(resume=resume):
                provider = MockProvider([Message("assistant", "不应发送")])
                harness = Harness(provider, self.tools, context_builder=SimpleNamespace(build=slow_build),
                                  budget=RunBudget(total_timeout_seconds=0.01))
                store, before = self.session(resume)
                result = await self.submit(harness, store, resume)
                self.check_finished(harness, store, before, result, "timeout")
                self.assertEqual(provider.requests, [])

    async def test_estimator_overrun_is_timeout_even_if_estimate_also_exceeds_budget(self):
        def slow_estimate(messages, tools):
            time.sleep(0.04)
            return InputSizeEstimate(40000, 10000, "slow-fixture")
        for resume in (False, True):
            with self.subTest(resume=resume):
                provider = MockProvider([])
                harness = Harness(provider, self.tools, input_estimator=slow_estimate,
                                  window_budget=ContextWindowBudget(100, 10),
                                  budget=RunBudget(total_timeout_seconds=0.01))
                store, before = self.session(resume)
                result = await self.submit(harness, store, resume)
                self.check_finished(harness, store, before, result, "timeout")
                self.assertEqual(provider.requests, [])

    async def test_prepared_route_passes_same_deadline_to_actual_send(self):
        async def prepare(items):
            return items
        for resume in (False, True):
            with self.subTest(resume=resume):
                loop = asyncio.get_running_loop()
                real_time = loop.time
                advance = [0.0]
                def slow_estimate(messages, tools):
                    advance[0] += 20.0  # 准备已完成后才推进测试时钟，避免依赖10ms启动竞态。
                    return InputSizeEstimate(4, 1, "clock-advance-fixture")
                provider = MockProvider([Message("assistant", "不应发送")])
                preparing = AsyncMock(side_effect=prepare)
                harness = Harness(provider, self.tools, prepare_messages=preparing,
                                  input_estimator=slow_estimate, window_budget=ContextWindowBudget(100, 10),
                                  budget=RunBudget(total_timeout_seconds=10.0))
                store, before = self.session(resume)
                with patch.object(loop, "time", side_effect=lambda: real_time() + advance[0]), \
                     patch.object(loop, "slow_callback_duration", float("inf")):
                    result = await self.submit(harness, store, resume)
                self.check_finished(harness, store, before, result, "timeout")
                preparing.assert_awaited_once()
                self.assertEqual(provider.requests, [])

    async def test_async_build_timeout_finishes_cleanup_before_run_end(self):
        cleaned = asyncio.Event()
        async def waiting(items):
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
        provider = MockProvider([])
        harness = Harness(provider, self.tools, context_builder=SimpleNamespace(build=waiting),
                          budget=RunBudget(total_timeout_seconds=0.02))
        store, before = self.session(False)
        result = await self.submit(harness, store, False)
        self.assertTrue(cleaned.is_set())
        self.check_finished(harness, store, before, result, "timeout")
        self.assertEqual(provider.requests, [])

    async def test_abort_keeps_agent_busy_until_builder_cleanup(self):
        started, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def waiting(items):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closing.set()
                await release.wait()
        provider = MockProvider([])
        harness = Harness(provider, self.tools, context_builder=SimpleNamespace(build=waiting))
        store, before = self.session(False)
        task = asyncio.create_task(self.submit(harness, store, False))
        try:
            await asyncio.wait_for(started.wait(), 1)
            harness.agent.abort()
            harness.agent.abort()
            await asyncio.wait_for(closing.wait(), 1)
            self.assertTrue(harness.agent.is_running)
            self.assertFalse(task.done())
            self.assertNotEqual(store.load().records[-1]["type"], "run_end")
            release.set()
            result = await asyncio.wait_for(task, 1)
            self.check_finished(harness, store, before, result, "cancelled")
            self.assertEqual(provider.requests, [])
        finally:
            release.set()
            if not task.done():
                harness.agent.abort()
            await asyncio.gather(task, return_exceptions=True)

    async def test_cancel_during_estimation_is_recorded_as_cancelled(self):
        def cancelling(messages, tools):
            asyncio.current_task().cancel()
            return InputSizeEstimate(4, 1, "cancel-fixture")
        provider = MockProvider([])
        harness = Harness(provider, self.tools, input_estimator=cancelling,
                          window_budget=ContextWindowBudget(100, 10))
        store, before = self.session(False)
        result = await self.submit(harness, store, False)
        self.check_finished(harness, store, before, result, "cancelled")
        self.assertEqual(provider.requests, [])

    def test_output_reservation_matches_exposed_provider_limit(self):
        for limit in (1024, 0, -1, True):
            with self.subTest(limit=limit):
                provider = MockProvider([])
                provider.max_completion_tokens = limit
                with self.assertRaises(ValueError):
                    Harness(provider, self.tools, input_estimator=Mock(),
                            window_budget=ContextWindowBudget(2000, 1000))
                self.assertEqual(provider.requests, [])
        provider = MockProvider([])
        provider.max_completion_tokens = 1024
        Harness(provider, self.tools, input_estimator=Mock(), window_budget=ContextWindowBudget(2000, 1024))
        self.assertEqual(provider.requests, [])

    async def test_actual_provider_programming_error_still_propagates(self):
        provider = SimpleNamespace(generate=AsyncMock(side_effect=OSError("provider-internal")))
        hook = AsyncMock()
        harness = Harness(provider, self.tools, input_estimator=Mock(return_value=InputSizeEstimate(4, 1, "fixture")),
                          window_budget=ContextWindowBudget(100, 10), on_run_end=hook)
        store, _ = self.session(False)
        with self.assertRaisesRegex(OSError, "provider-internal"):
            await self.submit(harness, store, False)
        self.assertFalse(harness.agent.is_running)
        self.assertIsInstance(hook.await_args.args[1], OSError)


if __name__ == "__main__":
    unittest.main()
