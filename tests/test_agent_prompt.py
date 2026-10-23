"""D13-B 公开提交入口：真实循环、同步占位、收尾门禁和等待取消隔离。"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mini_pi.agent import Agent
from mini_pi.models import Message
from mini_pi.session_store import SessionStore


class AgentPromptTests(unittest.IsolatedAsyncioTestCase):
    def make_agent(self, hook=None):
        provider = Mock()
        provider.generate = AsyncMock(return_value=Message("assistant", "完成", stop_reason="stop"))
        executor = Mock()
        executor.execute = AsyncMock()
        return Agent(provider, executor, [], on_run_end=hook), provider, executor

    async def test_immediate_occupancy_duplicate_rejection_and_next_run(self):
        agent, provider, executor = self.make_agent()
        pending = agent.prompt([Message("user", "A")])
        self.assertTrue(agent.is_running)
        provider.generate.assert_not_called()
        with self.assertRaises(RuntimeError):
            agent.prompt([Message("user", "B")])
        self.assertEqual((await pending).status, "finished")
        self.assertEqual(provider.generate.await_count, 1)
        self.assertFalse(agent.is_running)
        self.assertEqual((await agent.prompt([Message("user", "C")])).status, "finished")
        self.assertEqual(provider.generate.await_count, 2)
        executor.execute.assert_not_called()

    async def test_callback_waiting_blocks_new_prompt_and_new_records(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def hook(result, error):
            entered.set()
            await release.wait()
        agent, provider, executor = self.make_agent(hook)
        with TemporaryDirectory(prefix="_agent_prompt_", dir=Path(__file__).parent) as directory:
            store = SessionStore(Path(directory) / "session.jsonl")
            pending = agent.prompt([Message("user", "A")], session_store=store)
            try:
                async with asyncio.timeout(2):
                    await entered.wait()
                saved = store.path.read_bytes()
                self.assertTrue(agent.is_running)
                self.assertFalse(pending.done())
                with self.assertRaises(RuntimeError):
                    agent.prompt([Message("user", "B")], session_store=store)
                self.assertEqual(store.path.read_bytes(), saved)
                self.assertEqual(provider.generate.await_count, 1)
            finally:
                release.set()
                await pending
            self.assertFalse(agent.is_running)

    async def test_cancel_waiter_does_not_cancel_model_or_run(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def generate(history, tools):
            entered.set()
            await release.wait()
            return Message("assistant", "完成", stop_reason="stop")
        agent, provider, executor = self.make_agent()
        provider.generate.side_effect = generate
        pending = agent.prompt([Message("user", "A")])
        run = agent._active_run
        try:
            async with asyncio.timeout(2):
                await entered.wait()
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            self.assertTrue(agent.is_running)
            self.assertFalse(run.task.done())
            self.assertFalse(run.abort_requested)
        finally:
            release.set()
            result = await run.task
        self.assertEqual(result.status, "finished")
        self.assertTrue(run.idle.is_set())
        self.assertFalse(agent.is_running)

    async def test_task_creation_failure_closes_coroutine_and_releases(self):
        agent, provider, executor = self.make_agent()
        marker = RuntimeError("调度失败对照")
        operations = []
        def fail_creation(operation):
            operations.append(operation)
            raise marker
        with patch.object(asyncio.get_running_loop(), "create_task", side_effect=fail_creation):
            with self.assertRaises(RuntimeError) as caught:
                agent.prompt([Message("user", "A")])
        self.assertIs(caught.exception, marker)
        self.assertIsNone(operations[0].cr_frame)
        self.assertFalse(agent.is_running)
        provider.generate.assert_not_called()
        executor.execute.assert_not_called()

    async def test_submission_copies_list_and_transmits_budget_and_session(self):
        agent, provider, executor = self.make_agent()
        messages = [Message("user", "A")]
        with TemporaryDirectory(prefix="_agent_budget_", dir=Path(__file__).parent) as directory:
            store = SessionStore(Path(directory) / "session.jsonl")
            pending = agent.prompt(messages, session_store=store, max_model_turns=1,
                                   total_timeout_seconds=2)
            messages.append(Message("user", "提交后追加"))
            result = await pending
            loaded = store.load()
            self.assertEqual(loaded.history, result.messages)
            self.assertEqual([m.content for m in result.messages], ["A", "完成"])
            self.assertEqual([r["data"]["status"] for r in loaded.records
                              if r["type"] == "run_end"], ["finished"])

    async def test_internal_and_callback_errors_are_visible_without_stuck_slot(self):
        for location in ("model", "callback"):
            with self.subTest(location=location):
                marker = AssertionError(location)
                hook = AsyncMock(side_effect=marker) if location == "callback" else None
                agent, provider, executor = self.make_agent(hook)
                if location == "model":
                    provider.generate.side_effect = marker
                pending = agent.prompt([Message("user", "A")])
                run = agent._active_run
                with self.assertRaises(AssertionError) as caught:
                    await pending
                self.assertIs(caught.exception, marker)
                self.assertFalse(agent.is_running)
                self.assertTrue(run.idle.is_set())


if __name__ == "__main__":
    unittest.main()
