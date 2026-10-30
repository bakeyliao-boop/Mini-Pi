"""摘要保存入口：真实临时文件与模拟模型。"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mini_pi.compaction_pipeline import prepare_compaction_candidate
from mini_pi.compaction_restore import build_live_restored_history, build_restored_history, read_saved_compaction
from mini_pi.compaction_save import save_compaction_candidate
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context import ContextProvider, FullHistoryContext, ReadOutputContext
from mini_pi.context_size import estimate_qwen_input
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.memory.errors import MemoryContextError
from mini_pi.run_deadline import RunDeadlineExceeded
from mini_pi.session_store import SessionStore
from mini_pi.summary_call_budget import SummaryCallBudget


class CompactionSaveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "session.jsonl"
        self.store = SessionStore(self.path, "run-a")
        self.store.append_item(Message("user", "修复登录"))
        self.store.append_item(Message("assistant", "测试", [ToolCall("t", "test", {})]))
        self.store.append_item(ToolResult("t", "test", "测试失败"))
        self.store.append_item(Message("user", "继续"))
        self.session_id = self.store.ensure_session_id()
        self.references = [Message("user", "本轮参考资料")]
        self.tools = []
        self.window = ContextWindowBudget(10000, 100)
        self.answer_provider = SimpleNamespace(max_completion_tokens=100)
        self.answer_context = ContextProvider(self.answer_provider, FullHistoryContext(),
                                              input_estimator=estimate_qwen_input, window_budget=self.window)
        summary_provider = MockProvider([Message("assistant", "测试失败，待排查", stop_reason="stop")])
        summary_provider.max_completion_tokens = 100
        self.candidate = await prepare_compaction_candidate(
            self.store.load().history, self.references, self.tools, summary_provider, lambda item: 1,
            estimate_qwen_input, self.window, self.window, SummaryCallBudget(1), 1, 10000,
            session_id=self.session_id,
            answer_context=self.answer_context,
        )

    async def save(self, **kwargs):
        estimator = kwargs.pop("estimator", None)
        context = self.answer_context if estimator is None else ContextProvider(
            self.answer_provider, FullHistoryContext(), input_estimator=estimator, window_budget=self.window)
        return await save_compaction_candidate(self.store, self.candidate, self.references, self.tools,
                                               context, self.window, 10000, **kwargs)

    async def test_saved_record_keeps_original_history_and_excludes_references(self):
        before = self.path.read_bytes()
        old_history = self.store.load().history
        data, _ = await self.save()
        self.assertTrue(self.path.read_bytes().startswith(before))
        loaded = self.store.load()
        self.assertEqual(loaded.history, old_history)
        self.assertEqual(loaded.records[-1]["type"], "compaction")
        self.assertEqual(loaded.records[-1]["data"], data)
        self.assertNotIn("本轮参考资料", self.path.read_text(encoding="utf-8"))
        after = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "已有摘要"):
            await self.save()
        self.assertEqual(self.path.read_bytes(), after)

    async def test_read_saved_summary_accepts_new_messages_but_rejects_changed_history(self):
        self.assertIsNone(read_saved_compaction(self.store.load()))
        await self.save()
        later_store = SessionStore(self.path, "run-b")
        later_store.append_item(Message("user", "新进展"))
        summary, binding = read_saved_compaction(later_store.load())
        self.assertEqual(summary, "测试失败，待排查")
        self.assertEqual(binding, self.candidate.binding)
        content = self.path.read_text(encoding="utf-8")
        self.path.write_text(content.replace("测试失败", "测试通过", 1), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "历史已变化"):
            read_saved_compaction(later_store.load())

    async def test_restored_view_uses_summary_recent_and_later_without_rewriting_history(self):
        initial = self.store.load().history
        self.assertEqual(build_restored_history(self.store.load()), initial)
        await self.save()
        later_store = SessionStore(self.path, "run-b")
        later_store.append_item(Message("user", "先检查配置"))
        before = self.path.read_bytes()
        loaded = later_store.load()
        view = build_restored_history(loaded)
        self.assertEqual(len(view), 3)
        self.assertIn("测试失败，待排查", view[0].content)
        self.assertEqual(view[1:], [Message("user", "继续"), Message("user", "先检查配置")])
        self.assertEqual(loaded.history, initial + [Message("user", "先检查配置")])
        self.assertEqual(self.path.read_bytes(), before)

    async def test_restored_view_refuses_unfinished_tool_call(self):
        await self.save()
        later_store = SessionStore(self.path, "run-b")
        later_store.append_item(Message("assistant", "运行", [ToolCall("pending", "test", {})]))
        with self.assertRaisesRegex(ValueError, "未完成"):
            build_restored_history(later_store.load())

    async def test_live_restored_history_appends_new_messages_without_changing_original(self):
        await self.save()
        loaded = self.store.load()
        source = deepcopy(loaded.history)
        extra = [Message("user", "检查配置"),
                 Message("assistant", "读取", [ToolCall("r", "read", {"path": "config"})]),
                 ToolResult("r", "read", "配置结果")]
        live = deepcopy(source) + extra
        before = self.path.read_bytes()
        view = build_live_restored_history(loaded, live)
        self.assertIn("测试失败，待排查", view[0].content)
        self.assertEqual(view[1:], [Message("user", "继续"), *extra])
        self.assertEqual(loaded.history, source)
        self.assertEqual(live, source + extra)
        self.assertEqual(self.path.read_bytes(), before)

    async def test_live_restore_rejects_changed_prefix_and_incomplete_new_tool_group(self):
        await self.save()
        loaded = self.store.load()
        changed = deepcopy(loaded.history)
        changed[0].content = "其他任务"
        with self.assertRaisesRegex(ValueError, "运行历史与已加载会话不一致"):
            build_live_restored_history(loaded, changed)
        incomplete = deepcopy(loaded.history) + [Message("assistant", "读取", [ToolCall("r", "read", {})])]
        with self.assertRaises(MemoryContextError):
            build_live_restored_history(loaded, incomplete)

    async def test_read_rejects_summary_written_before_its_recorded_history(self):
        await self.save()
        records = self.store.load().records
        identity = next(item for item in records if item["type"] == "session_identity")
        summary = next(item for item in records if item["type"] == "compaction")
        messages = [item for item in records if item["type"] in ("message", "tool_result")]
        invalid_order = [identity, *messages[:-1], summary, messages[-1]]
        self.path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in invalid_order),
                             encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "位置与历史条数不一致"):
            read_saved_compaction(self.store.load())

    async def test_stale_history_or_deadline_rejects_without_appending(self):
        before = self.path.read_bytes()
        with self.assertRaises(RunDeadlineExceeded):
            await self.save(deadline=asyncio.get_running_loop().time() - 1)
        self.assertEqual(self.path.read_bytes(), before)
        self.store.append_item(Message("user", "新要求"))
        after_change = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "历史已变化"):
            await self.save()
        self.assertEqual(self.path.read_bytes(), after_change)

    async def test_cancellation_during_estimation_stops_before_write(self):
        before = self.path.read_bytes()
        def cancelling_estimator(messages, tools):
            asyncio.current_task().cancel()
            return estimate_qwen_input(messages, tools)
        task = asyncio.create_task(self.save(estimator=cancelling_estimator))
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.path.read_bytes(), before)

    async def test_long_recent_read_is_shortened_for_candidate_and_save_not_original(self):
        full_output = "文件正文" * 2000
        self.store.append_item(Message("assistant", "读取", [ToolCall("read-2", "read_file", {"path": "a"})]))
        self.store.append_item(ToolResult("read-2", "read_file", full_output))
        self.store.append_item(Message("user", "继续查看"))
        before = self.store.load().history
        window = ContextWindowBudget(500, 100)
        answer_context = ContextProvider(self.answer_provider, ReadOutputContext(120),
                                         input_estimator=estimate_qwen_input, window_budget=window)
        summary_provider = MockProvider([Message("assistant", "登录问题待排查", stop_reason="stop")])
        summary_provider.max_completion_tokens = 100
        candidate = await prepare_compaction_candidate(
            before, [], [], summary_provider, lambda item: 1, estimate_qwen_input,
            ContextWindowBudget(10000, 100), window, SummaryCallBudget(1), 2, None,
            session_id=self.session_id, answer_context=answer_context,
        )
        read = next(item for item in candidate.messages if isinstance(item, ToolResult))
        self.assertEqual(len(read.output), 120)
        data, estimate = await save_compaction_candidate(self.store, candidate, [], [], answer_context, window, None)
        self.assertEqual(estimate, estimate_qwen_input(candidate.messages, []))
        self.assertEqual(self.store.load().history, before)
        self.assertEqual(self.store.load().records[-1]["data"], data)
        self.assertEqual(next(item for item in self.store.load().history
                              if isinstance(item, ToolResult) and item.tool_call_id == "read-2").output, full_output)

    async def test_save_rechecks_history_after_waiting_for_builder(self):
        started, release = asyncio.Event(), asyncio.Event()

        class WaitingBuilder(FullHistoryContext):
            async def build(self, history):
                started.set()
                await release.wait()
                return await super().build(history)

        context = ContextProvider(self.answer_provider, WaitingBuilder(), input_estimator=estimate_qwen_input,
                                  window_budget=self.window)
        task = asyncio.create_task(save_compaction_candidate(self.store, self.candidate, self.references, self.tools,
                                                             context, self.window, 10000))
        try:
            await asyncio.wait_for(started.wait(), 1)
            self.store.append_item(Message("user", "等待期间的新要求"))
            release.set()
            with self.assertRaisesRegex(ValueError, "历史已变化"):
                await task
            loaded = self.store.load()
            self.assertEqual(loaded.history[-1].content, "等待期间的新要求")
            self.assertFalse(any(record["type"] == "compaction" for record in loaded.records))
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_partial_write_reports_error_and_reader_rejects_tail(self):
        before = self.path.read_bytes()
        def partial_write(event_type, data):
            with self.path.open("a", encoding="utf-8") as file:
                file.write('{"type":')
            raise OSError("模拟写入中断")
        with patch.object(self.store, "append_entry", side_effect=partial_write):
            with self.assertRaises(OSError):
                await self.save()
        self.assertTrue(self.path.read_bytes().startswith(before))
        with self.assertRaisesRegex(ValueError, "无效"):
            self.store.load()


if __name__ == "__main__":
    unittest.main()
