"""两入口共用请求上下文，原始JSONL不受组装影响，组装等待受生命周期管理。"""

import asyncio
from copy import deepcopy
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock

from mini_pi.bootstrap import build_tools
from mini_pi.harness import Harness, RunBudget
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore


class HarnessContextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="_context_", dir=Path(__file__).parent)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "sample.txt").write_text("complete file content", encoding="utf-8")
        self.tools = build_tools(self.root, ["sample.txt"],
            (sys.executable, "-c", "raise SystemExit(0)"), self.root / "evidence")

    def store(self, resume):
        path = self.root / ("resume.jsonl" if resume else "new.jsonl")
        if resume:
            old = SessionStore(path, "old")
            old.append_entry("run_start", {"status": "running"})
            old.append_item(Message("user", "旧问题"))
            old.append_item(Message("assistant", "旧回答"))
            old.append_entry("run_end", {"status": "finished"})
        return SessionStore(path, "current")

    async def submit(self, harness, store, resume):
        if resume:
            outcome = await harness.resume("本次问题", store)
            self.assertEqual(outcome.plan.state, "ready")
            return outcome.run_result
        return await harness.run("本次问题", store)

    async def test_both_entries_transform_each_request_but_keep_raw_jsonl(self):
        for resume in (False, True):
            with self.subTest(resume=resume):
                store = self.store(resume)
                before = store.path.read_bytes() if resume else b""
                snapshots = []
                class Builder:
                    def __bool__(self):
                        return False
                    async def build(self, items):
                        snapshots.append(deepcopy(items))
                        items[0].content = "仅模型请求可见"
                        for item in items:
                            if isinstance(item, ToolResult):
                                item.output = "请求摘要"
                        return list(items)
                provider = MockProvider([
                    Message("assistant", "读取", [ToolCall("r1", "read_file", {"path": "sample.txt"})]),
                    Message("assistant", "完成", stop_reason="stop")])
                harness = Harness(provider, self.tools, context_builder=Builder())
                agent = harness.agent
                result = await self.submit(harness, store, resume)
                self.assertIs(harness.agent, agent)
                self.assertEqual(result.status, "finished")
                self.assertEqual(len(snapshots), 2)
                self.assertEqual(provider.requests[0][0].content, "仅模型请求可见")
                self.assertEqual(provider.requests[1][-1].output, "请求摘要")
                self.assertEqual(snapshots[1][-1].output, "complete file content")
                self.assertEqual(store.load().history, result.messages)
                self.assertNotIn("仅模型请求可见", store.path.read_text(encoding="utf-8"))
                self.assertNotIn("请求摘要", store.path.read_text(encoding="utf-8"))
                self.assertTrue(store.path.read_bytes().startswith(before))
                self.assertEqual([t.name for t in provider.tool_requests[0]],
                    ["list_files", "read_file", "edit_file", "run_tests"])

    async def test_constructing_with_builder_does_not_start_work(self):
        builder = AsyncMock()
        provider = MockProvider([])
        harness = Harness(provider, self.tools, context_builder=builder)
        builder.build.assert_not_called()
        self.assertEqual(provider.requests, [])
        self.assertFalse(harness.agent.is_running)

    async def test_non_ready_does_not_build_or_append(self):
        store = self.store(True)
        SessionStore(store.path, "old").append_item(
            Message("assistant", "待编辑", [ToolCall("pending", "edit_file", {})]))
        before = store.path.read_bytes()
        builder = AsyncMock()
        provider = MockProvider([])
        harness = Harness(provider, self.tools, context_builder=builder)
        outcome = await harness.resume("继续", store)
        self.assertEqual(outcome.plan.state, "needs_review")
        builder.build.assert_not_called()
        self.assertEqual(provider.requests, [])
        self.assertEqual(store.path.read_bytes(), before)

    async def test_abort_during_build_for_both_entries_waits_for_cleanup(self):
        for resume in (False, True):
            with self.subTest(resume=resume):
                entered, cleaned = asyncio.Event(), asyncio.Event()
                class Builder:
                    async def build(self, items):
                        entered.set()
                        try:
                            await asyncio.Event().wait()
                        finally:
                            cleaned.set()
                store = self.store(resume)
                provider = MockProvider([])
                harness = Harness(provider, self.tools, context_builder=Builder())
                task = asyncio.create_task(self.submit(harness, store, resume))
                try:
                    await asyncio.wait_for(entered.wait(), 1)
                    harness.agent.abort()
                    await harness.agent.wait_for_idle()
                    result = await task
                    self.assertEqual(result.status, "cancelled")
                    self.assertTrue(cleaned.is_set())
                    self.assertFalse(harness.agent.is_running)
                    self.assertEqual(provider.requests, [])
                    self.assertEqual(store.load().records[-1]["data"]["status"], "cancelled")
                finally:
                    if not task.done():
                        harness.agent.abort()
                        await asyncio.gather(task, return_exceptions=True)

    async def test_timeout_includes_async_build_wait_for_both_entries(self):
        for resume in (False, True):
            with self.subTest(resume=resume):
                cleaned = asyncio.Event()
                class Builder:
                    async def build(self, items):
                        try:
                            await asyncio.Event().wait()
                        finally:
                            cleaned.set()
                provider = MockProvider([])
                store = self.store(resume)
                harness = Harness(provider, self.tools, context_builder=Builder(),
                    budget=RunBudget(total_timeout_seconds=0.05))
                result = await self.submit(harness, store, resume)
                self.assertEqual(result.status, "timeout")
                self.assertTrue(cleaned.is_set())
                self.assertFalse(harness.agent.is_running)
                self.assertEqual(provider.requests, [])
                self.assertEqual(store.load().records[-1]["data"]["status"], "timeout")

    async def test_build_error_propagates_and_releases_agent(self):
        builder = AsyncMock()
        builder.build.side_effect = RuntimeError("context bug")
        provider = MockProvider([])
        hook = AsyncMock()
        harness = Harness(provider, self.tools, context_builder=builder, on_run_end=hook)
        with self.assertRaisesRegex(RuntimeError, "context bug"):
            await harness.run("继续", self.store(False))
        self.assertFalse(harness.agent.is_running)
        self.assertEqual(provider.requests, [])
        hook.assert_awaited_once()
        self.assertIsInstance(hook.await_args.args[1], RuntimeError)
