"""D16：真实本地记忆读取、读取副本缩短与发送门禁的联合验证。"""

import asyncio
from functools import partial
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock, patch

from mini_pi.bootstrap import build_tools
from mini_pi.context import FullHistoryContext, ReadOutputContext
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context_size import estimate_qwen_input
from mini_pi.harness import Harness, RunBudget
from mini_pi.memory.embedding import EmbeddingSpec
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.request_context import prepare_context
from mini_pi.memory.store import MemoryStore
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore


class FixedEmbedder:
    spec = EmbeddingSpec("offline-d16", "v1", 2)

    async def embed_query(self, text):
        return (1.0, 0.0)

    async def embed_documents(self, texts):
        return [(1.0, 0.0) for _ in texts]


class MemoryReadOutputIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="d16-memory-read-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.full_text = "def calculate():\n" + "原始文件正文\n" * 500
        (self.root / "sample.txt").write_text(self.full_text, encoding="utf-8")
        self.tools = build_tools(self.root, ["sample.txt"], [sys.executable, "-c", "pass"], self.root / "evidence")
        self.store = MemoryStore(self.root / "memory.sqlite3")
        self.scope = MemoryScope("d16-user", "d16-project")
        text = "讲解时使用Python示例。"
        source = MemorySource("d16-source", self.scope, "user", text, "2026-01-01T00:00:00+08:00")
        self.entry = self.store.remember(self.scope, source, MemoryDraft("language", 0, len(text), source.recorded_at))
        self.prepare = partial(prepare_context, self.store, self.scope, "讲解语言偏好", embedder=FixedEmbedder(),
                               at="2026-10-27T12:00:00+08:00", top_k=2, min_score=0.9, max_context_chars=50000)

    def session(self, resume):
        session = SessionStore(self.root / ("resume.jsonl" if resume else "new.jsonl"), "current")
        before = b""
        if resume:
            old = SessionStore(session.path, "old")
            old.append_entry("run_start", {"status": "running"})
            old.append_item(Message("user", "旧问题"))
            old.append_item(Message("assistant", "旧回答"))
            old.append_entry("run_end", {"status": "finished"})
            before = session.path.read_bytes()
        return session, before

    async def submit(self, harness, session, resume):
        if resume:
            outcome = await harness.resume("继续", session)
            self.assertEqual(outcome.plan.state, "ready")
            return outcome.run_result
        return await harness.run("读取sample.txt并说明", session)

    def harness(self, provider, **options):
        settings = dict(prepare_messages=self.prepare, context_builder=ReadOutputContext(120),
                        input_estimator=estimate_qwen_input, window_budget=ContextWindowBudget(20000, 1024, 128))
        settings.update(options)
        return Harness(provider, self.tools, **settings)

    def check_end(self, harness, session, result, status):
        self.assertEqual(result.status, status)
        self.assertIsNone(result.task_passed)
        self.assertFalse(harness.agent.is_running)
        loaded = session.load()
        self.assertEqual(loaded.history, result.messages)
        ends = [r for r in loaded.records if r["run_id"] == "current" and r["type"] == "run_end"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]["data"]["status"], status)

    async def test_both_entries_keep_memory_and_full_session_but_send_short_read(self):
        for resume in (False, True):
            with self.subTest(resume=resume):
                provider = MockProvider([
                    Message("assistant", "读取", [ToolCall("read", "read_file", {"path": "sample.txt"})]),
                    Message("assistant", "完成"),
                ])
                estimator = Mock(wraps=estimate_qwen_input)
                harness = self.harness(provider, input_estimator=estimator)
                session, before = self.session(resume)
                result = await self.submit(harness, session, resume)
                self.check_end(harness, session, result, "finished")
                self.assertEqual(len(provider.requests), 2)
                for index, request in enumerate(provider.requests):
                    material = [m for m in request if isinstance(m, Message) and m.content.startswith('{"purpose":')]
                    self.assertEqual(len(material), 1)
                    self.assertEqual(json.loads(material[0].content)["memories"][0]["memory_id"], self.entry.memory_id)
                    self.assertEqual(estimator.call_args_list[index].args[0], request)
                    self.assertEqual(estimator.call_args_list[index].args[1], provider.tool_requests[index])
                read = next(m for m in provider.requests[1] if isinstance(m, ToolResult))
                self.assertEqual(len(read.output), 120)
                self.assertIn("省略", read.output)
                raw_read = next(m for m in session.load().history if isinstance(m, ToolResult))
                self.assertEqual(raw_read.output, self.full_text)
                self.assertNotIn('"purpose"', session.path.read_text(encoding="utf-8"))
                self.assertTrue(session.path.read_bytes().startswith(before))

    async def test_final_budget_failure_keeps_prepared_material_out_of_session(self):
        for resume in (False, True):
            with self.subTest(resume=resume):
                provider = MockProvider([])
                estimator = Mock(wraps=estimate_qwen_input)
                harness = self.harness(provider, input_estimator=estimator,
                                       window_budget=ContextWindowBudget(100, 10))
                session, _ = self.session(resume)
                result = await self.submit(harness, session, resume)
                self.check_end(harness, session, result, "budget_exhausted")
                estimator.assert_called_once()
                self.assertTrue(any(isinstance(m, Message) and m.content.startswith('{"purpose":')
                                    for m in estimator.call_args.args[0]))
                self.assertEqual(provider.requests, [])
                self.assertNotIn('"purpose"', session.path.read_text(encoding="utf-8"))

    async def test_common_final_pairing_check_rejects_corrupted_builder_output(self):
        original_build = ReadOutputContext.build
        async def corrupt(builder, messages):
            result = await original_build(builder, messages)
            result.append(ToolResult("orphan", "read_file", "伪造的孤立结果"))
            return result
        provider = MockProvider([])
        estimator = Mock(wraps=estimate_qwen_input)
        harness = self.harness(provider, input_estimator=estimator)
        session, _ = self.session(False)
        with patch.object(ReadOutputContext, "build", new=corrupt):
            result = await self.submit(harness, session, False)
        self.check_end(harness, session, result, "error")
        self.assertIn("对应调用", result.error)
        estimator.assert_not_called()
        self.assertEqual(provider.requests, [])
        self.assertFalse(any(isinstance(m, ToolResult) for m in result.messages))

    async def test_joint_estimation_overrun_stops_before_send(self):
        def slow(messages, tools):
            time.sleep(0.06)
            return estimate_qwen_input(messages, tools)
        provider = MockProvider([Message("assistant", "不应发送")])
        harness = self.harness(provider, input_estimator=slow, budget=RunBudget(total_timeout_seconds=0.03))
        session, _ = self.session(False)
        result = await self.submit(harness, session, False)
        self.check_end(harness, session, result, "timeout")
        self.assertEqual(provider.requests, [])

    async def test_joint_cancellation_after_memory_stops_before_send(self):
        def cancelling(messages, tools):
            asyncio.current_task().cancel()
            return estimate_qwen_input(messages, tools)
        provider = MockProvider([])
        harness = self.harness(provider, input_estimator=cancelling)
        session, _ = self.session(False)
        result = await self.submit(harness, session, False)
        self.check_end(harness, session, result, "cancelled")
        self.assertEqual(provider.requests, [])

    async def test_truncated_unexecuted_calls_stay_paired_with_memory_and_reduction(self):
        raw_arguments = '{"path":"sample.txt","new_text":'
        provider = MockProvider([
            Message("assistant", "", [ToolCall("cut", "edit_file", None, raw_arguments)], stop_reason="length"),
            Message("assistant", "读取", [ToolCall("read", "read_file", {"path": "sample.txt"})]),
            Message("assistant", "完成"),
        ])
        harness = self.harness(provider)
        session, _ = self.session(False)
        result = await self.submit(harness, session, False)
        self.check_end(harness, session, result, "finished")
        cut_reply = next(m for m in provider.requests[1] if isinstance(m, Message) and m.tool_calls)
        self.assertIsNone(cut_reply.tool_calls[0].arguments)
        self.assertEqual(cut_reply.tool_calls[0].raw_arguments, raw_arguments)
        feedback = next(m for m in provider.requests[1] if isinstance(m, ToolResult))
        self.assertIn("未执行", feedback.error)
        self.assertEqual((self.root / "sample.txt").read_text(encoding="utf-8"), self.full_text)
        self.assertEqual(len(provider.requests), 3)

    def test_only_supported_builder_with_both_budget_options_can_combine(self):
        class OtherReadContext(ReadOutputContext):
            pass
        for builder, estimator, budget in (
            (FullHistoryContext(), estimate_qwen_input, ContextWindowBudget(20000, 1024)),
            (OtherReadContext(120), estimate_qwen_input, ContextWindowBudget(20000, 1024)),
            (ReadOutputContext(120), None, ContextWindowBudget(20000, 1024)),
            (ReadOutputContext(120), estimate_qwen_input, None),
        ):
            with self.subTest(builder=type(builder).__name__, estimator=estimator):
                provider = MockProvider([])
                with self.assertRaises(ValueError):
                    self.harness(provider, context_builder=builder, input_estimator=estimator, window_budget=budget)
                self.assertEqual(provider.requests, [])


if __name__ == "__main__":
    unittest.main()
