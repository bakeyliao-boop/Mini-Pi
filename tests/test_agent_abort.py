"""D13-B 取消请求反例；等待收尾接口及真实资源边界后续独立验证。"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, Mock

from mini_pi.agent import Agent
from mini_pi.models import Message
from mini_pi.session_store import SessionStore


class AgentAbortTests(unittest.IsolatedAsyncioTestCase):
    def make_agent(self, hook=None):
        provider = Mock()
        provider.generate = AsyncMock(return_value=Message("assistant", "完成", stop_reason="stop"))
        executor = Mock()
        executor.execute = AsyncMock()
        return Agent(provider, executor, [], on_run_end=hook), provider, executor

    async def test_idle_abort_does_not_start_work(self):
        agent, provider, executor = self.make_agent()
        agent.abort()
        self.assertFalse(agent.is_running)
        provider.generate.assert_not_called()
        executor.execute.assert_not_called()

    async def test_abort_before_task_starts_records_cancelled_without_model(self):
        agent, provider, executor = self.make_agent()
        abort = agent.abort
        with TemporaryDirectory(prefix="_agent_abort_", dir=Path(__file__).parent) as directory:
            store = SessionStore(Path(directory) / "session.jsonl")
            pending = agent.prompt([Message("user", "A")], session_store=store)
            run = agent._active_run
            abort()
            self.assertTrue(agent.is_running)
            self.assertTrue(run.abort_requested)
            self.assertFalse(run.started)
            self.assertFalse(run.task.cancelled())
            result = await pending
            self.assertEqual(result.status, "cancelled")
            loaded = store.load()
            self.assertEqual([r["data"]["status"] for r in loaded.records
                              if r["type"] == "run_end"], ["cancelled"])
            self.assertEqual(loaded.history, result.messages)
            provider.generate.assert_not_called()
            executor.execute.assert_not_called()
            self.assertTrue(run.idle.is_set())

    async def test_repeated_abort_keeps_cleanup_waiting_and_blocks_new_prompt(self):
        entered, cancelling, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def generate(history, tools):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelling.set()
                await release.wait()
                raise
        agent, provider, executor = self.make_agent()
        abort = agent.abort
        provider.generate.side_effect = generate
        pending = agent.prompt([Message("user", "A")])
        run = agent._active_run
        try:
            async with asyncio.timeout(2):
                await entered.wait()
                abort()
                await cancelling.wait()
            abort()
            await asyncio.sleep(0)
            self.assertEqual(run.task.cancelling(), 1)
            self.assertTrue(agent.is_running)
            self.assertFalse(run.idle.is_set())
            self.assertFalse(pending.done())
            with self.assertRaises(RuntimeError):
                agent.prompt([Message("user", "B")])
            self.assertEqual(provider.generate.await_count, 1)
        finally:
            release.set()
            result = await pending
        self.assertEqual(result.status, "cancelled")
        self.assertFalse(agent.is_running)

    async def test_abort_during_end_callback_does_not_interrupt_closing(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def hook(result, error):
            entered.set()
            await release.wait()
        agent, provider, executor = self.make_agent(hook)
        abort = agent.abort
        pending = agent.prompt([Message("user", "A")])
        run = agent._active_run
        try:
            async with asyncio.timeout(2):
                await entered.wait()
            abort()
            self.assertTrue(run.closing)
            self.assertFalse(run.abort_requested)
            self.assertEqual(run.task.cancelling(), 0)
            self.assertTrue(agent.is_running)
            self.assertFalse(pending.done())
        finally:
            release.set()
            result = await pending
        self.assertEqual(result.status, "finished")
        self.assertTrue(run.idle.is_set())


if __name__ == "__main__":
    unittest.main()
