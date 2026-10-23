"""D13-B：生命周期行为反例；随分段实现补齐真实收尾边界验证。"""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from mini_pi import agent as agent_module
from mini_pi.models import Message


class AgentInitialStateTests(unittest.TestCase):
    def test_new_agent_is_idle_and_does_not_start_work(self):
        provider = Mock()
        provider.generate = AsyncMock()
        executor = Mock()
        executor.execute = AsyncMock()
        on_run_end = AsyncMock()
        agent = agent_module.Agent(provider, executor, [], on_run_end=on_run_end)
        self.assertFalse(agent.is_running)
        provider.generate.assert_not_called()
        executor.execute.assert_not_called()
        on_run_end.assert_not_called()


class AgentReservationTests(unittest.TestCase):
    def setUp(self):
        self.provider = Mock()
        self.provider.generate = AsyncMock()
        self.executor = Mock()
        self.executor.execute = AsyncMock()
        self.on_run_end = AsyncMock()
        self.agent = agent_module.Agent(
            self.provider, self.executor, [], on_run_end=self.on_run_end,
        )

    def assert_no_work(self):
        self.provider.generate.assert_not_called()
        self.executor.execute.assert_not_called()
        self.on_run_end.assert_not_called()

    def test_reservation_marks_busy_without_starting_work(self):
        run = self.agent._reserve_run()
        self.assertTrue(self.agent.is_running)
        self.assertFalse(run.idle.is_set())
        self.assertIsNone(run.task)
        self.assertFalse(run.started)
        self.assertFalse(run.abort_requested)
        self.assertFalse(run.closing)
        self.assert_no_work()

    def test_duplicate_reservation_preserves_original_occupancy(self):
        run = self.agent._reserve_run()
        with self.assertRaises(RuntimeError):
            self.agent._reserve_run()
        self.assertIs(self.agent._active_run, run)
        self.assertFalse(run.idle.is_set())
        self.assert_no_work()

    def test_closing_run_is_still_occupied(self):
        run = self.agent._reserve_run()
        run.closing = True
        with self.assertRaises(RuntimeError):
            self.agent._reserve_run()
        self.assertTrue(self.agent.is_running)
        self.assertIs(self.agent._active_run, run)
        self.assertFalse(run.idle.is_set())
        self.assert_no_work()


class AgentRunOwnerTests(unittest.IsolatedAsyncioTestCase):
    def make_agent(self, *, on_run_end=None):
        provider = Mock()
        provider.generate = AsyncMock(return_value=Message("assistant", "完成", stop_reason="stop"))
        executor = Mock()
        executor.execute = AsyncMock()
        agent = agent_module.Agent(provider, executor, [], on_run_end=on_run_end)
        return agent, provider, executor

    async def test_normal_run_releases_and_notifies_after_callback(self):
        hook = AsyncMock()
        agent, provider, executor = self.make_agent(on_run_end=hook)
        run = agent._reserve_run()
        run.task = asyncio.create_task(agent._run(run, [Message("user", "回答")], {}))
        result = await run.task
        self.assertEqual(result.status, "finished")
        hook.assert_awaited_once_with(result, None)
        self.assertFalse(agent.is_running)
        self.assertTrue(run.idle.is_set())
        executor.execute.assert_not_called()

    async def test_callback_barrier_keeps_occupancy_until_settled(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        async def hook(result, error):
            self.assertEqual(result.status, "finished")
            self.assertIsNone(error)
            entered.set()
            await release.wait()
        agent, provider, executor = self.make_agent(on_run_end=hook)
        run = agent._reserve_run()
        run.task = asyncio.create_task(agent._run(run, [Message("user", "回答")], {}))
        try:
            async with asyncio.timeout(2):
                await entered.wait()
            self.assertTrue(agent.is_running)
            self.assertTrue(run.closing)
            self.assertFalse(run.idle.is_set())
            with self.assertRaises(RuntimeError):
                agent._reserve_run()
            self.assertEqual(provider.generate.await_count, 1)
        finally:
            release.set()
            await run.task
        self.assertFalse(agent.is_running)
        self.assertTrue(run.idle.is_set())

    async def test_internal_error_remains_visible_but_releases_occupancy(self):
        hook = AsyncMock()
        agent, provider, executor = self.make_agent(on_run_end=hook)
        marker = AssertionError("内部异常对照")
        provider.generate.side_effect = marker
        run = agent._reserve_run()
        run.task = asyncio.create_task(agent._run(run, [Message("user", "回答")], {}))
        with self.assertRaises(AssertionError) as caught:
            await run.task
        self.assertIs(caught.exception, marker)
        hook.assert_awaited_once_with(None, marker)
        self.assertFalse(agent.is_running)
        self.assertTrue(run.idle.is_set())

    async def test_abort_requested_before_start_reaches_loop_without_model_request(self):
        agent, provider, executor = self.make_agent()
        run = agent._reserve_run()
        run.abort_requested = True
        run.task = asyncio.create_task(agent._run(run, [Message("user", "回答")], {}))
        result = await run.task
        self.assertEqual(result.status, "cancelled")
        provider.generate.assert_not_called()
        executor.execute.assert_not_called()
        self.assertFalse(agent.is_running)
        self.assertTrue(run.idle.is_set())


if __name__ == "__main__":
    unittest.main()
