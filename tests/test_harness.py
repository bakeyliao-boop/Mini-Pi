"""D13-D 新任务入口：共享Agent、真实文件/JSONL、预算与重入门禁。"""

import asyncio
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, Mock

from mini_pi.bootstrap import build_tools
from mini_pi.harness import Harness, RunBudget
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore


class HarnessRunTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_harness_", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "value.py").write_bytes(b"value = 1\n")
        self.tools = build_tools(self.root, ["value.py"],
            (sys.executable, "-c", "raise SystemExit(0)"), self.root / "evidence")
        self.store = SessionStore(self.root / "A.jsonl")

    def provider(self):
        return MockProvider([Message("assistant", "完成", stop_reason="stop")])

    def assert_saved(self, result, store, status):
        self.assertEqual(result.status, status)
        loaded = store.load()
        self.assertEqual(loaded.history, result.messages)
        self.assertEqual([row["data"]["status"] for row in loaded.records
                          if row["type"] == "run_end"], [status])
        self.assertEqual({row["run_id"] for row in loaded.records}, {store.run_id})

    async def test_construction_does_not_request_model_or_create_session_file(self):
        provider = self.provider()
        hook = AsyncMock()
        harness = Harness(provider, self.tools, on_run_end=hook)
        self.assertFalse(harness.agent.is_running)
        self.assertEqual(provider.requests, [])
        hook.assert_not_called()
        self.assertFalse(self.store.path.exists())
        self.assertFalse((self.root / "evidence").exists())

    async def test_new_task_uses_agent_real_read_and_jsonl(self):
        provider = MockProvider([
            Message("assistant", "读取", [ToolCall("read_001", "read_file", {"path": "value.py"})]),
            Message("assistant", "完成", stop_reason="stop"),
        ])
        hook = AsyncMock()
        harness = Harness(provider, self.tools, on_run_end=hook)
        pending = harness.run("读取value.py", self.store)
        self.assertTrue(harness.agent.is_running)
        result = await pending
        self.assert_saved(result, self.store, "finished")
        self.assertEqual(provider.requests[0], [Message("user", "读取value.py")])
        self.assertEqual([t.name for t in provider.tool_requests[0]],
                         ["list_files", "read_file", "edit_file", "run_tests"])
        self.assertEqual([item.output for item in result.messages if isinstance(item, ToolResult)],
                         ["value = 1\n"])
        hook.assert_awaited_once_with(result, None)
        self.assertFalse(harness.agent.is_running)

    async def test_existing_session_is_not_appended_as_new_task(self):
        self.store.append_entry("run_start", {"status": "running"})
        self.store.append_item(Message("user", "旧任务"))
        self.store.append_entry("run_end", {"status": "finished"})
        before = self.store.path.read_bytes()
        provider = self.provider()
        harness = Harness(provider, self.tools)
        with self.assertRaises(FileExistsError):
            harness.run("不应写入", self.store)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(provider.requests, [])
        self.assertFalse(harness.agent.is_running)

    async def test_invalid_user_text_does_not_submit_or_create_records(self):
        provider = self.provider()
        harness = Harness(provider, self.tools)
        for text in (None, 123, "", " \n"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    harness.run(text, self.store)
        self.assertFalse(self.store.path.exists())
        self.assertEqual(provider.requests, [])

    async def test_turn_budget_reaches_existing_loop(self):
        provider = MockProvider([
            Message("assistant", "读取", [ToolCall("read_001", "read_file", {"path": "value.py"})]),
            Message("assistant", "不应请求"),
        ])
        harness = Harness(provider, self.tools, budget=RunBudget(max_model_turns=1))
        result = await harness.run("读取", self.store)
        self.assert_saved(result, self.store, "budget_exhausted")
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual([r.tool_call_id for r in result.messages if isinstance(r, ToolResult)], ["read_001"])

    async def test_time_budget_cancels_waiting_model_and_saves_timeout(self):
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
            result = await harness.run("等待", self.store)
        self.assert_saved(result, self.store, "timeout")
        self.assertTrue(cleaned.is_set())
        self.assertEqual(provider.generate.await_count, 1)
        self.assertFalse(harness.agent.is_running)

    async def test_busy_run_rejects_second_task_without_record_append(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def generate(history, tools):
            entered.set()
            await release.wait()
            return Message("assistant", "完成", stop_reason="stop")
        provider = Mock()
        provider.generate = AsyncMock(side_effect=generate)
        harness = Harness(provider, self.tools)
        pending = harness.run("A", self.store)
        second_store = SessionStore(self.root / "B.jsonl")
        try:
            async with asyncio.timeout(3):
                await entered.wait()
            before = self.store.path.read_bytes()
            with self.assertRaises(RuntimeError):
                harness.run("B", second_store)
            self.assertFalse(second_store.path.exists())
            self.assertEqual(self.store.path.read_bytes(), before)
            self.assertEqual(provider.generate.await_count, 1)
        finally:
            release.set()
            await pending

    async def test_new_stores_keep_new_run_ids_with_same_agent(self):
        provider = MockProvider([Message("assistant", "完成", stop_reason="stop") for _ in range(2)])
        harness = Harness(provider, self.tools)
        original_agent = harness.agent
        first = await harness.run("A", self.store)
        second_store = SessionStore(self.root / "B.jsonl")
        second = await harness.run("B", second_store)
        self.assert_saved(first, self.store, "finished")
        self.assert_saved(second, second_store, "finished")
        self.assertNotEqual(self.store.run_id, second_store.run_id)
        self.assertIs(harness.agent, original_agent)


if __name__ == "__main__":
    unittest.main()
