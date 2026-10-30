"""已有摘要的会话恢复：原始记录、模型视图与可选本地记忆。"""

from functools import partial
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from mini_pi.bootstrap import build_tools
from mini_pi.compaction_pipeline import prepare_compaction_candidate
from mini_pi.compaction_restore import build_live_restored_history
from mini_pi.compaction_save import save_compaction_candidate
from mini_pi.context import ContextProvider, FullHistoryContext, ReadOutputContext
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context_size import estimate_qwen_input
from mini_pi.harness import Harness
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.request_context import prepare_context
from mini_pi.memory.store import MemoryStore
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore
from mini_pi.summary_call_budget import SummaryCallBudget
from tests.test_memory_request_context import FixedEmbedder


class HarnessCompactionResumeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = TemporaryDirectory(prefix="resume-compaction-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.full_text = "配置正文\n" * 200
        (self.root / "sample.txt").write_text(self.full_text, encoding="utf-8")
        self.tools = build_tools(self.root, ["sample.txt"], [sys.executable, "-c", "pass"], self.root / "evidence")
        self.path = self.root / "session.jsonl"
        self.old = SessionStore(self.path, "old")
        self.old.append_entry("run_start", {"status": "running"})
        self.old.append_item(Message("user", "旧任务修复登录"))
        self.old.append_item(Message("assistant", "读取旧文件", [ToolCall("old-read", "read_file", {"path": "sample.txt"})]))
        self.old.append_item(ToolResult("old-read", "read_file", "旧结果：测试失败"))
        self.old.append_item(Message("user", "继续排查"))
        self.old.append_entry("run_end", {"status": "finished"})
        session_id = self.old.ensure_session_id()
        self.window = ContextWindowBudget(20000, 1024, 128)
        summary_provider = MockProvider([Message("assistant", "修复登录：测试失败，待排查", stop_reason="stop")])
        summary_provider.max_completion_tokens = 1024
        answer_context = ContextProvider(SimpleNamespace(max_completion_tokens=1024), FullHistoryContext(),
                                         input_estimator=estimate_qwen_input, window_budget=self.window)
        candidate = await prepare_compaction_candidate(
            self.old.load().history, [], self.tools.definitions, summary_provider, lambda item: 1,
            estimate_qwen_input, self.window, self.window, SummaryCallBudget(1), 1, 50000,
            session_id=session_id,
            answer_context=answer_context,
        )
        await save_compaction_candidate(self.old, candidate, [], self.tools.definitions,
                                        answer_context, self.window, 50000)

    def provider(self):
        return MockProvider([
            Message("assistant", "读取配置", [ToolCall("new-read", "read_file", {"path": "sample.txt"})]),
            Message("assistant", "已检查配置"),
        ])

    async def check_resume(self, harness, provider, reference_expected):
        before = self.path.read_bytes()
        old_history = self.old.load().history
        outcome = await harness.resume("新问题：检查配置", SessionStore(self.path, "new"))
        self.assertEqual(outcome.plan.state, "ready")
        self.assertEqual(outcome.run_result.status, "finished")
        self.assertEqual(len(provider.requests), 2)
        for request in provider.requests:
            texts = [item.content for item in request if isinstance(item, Message)]
            self.assertTrue(any("测试失败，待排查" in text for text in texts))
            self.assertIn("继续排查", texts)
            self.assertIn("新问题：检查配置", texts)
            self.assertNotIn("旧任务修复登录", texts)
            self.assertEqual(any("讲解时使用Python示例" in text for text in texts), reference_expected)
        read = next(item for item in provider.requests[1] if isinstance(item, ToolResult))
        self.assertEqual(len(read.output), 120)
        loaded = SessionStore(self.path, "new").load()
        self.assertEqual(loaded.history, outcome.run_result.messages)
        self.assertEqual(loaded.history[:len(old_history)], old_history)
        self.assertEqual(next(item for item in loaded.history if isinstance(item, ToolResult) and item.tool_call_id == "new-read").output,
                         self.full_text)
        self.assertTrue(self.path.read_bytes().startswith(before))
        self.assertNotIn("讲解时使用Python示例", self.path.read_text(encoding="utf-8"))

    async def test_resume_without_memory_uses_summary_and_window_budget(self):
        provider = self.provider()
        harness = Harness(provider, self.tools, context_builder=ReadOutputContext(120),
                          input_estimator=estimate_qwen_input, window_budget=self.window)
        await self.check_resume(harness, provider, False)

    async def test_resume_with_local_memory_counts_reference_and_preserves_session(self):
        memory = MemoryStore(self.root / "memory.sqlite3")
        scope = MemoryScope("user", "project")
        text = "讲解时使用Python示例"
        source = MemorySource("preference", scope, "user", text, "2026-01-01T00:00:00+08:00")
        memory.remember(scope, source, MemoryDraft("language", 0, len(text), source.recorded_at))
        prepare = partial(prepare_context, memory, scope, "讲解语言偏好", embedder=FixedEmbedder(),
                          at="2026-10-29T12:00:00+08:00", top_k=2, min_score=0.9,
                          max_context_chars=50000, reference_only=True)
        provider = self.provider()
        harness = Harness(provider, self.tools, context_builder=ReadOutputContext(120),
                          prepare_references=prepare, max_context_chars=50000,
                          input_estimator=estimate_qwen_input, window_budget=self.window)
        await self.check_resume(harness, provider, True)

    async def test_missing_budget_and_changed_history_stop_before_writing(self):
        provider = self.provider()
        harness = Harness(provider, self.tools)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "窗口预算"):
            await harness.resume("继续", SessionStore(self.path, "new"))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(provider.requests, [])
        contents = self.path.read_text(encoding="utf-8")
        self.path.write_text(contents.replace("旧结果：测试失败", "旧结果：测试通过", 1), encoding="utf-8")
        changed = self.path.read_bytes()
        harness = Harness(provider, self.tools, input_estimator=estimate_qwen_input, window_budget=self.window)
        with self.assertRaisesRegex(ValueError, "历史已变化"):
            await harness.resume("继续", SessionStore(self.path, "new"))
        self.assertEqual(self.path.read_bytes(), changed)
        self.assertEqual(provider.requests, [])

    async def test_reference_is_included_in_final_window_budget(self):
        loaded = self.old.load()
        view = build_live_restored_history(loaded, loaded.history + [Message("user", "继续")])
        baseline = estimate_qwen_input(view, self.tools.definitions)
        window = ContextWindowBudget(baseline.estimated_input_tokens + 100, 100)
        prepare = AsyncMock(return_value=[Message("user", "参考资料" * 3000)])
        provider = MockProvider([])
        harness = Harness(provider, self.tools, prepare_references=prepare, max_context_chars=100000,
                          input_estimator=estimate_qwen_input, window_budget=window)
        outcome = await harness.resume("继续", SessionStore(self.path, "new"))
        self.assertEqual(outcome.run_result.status, "budget_exhausted")
        self.assertEqual(provider.requests, [])
        prepare.assert_awaited_once()
        self.assertNotIn("参考资料", self.path.read_text(encoding="utf-8"))

    async def test_pending_tool_and_legacy_preparation_stop_before_writing(self):
        provider = self.provider()
        legacy = AsyncMock(return_value=[])
        harness = Harness(provider, self.tools, prepare_messages=legacy,
                          input_estimator=estimate_qwen_input, window_budget=self.window)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "旧的消息准备入口"):
            await harness.resume("继续", SessionStore(self.path, "new"))
        self.assertEqual(self.path.read_bytes(), before)
        legacy.assert_not_awaited()

        interrupted = SessionStore(self.path, "interrupted")
        interrupted.append_item(Message("assistant", "读取", [ToolCall("pending", "read_file", {"path": "sample.txt"})]))
        before = self.path.read_bytes()
        harness = Harness(provider, self.tools, input_estimator=estimate_qwen_input, window_budget=self.window)
        outcome = await harness.resume("继续", SessionStore(self.path, "new"))
        self.assertNotEqual(outcome.plan.state, "ready")
        self.assertIsNone(outcome.run_result)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(provider.requests, [])


if __name__ == "__main__":
    unittest.main()
