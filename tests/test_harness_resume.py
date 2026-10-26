"""D13-D 恢复接线：复用D11门禁，经过共享Agent且不重写旧历史。"""

import asyncio
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mini_pi.bootstrap import build_tools
from mini_pi.harness import Harness, RunBudget
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore


class HarnessResumeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_harness_resume_", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "old.jsonl"
        (self.root / "sample.txt").write_bytes(b"actual content\n")
        self.tools = build_tools(self.root, ["sample.txt"],
            (sys.executable, "-c", "raise SystemExit(0)"), self.root / "evidence")

    def seed(self, calls=None, *, many_turns=False):
        old = SessionStore(self.path, "old_run")
        old.append_entry("run_start", {"status": "running"})
        old.append_item(Message("user", "旧任务"))
        if many_turns:
            for index in range(4):
                old.append_item(Message("assistant", f"旧回复{index}"))
                old.append_item(Message("user", "旧继续"))
        if calls is None:
            old.append_item(Message("assistant", "旧任务完成", stop_reason="stop"))
            old.append_entry("run_end", {"status": "finished"})
        else:
            old.append_item(Message("assistant", "调用结果尚未知", calls))
        self.before = self.path.read_bytes()
        self.old = old.load().history
        return SessionStore(self.path, "resumed_run")

    def assert_incremental(self, store, outcome, status):
        self.assertEqual(outcome.plan.state, "ready")
        self.assertEqual(outcome.run_result.status, status)
        self.assertTrue(self.path.read_bytes().startswith(self.before))
        loaded = store.load()
        self.assertEqual(loaded.history, outcome.run_result.messages)
        new = [row for row in loaded.records if row["run_id"] == store.run_id]
        self.assertEqual(new[0]["type"], "run_start")
        self.assertEqual([row["data"]["status"] for row in new if row["type"] == "run_end"], [status])
        self.assertEqual(sum(row["type"] == "message" for row in loaded.records
                             if row["run_id"] == "old_run"), len(self.old))

    async def test_ready_resume_uses_shared_agent_queues_and_real_read(self):
        store = self.seed()
        provider = MockProvider([
            Message("assistant", "读取", [ToolCall("new_read", "read_file", {"path": "sample.txt"})]),
            Message("assistant", "恢复完成", stop_reason="stop"),
        ])
        hook = AsyncMock()
        harness = Harness(provider, self.tools, on_run_end=hook)
        original_agent = harness.agent
        harness.agent.steer("恢复时先解释")
        outcome = await harness.resume("本次继续", store)
        self.assert_incremental(store, outcome, "finished")
        self.assertIs(harness.agent, original_agent)
        self.assertEqual(provider.requests[0], self.old + [
            Message("user", "本次继续"), Message("user", "恢复时先解释")])
        self.assertEqual([item.output for item in outcome.run_result.messages if isinstance(item, ToolResult)],
                         ["actual content\n"])
        hook.assert_awaited_once_with(outcome.run_result, None)
        self.assertFalse(harness.agent.is_running)

    async def test_non_ready_is_zero_model_tool_or_record_append(self):
        for name, expected in (("read_file", "read_interrupted"), ("edit_file", "needs_review"),
                               ("run_tests", "needs_review"), ("unknown_tool", "needs_review")):
            with self.subTest(tool=name):
                self.path = self.root / (name + ".jsonl")
                store = self.seed([ToolCall("pending_001", name, {})])
                provider = MockProvider([Message("assistant", "不应请求")])
                harness = Harness(provider, self.tools)
                with patch.object(self.tools.executor, "execute", wraps=self.tools.executor.execute) as execute, \
                     patch.object(harness.agent, "prompt", wraps=harness.agent.prompt) as prompt:
                    outcome = await harness.resume("继续", store)
                self.assertEqual(outcome.plan.state, expected)
                self.assertIsNone(outcome.run_result)
                self.assertEqual(provider.requests, [])
                execute.assert_not_called()
                prompt.assert_not_called()
                self.assertEqual(self.path.read_bytes(), self.before)

    async def test_invalid_pairing_is_rejected_without_append(self):
        store = self.seed()
        old = SessionStore(self.path, "old_run")
        old.append_item(ToolResult("orphan", "read_file", "orphan result"))
        before = self.path.read_bytes()
        provider = MockProvider([Message("assistant", "不应请求")])
        harness = Harness(provider, self.tools)
        with self.assertRaises(ValueError):
            await harness.resume("继续", store)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(provider.requests, [])

    async def test_old_turns_do_not_consume_new_turn_budget(self):
        store = self.seed(many_turns=True)
        provider = MockProvider([
            Message("assistant", "读取", [ToolCall("new_read", "read_file", {"path": "sample.txt"})]),
            Message("assistant", "不应第二次请求"),
        ])
        harness = Harness(provider, self.tools, budget=RunBudget(max_model_turns=1))
        outcome = await harness.resume("继续", store)
        self.assert_incremental(store, outcome, "budget_exhausted")
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(provider.requests[0], self.old + [Message("user", "继续")])
        self.assertEqual([r.tool_call_id for r in outcome.run_result.messages if isinstance(r, ToolResult)],
                         ["new_read"])

    async def test_time_budget_reaches_resume_and_cleans_model(self):
        store = self.seed()
        cleaned = asyncio.Event()
        async def generate(history, tools):
            try:
                await asyncio.Future()
            finally:
                cleaned.set()
        provider = Mock()
        provider.generate = AsyncMock(side_effect=generate)
        harness = Harness(provider, self.tools, budget=RunBudget(total_timeout_seconds=0.1))
        async with asyncio.timeout(3):
            outcome = await harness.resume("继续", store)
        self.assert_incremental(store, outcome, "timeout")
        self.assertTrue(cleaned.is_set())
        self.assertEqual(provider.generate.await_count, 1)

    async def test_busy_resume_is_rejected_before_loading_or_appending(self):
        store = self.seed()
        entered, release = asyncio.Event(), asyncio.Event()
        async def generate(history, tools):
            entered.set()
            await release.wait()
            return Message("assistant", "完成", stop_reason="stop")
        provider = Mock()
        provider.generate = AsyncMock(side_effect=generate)
        harness = Harness(provider, self.tools)
        pending = harness.run("当前任务", SessionStore(self.root / "active.jsonl"))
        try:
            async with asyncio.timeout(3):
                await entered.wait()
            with patch.object(store, "load", side_effect=AssertionError("忙碌时不应加载")):
                with self.assertRaises(RuntimeError):
                    await harness.resume("不应恢复", store)
            self.assertEqual(self.path.read_bytes(), self.before)
            self.assertEqual(provider.generate.await_count, 1)
        finally:
            release.set()
            await pending

    async def test_reused_run_id_is_rejected_before_append(self):
        self.seed()
        store = SessionStore(self.path, "old_run")
        provider = MockProvider([Message("assistant", "不应请求")])
        harness = Harness(provider, self.tools)
        with self.assertRaises(ValueError):
            await harness.resume("继续", store)
        self.assertEqual(self.path.read_bytes(), self.before)
        self.assertEqual(provider.requests, [])

    async def test_invalid_text_is_rejected_before_load(self):
        store = self.seed()
        provider = MockProvider([Message("assistant", "不应请求")])
        harness = Harness(provider, self.tools)
        with patch.object(store, "load", side_effect=AssertionError("无效输入不应加载")):
            for text in (None, 123, "", " \n"):
                with self.subTest(text=text):
                    with self.assertRaises(ValueError):
                        await harness.resume(text, store)
        self.assertEqual(self.path.read_bytes(), self.before)
        self.assertEqual(provider.requests, [])

    async def test_missing_session_is_not_created_by_resume(self):
        store = SessionStore(self.root / "missing.jsonl")
        provider = MockProvider([Message("assistant", "不应请求")])
        harness = Harness(provider, self.tools)
        with self.assertRaises(FileNotFoundError):
            await harness.resume("继续", store)
        self.assertFalse(store.path.exists())
        self.assertEqual(provider.requests, [])


if __name__ == "__main__":
    unittest.main()
