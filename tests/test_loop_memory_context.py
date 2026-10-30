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
from unittest.mock import AsyncMock, Mock

from mini_pi.context import ContextProvider, FullHistoryContext
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context_size import estimate_qwen_input
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

    async def test_invalid_separate_configuration_has_no_run_side_effects(self):
        references = AsyncMock(return_value=[])
        legacy = AsyncMock(return_value=[])
        wrapped = ContextProvider(self.provider, FullHistoryContext(),
                                  input_estimator=estimate_qwen_input,
                                  window_budget=ContextWindowBudget(1000, 100))
        no_budget = ContextProvider(self.provider, FullHistoryContext())
        cases = [
            (wrapped, {"prepare_references": references, "prepare_messages": legacy, "max_context_chars": 100}),
            (wrapped, {"prepare_references": "invalid", "max_context_chars": 100}),
            (no_budget, {"prepare_references": references, "max_context_chars": 100}),
            (self.provider, {"prepare_references": references, "max_context_chars": 100}),
            (wrapped, {"prepare_references": references, "max_context_chars": True}),
            (wrapped, {"prepare_references": references}),
            (wrapped, {"max_context_chars": 100}),
            (wrapped, {"prepare_model_history": "invalid", "max_context_chars": 100}),
            (wrapped, {"prepare_model_history": lambda history: history, "prepare_messages": legacy,
                       "max_context_chars": 100}),
            (no_budget, {"prepare_model_history": lambda history: history, "max_context_chars": 100}),
            (wrapped, {"prepare_model_history": lambda history: history, "max_context_chars": True}),
        ]
        for provider, options in cases:
            with self.subTest(options=options), self.assertRaises(ValueError):
                await run_loop(provider, self.executor, self.initial, [], session_store=self.session, **options)
            self.assertFalse(self.session.path.exists())
            self.assertEqual(self.provider.requests, [])
        references.assert_not_awaited()
        legacy.assert_not_awaited()
        self.executor.execute.assert_not_awaited()

    async def test_new_entries_can_be_configured_together(self):
        references = AsyncMock(return_value=[])
        prepare_history = Mock(side_effect=lambda history: history)
        provider = ContextProvider(self.provider, FullHistoryContext(), input_estimator=estimate_qwen_input,
                                   window_budget=ContextWindowBudget(10000, 100))
        result = await run_loop(provider, self.executor, self.initial, [], session_store=self.session,
                                prepare_references=references, prepare_model_history=prepare_history,
                                max_context_chars=10000)
        self.assertEqual(result.status, "finished")
        references.assert_awaited_once()
        prepare_history.assert_called_once()

    async def test_model_history_view_and_references_preserve_original_session(self):
        references = AsyncMock(return_value=[Message("user", "临时资料")])
        seen = []
        def prepare_history(history):
            seen.append(deepcopy(history))
            return [Message("system", "编程助手"), Message("user", "旧过程摘要"), *history[2:]]
        self.provider = MockProvider([
            Message("assistant", "运行测试", [ToolCall("t1", "run_tests", {})]),
            Message("assistant", "完成"),
        ])
        wrapped = ContextProvider(self.provider, FullHistoryContext(), input_estimator=estimate_qwen_input,
                                  window_budget=ContextWindowBudget(10000, 100))
        result = await run_loop(wrapped, self.executor, self.initial, [], session_store=self.session,
                                prepare_references=references, prepare_model_history=prepare_history,
                                max_context_chars=10000)
        self.assertEqual(result.status, "finished")
        self.assertEqual(references.await_count, 2)
        self.assertEqual(len(seen), 2)
        for raw in seen:
            self.assertEqual(raw[:2], self.initial)
            self.assertFalse(any(isinstance(item, Message) and item.content == "临时资料" for item in raw))
        for request in self.provider.requests:
            self.assertEqual([item.content for item in request[:3]], ["编程助手", "临时资料", "旧过程摘要"])
        self.assertIsInstance(self.provider.requests[1][-1], ToolResult)
        self.assertEqual(self.session.load().history, result.messages)
        self.assertEqual(result.messages[:2], self.initial)
        self.assertNotIn("旧过程摘要", self.session.path.read_text(encoding="utf-8"))
        self.assertNotIn("临时资料", self.session.path.read_text(encoding="utf-8"))

    async def test_history_view_alone_and_invalid_view(self):
        for invalid in (False, True):
            with self.subTest(invalid=invalid):
                provider = MockProvider([Message("assistant", "完成")])
                wrapped = ContextProvider(provider, FullHistoryContext(), input_estimator=estimate_qwen_input,
                                          window_budget=ContextWindowBudget(10000, 100))
                session = SessionStore(self.root / f"view-{invalid}.jsonl", run_id="view")
                prepare = lambda history: "not-a-list" if invalid else [Message("user", "摘要视图")]
                result = await run_loop(wrapped, self.executor, self.initial, [], session_store=session,
                                        prepare_model_history=prepare, max_context_chars=10000)
                self.assertEqual(result.status, "error" if invalid else "finished")
                self.assertEqual(len(provider.requests), 0 if invalid else 1)
                if not invalid:
                    self.assertEqual(provider.requests[0], [Message("user", "摘要视图")])
                self.assertEqual(session.load().history, result.messages)

    def separate_provider(self):
        return ContextProvider(self.provider, FullHistoryContext(),
                               input_estimator=estimate_qwen_input,
                               window_budget=ContextWindowBudget(10000, 100))

    async def test_separate_references_reach_model_but_not_session_history(self):
        original = deepcopy(self.initial)
        async def references(history):
            history[-1].content = "不应污染历史"
            return [Message("user", "临时参考资料")]
        result = await run_loop(self.separate_provider(), self.executor, self.initial, [],
                                session_store=self.session, prepare_references=references,
                                max_context_chars=10000)
        self.assertEqual(result.status, "finished")
        self.assertEqual(self.provider.requests[0], [original[0], Message("user", "临时参考资料"), original[1]])
        self.assertEqual(result.messages, self.session.load().history)
        self.assertEqual(result.messages[:2], original)
        self.assertNotIn("临时参考资料", self.session.path.read_text(encoding="utf-8"))

    async def test_separate_reference_preparation_failure_and_over_limit_stop_send(self):
        for name, references, limit, expected in [
            ("error", AsyncMock(side_effect=OSError("检索失败")), 10000, "error"),
            ("invalid", AsyncMock(return_value=[Message("system", "资料")]), 10000, "error"),
            ("limit", AsyncMock(return_value=[Message("user", "资料")]), 1, "error"),
        ]:
            with self.subTest(name=name):
                session = SessionStore(self.root / f"{name}.jsonl", run_id=name)
                result = await run_loop(self.separate_provider(), self.executor, self.initial, [],
                                        session_store=session, prepare_references=references,
                                        max_context_chars=limit)
                self.assertEqual(result.status, expected)
                self.assertEqual(session.load().history, self.initial)
                self.assertEqual(session.load().records[-1]["data"]["status"], expected)
                self.assertEqual(self.provider.requests, [])

    async def test_cancel_reference_preparation_waits_for_cleanup(self):
        started, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def references(history):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closing.set()
                await release.wait()
        task = asyncio.create_task(run_loop(self.separate_provider(), self.executor, self.initial, [],
                                            session_store=self.session, prepare_references=references,
                                            max_context_chars=10000))
        try:
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            await asyncio.wait_for(closing.wait(), 1)
            self.assertFalse(task.done())
            release.set()
            result = await asyncio.wait_for(task, 1)
            self.assertEqual(result.status, "cancelled")
            self.assertEqual(self.session.load().history, self.initial)
            self.assertEqual(self.end_record()["status"], "cancelled")
            self.assertEqual(self.provider.requests, [])
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

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
