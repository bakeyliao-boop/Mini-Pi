"""整合候选跨层反例：主线Agent/Harness/队列/截断与MEM-04同时工作。"""

import asyncio
from copy import deepcopy
from functools import partial
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.agent import Agent
from mini_pi.bootstrap import build_tools
from mini_pi.context import FullHistoryContext
from mini_pi.harness import Harness, RunBudget
from mini_pi.memory.context_helpers import messages_char_count
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.embedding import EmbeddingSpec
from mini_pi.memory.request_context import prepare_context
from mini_pi.memory.store import MemoryStore
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore
import tests.test_memory_context_transport as transport_tests


class FixedEmbedder:
    spec = EmbeddingSpec("offline-integration", "v1", 2)
    async def embed_query(self, text):
        return (1.0, 0.0)
    async def embed_documents(self, texts):
        return [(1.0, 0.0) for _ in texts]


class MemoryMainlineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="integration-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "sample.txt").write_text("actual-file", encoding="utf-8")
        self.tools = build_tools(self.root, ["sample.txt"],
            [sys.executable, "-c", "pass"], self.root / "tool-evidence")
        self.store = MemoryStore(self.root / "memory.sqlite3")
        self.scope = MemoryScope("integration-user", "integration-project")
        text = "讲解时使用Python示例。"
        source = MemorySource("integration-source", self.scope, "user", text, "2026-01-01T00:00:00+08:00")
        self.entry = self.store.remember(self.scope, source,
            MemoryDraft("language", 0, len(text), source.recorded_at))
        self.options = dict(embedder=FixedEmbedder(), at="2026-10-27T12:00:00+08:00",
                            top_k=2, min_score=0.9, max_context_chars=20000)
        self.prepare = partial(prepare_context, self.store, self.scope, "讲解语言偏好", **self.options)

    def session(self, label="new", resume=False):
        path = self.root / (label + ".jsonl")
        if resume:
            old = SessionStore(path, "old")
            old.append_entry("run_start", {"status": "running"})
            old.append_item(Message("user", "旧问题"))
            old.append_item(Message("assistant", "旧回答"))
            old.append_entry("run_end", {"status": "finished"})
        return SessionStore(path)

    async def test_both_harness_entries_memory_steering_followup_and_clean_session(self):
        for resume in (False, True):
            with self.subTest(resume=resume):
                provider = MockProvider([
                    Message("assistant", "读", [ToolCall("read", "read_file", {"path": "sample.txt"})]),
                    Message("assistant", "准备停止"), Message("assistant", "处理追加输入")])
                inputs = []
                async def preparing(items):
                    inputs.append(deepcopy(items))
                    return await self.prepare(items)
                recorded = AsyncMock(side_effect=preparing)
                harness = Harness(provider, self.tools, prepare_messages=recorded)
                identity = harness.agent
                harness.agent.steer("方向调整")
                harness.agent.follow_up("后续问题")
                session = self.session(str(resume), resume)
                before = session.path.read_bytes() if resume else b""
                outcome = await harness.resume("继续", session) if resume else await harness.run("继续", session)
                result = outcome.run_result if resume else outcome
                self.assertIs(harness.agent, identity)
                self.assertEqual(result.status, "finished")
                self.assertEqual(recorded.await_count, 3)
                for request in provider.requests:
                    materials = [m for m in request if isinstance(m, Message) and m.content.startswith('{"')]
                    self.assertEqual(len(materials), 1)
                    self.assertEqual(json.loads(materials[0].content)["memories"][0]["memory_id"], self.entry.memory_id)
                    self.assertLessEqual(messages_char_count(request), 20000)
                self.assertEqual(inputs[0][-1].content, "方向调整")
                self.assertIsInstance(inputs[1][-1], ToolResult)
                self.assertEqual(inputs[1][-1].output, "actual-file")
                self.assertEqual(inputs[2][-1].content, "后续问题")
                self.assertNotIn('"memories"', session.path.read_text(encoding="utf-8"))
                self.assertEqual(session.load().history, result.messages)
                self.assertTrue(session.path.read_bytes().startswith(before))
                self.assertFalse(harness.agent.is_running)

    async def test_preparation_failure_uses_error_result_hook_and_unchanged_raw_history(self):
        async def broken(items):
            items[0].content = "只能修改副本"
            raise OSError("synthetic preparation error")
        hook = AsyncMock()
        provider = MockProvider([])
        harness = Harness(provider, self.tools, prepare_messages=broken, on_run_end=hook)
        session = self.session()
        result = await harness.run("原始问题", session)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.messages, [Message("user", "原始问题")])
        self.assertEqual(session.load().records[-1]["data"]["status"], "error")
        hook.assert_awaited_once_with(result, None)
        self.assertEqual(provider.requests, [])
        self.assertFalse(harness.agent.is_running)

    async def test_preparation_cancellation_keeps_busy_until_cleanup(self):
        entered, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def preparing(items):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                closing.set()
                await release.wait()
        provider = MockProvider([])
        harness = Harness(provider, self.tools, prepare_messages=preparing)
        session = self.session()
        pending = harness.run("A", session)
        try:
            await asyncio.wait_for(entered.wait(), 1)
            harness.agent.abort()
            await asyncio.wait_for(closing.wait(), 1)
            self.assertTrue(harness.agent.is_running)
            with self.assertRaisesRegex(RuntimeError, "活动运行"):
                harness.run("B", self.session("other"))
            self.assertNotEqual(session.load().records[-1]["type"], "run_end")
            release.set()
            result = await pending
            self.assertEqual(result.status, "cancelled")
            self.assertFalse(harness.agent.is_running)
            self.assertEqual(provider.requests, [])
        finally:
            release.set()
            harness.agent.abort()
            await asyncio.gather(pending, return_exceptions=True)
            await harness.agent.wait_for_idle()

    async def test_sync_preparation_overrun_does_not_send_after_deadline(self):
        async def slow(items):
            time.sleep(0.04)
            return items
        provider = MockProvider([])
        harness = Harness(provider, self.tools, prepare_messages=slow,
                          budget=RunBudget(total_timeout_seconds=0.01))
        result = await harness.run("任务", self.session())
        self.assertEqual(result.status, "timeout")
        self.assertEqual(provider.requests, [])
        self.assertFalse(harness.agent.is_running)

    async def test_truncated_arguments_are_preserved_and_never_executed_with_memory(self):
        provider = MockProvider([
            Message("assistant", "截断", [ToolCall("trunc", "edit_file", None, raw_arguments='{"path":')], stop_reason="length"),
            Message("assistant", "收到未执行反馈")])
        harness = Harness(provider, self.tools, prepare_messages=self.prepare)
        with patch.object(self.tools.executor, "execute", wraps=self.tools.executor.execute) as execute:
            result = await harness.run("任务", self.session())
        self.assertEqual(result.status, "finished")
        execute.assert_not_called()
        second = provider.requests[1]
        truncated = [m for m in second if isinstance(m, Message) and m.stop_reason == "length"][0]
        self.assertEqual(truncated.tool_calls[0].raw_arguments, '{"path":')
        self.assertIsNone(truncated.tool_calls[0].arguments)
        self.assertEqual(second[-1].tool_call_id, "trunc")
        self.assertIsNotNone(second[-1].error)
        self.assertEqual((self.root / "sample.txt").read_text(), "actual-file")

    async def test_normal_model_error_still_ends_without_executing_calls(self):
        provider = MockProvider([Message("assistant", "", [ToolCall("never", "read_file", {"path": "sample.txt"})], stop_reason="error", error_message="service error")])
        harness = Harness(provider, self.tools, prepare_messages=self.prepare)
        with patch.object(self.tools.executor, "execute", wraps=self.tools.executor.execute) as execute:
            result = await harness.run("任务", self.session())
        self.assertEqual(result.status, "error")
        execute.assert_not_called()

    async def test_provider_internal_error_is_not_misclassified_as_preparation_failure(self):
        provider = MockProvider([])
        provider.generate = AsyncMock(side_effect=AssertionError("provider bug"))
        hook = AsyncMock()
        harness = Harness(provider, self.tools, prepare_messages=self.prepare, on_run_end=hook)
        session = self.session()
        with self.assertRaisesRegex(AssertionError, "provider bug"):
            await harness.run("任务", session)
        self.assertFalse(harness.agent.is_running)
        self.assertNotEqual(session.load().records[-1]["type"], "run_end")
        self.assertIsInstance(hook.await_args.args[1], AssertionError)

    async def test_budget_gate_precedes_next_preparation(self):
        provider = MockProvider([Message("assistant", "读", [ToolCall("read", "read_file", {"path": "sample.txt"})])])
        prepare = AsyncMock(side_effect=self.prepare)
        harness = Harness(provider, self.tools, prepare_messages=prepare, budget=RunBudget(max_model_turns=1))
        result = await harness.run("任务", self.session())
        self.assertEqual(result.status, "budget_exhausted")
        self.assertEqual(prepare.await_count, 1)
        self.assertEqual(len(provider.requests), 1)

    async def test_opaque_two_stage_transform_is_rejected_instead_of_bypassing_final_budget(self):
        provider = MockProvider([])
        with self.assertRaisesRegex(ValueError, "不能同时配置"):
            Harness(provider, self.tools, prepare_messages=self.prepare, context_builder=FullHistoryContext())
        self.assertEqual(provider.requests, [])

    async def test_memory_character_budget_failure_has_zero_model_calls(self):
        prepare = partial(prepare_context, self.store, self.scope, "偏好",
                          **{**self.options, "max_context_chars": 1})
        provider = MockProvider([])
        harness = Harness(provider, self.tools, prepare_messages=prepare)
        result = await harness.run("任务", self.session())
        self.assertEqual(result.status, "error")
        self.assertIn("字符预算", result.error)
        self.assertEqual(provider.requests, [])


class MainlineMemoryTransportTests(transport_tests.MemoryContextTransportTests):
    """复用实际本地HTTPS，但改经主线Agent生命周期与ContextProvider。"""
    async def run_case(self, embedder):
        prepare = partial(prepare_context, self.store, self.scope, transport_tests.QUERY,
                          embedder=embedder, at="2026-10-27T10:00:00+08:00", top_k=1,
                          min_score=0.9, max_context_chars=10000)
        from mini_pi.context import ContextProvider
        agent = Agent(ContextProvider(self.provider, FullHistoryContext()), self.executor, [])
        waiting = agent.prompt(self.initial, session_store=self.session, prepare_messages=prepare)
        actual_task = agent._active_run.task
        try:
            return await waiting
        except asyncio.CancelledError:
            agent.abort()
            return await asyncio.shield(actual_task)
        finally:
            await agent.wait_for_idle()
            self.assertFalse(agent.is_running)
