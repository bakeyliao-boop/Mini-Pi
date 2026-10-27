"""助手准备：请求准备的离线反例；固定embedding及真实临时SQLite。"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.memory.embedding import EmbeddingSpec
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.request_context import prepare_context
from mini_pi.memory.store import MemoryStore
from mini_pi.models import Message


class FixedEmbedder:
    spec = EmbeddingSpec("offline-fixed", "test-v1", 2)

    async def embed_query(self, text):
        return (1.0, 0.0)

    async def embed_documents(self, texts):
        return [(1.0, 0.0) for _ in texts]


class RequestContextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = MemoryStore(Path(temporary.name) / "memory.sqlite3")
        self.scope = MemoryScope("test-user", "test-project")
        self.history = [Message("system", "编程助手"), Message("user", "如何解释折扣修复？")]
        self.options = dict(embedder=FixedEmbedder(), at="2026-10-26T10:00:00+08:00",
                            top_k=2, min_score=0.9, max_context_chars=10000)

    def remember(self):
        text = "后续请尽量使用Python示例。"
        source = MemorySource("preference", self.scope, "user", text, "2026-01-01T00:00:00+08:00")
        return self.store.remember(self.scope, source, MemoryDraft("language", 0, len(text), source.recorded_at))

    async def prepare(self):
        return await prepare_context(self.store, self.scope, "解释修复时的语言偏好", self.history, **self.options)

    async def test_actual_search_and_builder_preserve_history_and_source(self):
        entry = self.remember()
        before = deepcopy(self.history)
        messages = await self.prepare()
        payload = json.loads(messages[1].content)
        self.assertEqual(payload["memories"][0]["memory_id"], entry.memory_id)
        self.assertEqual(payload["memories"][0]["content"], entry.text)
        self.assertEqual(messages[0], before[0])
        self.assertEqual(messages[2:], before[1:])
        self.assertEqual(self.history, before)

    async def test_empty_store_keeps_messages_without_embedding_or_database_creation(self):
        embedder = self.options["embedder"]
        with patch.object(embedder, "embed_query", new_callable=AsyncMock) as send:
            self.assertEqual(await self.prepare(), self.history)
            send.assert_not_awaited()
        self.assertIsNone(self.store.latest(self.scope, "language"))
        self.assertFalse(self.store._backend.path.exists())

    async def test_search_failure_is_propagated_without_building_empty_context(self):
        failure = OSError("synthetic search failure")
        with patch.object(self.store, "search", new=AsyncMock(side_effect=failure)):
            with patch("mini_pi.memory.request_context.build_context") as build:
                with self.assertRaises(OSError) as caught:
                    await self.prepare()
                self.assertIs(caught.exception, failure)
                build.assert_not_called()

    async def test_cancel_during_embedding_waits_for_cleanup_before_returning(self):
        self.remember()
        started, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def waiting_query(text):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closing.set()
                await release.wait()

        with patch.object(self.options["embedder"], "embed_query", side_effect=waiting_query):
            task = asyncio.create_task(self.prepare())
            try:
                await asyncio.wait_for(started.wait(), 1)
                task.cancel()
                await asyncio.wait_for(closing.wait(), 1)
                self.assertFalse(task.done())
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_cancellation_requested_when_search_returns_prevents_build(self):
        async def search_then_cancel(*args, **kwargs):
            asyncio.current_task().cancel()
            return []

        with patch.object(self.store, "search", side_effect=search_then_cancel):
            with patch("mini_pi.memory.request_context.build_context") as build:
                task = asyncio.create_task(self.prepare())
                with self.assertRaises(asyncio.CancelledError):
                    await task
                build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
