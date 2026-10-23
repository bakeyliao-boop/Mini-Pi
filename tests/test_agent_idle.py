"""D13-B 等待空闲反例：捕获本次运行、等结束回调、隔离等待者取消。"""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from mini_pi.agent import Agent
from mini_pi.models import Message


class AgentIdleTests(unittest.IsolatedAsyncioTestCase):
    def make_agent(self, hook=None):
        provider = Mock()
        provider.generate = AsyncMock(return_value=Message("assistant", "完成", stop_reason="stop"))
        executor = Mock()
        executor.execute = AsyncMock()
        return Agent(provider, executor, [], on_run_end=hook), provider, executor

    async def test_idle_wait_is_bound_before_later_prompt_starts(self):
        agent, provider, executor = self.make_agent()
        wait = agent.wait_for_idle()
        pending = agent.prompt([Message("user", "A")])
        try:
            async with asyncio.timeout(2):
                self.assertIsNone(await wait)
            self.assertTrue(agent.is_running)
            provider.generate.assert_not_called()
        finally:
            await pending

    async def test_wait_includes_callback_and_abort_does_not_release_early(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def hook(result, error):
            entered.set()
            await release.wait()
        agent, provider, executor = self.make_agent(hook)
        wait_method = agent.wait_for_idle
        pending = agent.prompt([Message("user", "A")])
        waiter = asyncio.create_task(wait_method())
        try:
            async with asyncio.timeout(2):
                await entered.wait()
            agent.abort()
            await asyncio.sleep(0)
            self.assertFalse(waiter.done())
            self.assertTrue(agent.is_running)
            with self.assertRaises(RuntimeError):
                agent.prompt([Message("user", "B")])
        finally:
            release.set()
            await pending
            self.assertIsNone(await waiter)
        self.assertFalse(agent.is_running)

    async def test_cancel_idle_waiter_does_not_cancel_run(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def generate(history, tools):
            entered.set()
            await release.wait()
            return Message("assistant", "完成", stop_reason="stop")
        agent, provider, executor = self.make_agent()
        wait_method = agent.wait_for_idle
        provider.generate.side_effect = generate
        pending = agent.prompt([Message("user", "A")])
        waiter = asyncio.create_task(wait_method())
        try:
            async with asyncio.timeout(2):
                await entered.wait()
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            self.assertTrue(agent.is_running)
            self.assertEqual(agent._active_run.task.cancelling(), 0)
            self.assertFalse(pending.done())
        finally:
            release.set()
            await pending
        self.assertIsNone(await agent.wait_for_idle())

    async def test_wait_on_A_does_not_follow_later_run_B(self):
        agent, provider, executor = self.make_agent()
        wait_method = agent.wait_for_idle
        pending_A = agent.prompt([Message("user", "A")])
        wait_A = wait_method()
        await pending_A
        entered, release = asyncio.Event(), asyncio.Event()
        async def generate(history, tools):
            entered.set()
            await release.wait()
            return Message("assistant", "完成", stop_reason="stop")
        provider.generate.side_effect = generate
        pending_B = agent.prompt([Message("user", "B")])
        try:
            async with asyncio.timeout(2):
                await entered.wait()
                self.assertIsNone(await wait_A)
            self.assertTrue(agent.is_running)
            self.assertFalse(pending_B.done())
        finally:
            release.set()
            await pending_B


if __name__ == "__main__":
    unittest.main()
