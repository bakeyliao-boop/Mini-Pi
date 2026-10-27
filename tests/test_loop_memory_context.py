"""助手准备：每轮Context准备、provider输入及结束边界的离线验收。"""

import asyncio
from copy import deepcopy
from functools import partial
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from mini_pi.loop import run_loop
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.request_context import prepare_context
from mini_pi.memory.store import MemoryStore
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore
from tests.test_memory_request_context import FixedEmbedder


class LoopMemoryContextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.session = SessionStore(self.root / "session.jsonl", run_id="context-loop")
        self.initial = [Message("system", "编程助手"), Message("user", "解释折扣修复。")]
        self.provider = MockProvider([Message("assistant", "说明完成。")])
        self.executor = SimpleNamespace(execute=AsyncMock(return_value=ToolResult("t1", "run_tests", "FAILED")))

    async def run_case(self, prepare, **kwargs):
        return await run_loop(self.provider, self.executor, self.initial, [],
                              session_store=self.session, prepare_messages=prepare, **kwargs)

    def end_record(self):
        return self.session.load().records[-1]["data"]

    async def test_each_turn_retrieves_and_provider_receives_context_without_session_pollution(self):
        scope = MemoryScope("user", "project")
        store = MemoryStore(self.root / "memory.sqlite3")
        text = "后续尽量使用Python解释。"
        source = MemorySource("p1", scope, "user", text, "2026-01-01T00:00:00+08:00")
        entry = store.remember(scope, source, MemoryDraft("language", 0, len(text), source.recorded_at))
        prepare = partial(prepare_context, store, scope, "讲解语言偏好", embedder=FixedEmbedder(),
                          at="2026-10-26T10:00:00+08:00", top_k=2, min_score=0.9, max_context_chars=10000)
        recorded = AsyncMock(side_effect=prepare)
        self.provider = MockProvider([
            Message("assistant", "运行测试。", [ToolCall("t1", "run_tests", {})]),
            Message("assistant", "测试失败，继续定位。"),
        ])
        result = await self.run_case(recorded)
        self.assertEqual(result.status, "finished")
        self.assertEqual(recorded.await_count, 2)
        self.assertEqual(len(self.provider.requests), 2)
        for request in self.provider.requests:
            payload = json.loads(request[1].content)
            self.assertEqual(payload["memories"][0]["memory_id"], entry.memory_id)
        self.assertIsInstance(self.provider.requests[1][-1], ToolResult)
        self.assertEqual(self.provider.requests[1][-1].output, "FAILED")
        self.assertEqual(result.messages, self.session.load().history)
        self.assertEqual(len(result.messages), 5)
        self.assertNotIn('"memories"', self.session.path.read_text(encoding="utf-8"))

    async def test_preparation_error_records_error_without_provider_or_tool_or_history_mutation(self):
        snapshot = deepcopy(self.initial)
        async def broken(history):
            history[0].content = "修改副本"
            raise OSError("synthetic preparation failure")
        result = await self.run_case(broken)
        self.assertEqual(result.status, "error")
        self.assertIn("synthetic preparation failure", result.error)
        self.assertEqual(self.initial, snapshot)
        self.assertEqual(result.messages, snapshot)
        self.assertEqual(self.end_record()["status"], "error")
        self.assertEqual(self.provider.requests, [])
        self.executor.execute.assert_not_awaited()

    async def test_cancel_preparation_waits_for_cleanup_then_records_cancelled(self):
        started, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def waiting(history):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closing.set()
                await release.wait()
        task = asyncio.create_task(self.run_case(waiting))
        try:
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            await asyncio.wait_for(closing.wait(), 1)
            self.assertFalse(task.done())
            self.assertNotEqual(self.session.load().records[-1]["type"], "run_end")
            release.set()
            result = await asyncio.wait_for(task, 1)
            self.assertEqual(result.status, "cancelled")
            self.assertEqual(self.end_record()["status"], "cancelled")
            self.assertEqual(self.provider.requests, [])
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_preparation_timeout_finishes_cleanup_before_run_end(self):
        cleaned = asyncio.Event()
        async def waiting(history):
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
        result = await self.run_case(waiting, total_timeout_seconds=0.03)
        self.assertTrue(cleaned.is_set())
        self.assertEqual(result.status, "timeout")
        self.assertEqual(self.end_record()["status"], "timeout")
        self.assertEqual(self.provider.requests, [])

    async def test_cancel_on_preparation_return_does_not_start_provider(self):
        async def prepare(history):
            asyncio.current_task().cancel()
            return history
        result = await self.run_case(prepare)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(self.provider.requests, [])
        self.assertEqual(self.end_record()["status"], "cancelled")

    async def test_sync_preparation_overruns_deadline_and_provider_is_not_started(self):
        async def slow(history):
            time.sleep(0.03)  # 合成同步阻塞：不承诺可抢占，但发送前必须再核对截止时间。
            return history
        result = await self.run_case(slow, total_timeout_seconds=0.001)
        self.assertEqual(result.status, "timeout")
        self.assertEqual(self.provider.requests, [])

    async def test_invalid_callback_rejected_before_session_append_or_provider(self):
        with self.assertRaises(ValueError):
            await self.run_case("invalid")
        self.assertFalse(self.session.path.exists())
        self.assertEqual(self.provider.requests, [])

    async def test_provider_error_is_not_reclassified_as_preparation_failure(self):
        async def prepare(history):
            return history
        for callback in (None, prepare):
            with self.subTest(callback=callback):
                failure = OSError("synthetic provider failure")
                self.provider = SimpleNamespace(generate=AsyncMock(side_effect=failure))
                with self.assertRaises(OSError) as caught:
                    await self.run_case(callback)
                self.assertIs(caught.exception, failure)


if __name__ == "__main__":
    unittest.main()
