"""摘要待保存记录：只包含摘要和来源，不写入会话。"""

from dataclasses import asdict, replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from mini_pi.compaction_pipeline import prepare_compaction_candidate
from mini_pi.compaction_record import check_answer_output_limit, check_candidate_before_save, make_compaction_record
from mini_pi.context_budget import ContextBudgetError, ContextWindowBudget
from mini_pi.context import ContextProvider, FullHistoryContext
from mini_pi.context_size import estimate_qwen_input
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolDefinition, ToolResult
from mini_pi.session_store import SessionStore
from mini_pi.summary_call_budget import SummaryCallBudget


class CompactionRecordPreparationTests(unittest.IsolatedAsyncioTestCase):
    def test_answer_provider_output_limit_matches_reserved_space(self):
        window = ContextWindowBudget(1000, 200)
        self.assertIsNone(check_answer_output_limit(SimpleNamespace(max_completion_tokens=200), window))
        for limit in (201, 0, -1, True, None):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                check_answer_output_limit(SimpleNamespace(max_completion_tokens=limit), window)
        with self.assertRaises(ValueError):
            check_answer_output_limit(SimpleNamespace(), window)
        with self.assertRaises(ValueError):
            check_answer_output_limit(SimpleNamespace(max_completion_tokens=100), None)

    async def test_record_contains_binding_and_summary_without_reference_or_write(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            store = SessionStore(path, "run-a")
            store.append_item(Message("user", "修复登录"))
            store.append_item(Message("assistant", "测试", [ToolCall("t", "test", {})]))
            store.append_item(ToolResult("t", "test", "失败"))
            store.append_item(Message("user", "继续"))
            session_id = store.ensure_session_id()
            loaded = store.load()
            provider = MockProvider([Message("assistant", "测试失败，待排查", stop_reason="stop")])
            provider.max_completion_tokens = 100
            window = ContextWindowBudget(10000, 100)
            answer_context = ContextProvider(MockProvider([]), FullHistoryContext(),
                                             input_estimator=estimate_qwen_input, window_budget=window)
            candidate = await prepare_compaction_candidate(
                loaded.history, [Message("user", "本轮临时资料")], [], provider, lambda item: 1,
                estimate_qwen_input, window, window,
                SummaryCallBudget(1), 1, 10000, session_id=session_id,
                answer_context=answer_context,
            )
            before = path.read_bytes()
            data = make_compaction_record(store.load(), candidate)
            self.assertEqual(data, {**asdict(candidate.binding), "summary": "测试失败，待排查"})
            self.assertNotIn("本轮临时资料", json.dumps(data, ensure_ascii=False))
            self.assertEqual(path.read_bytes(), before)
            references = [Message("user", "本轮临时资料")]
            prepared, estimate = await check_candidate_before_save(store.load(), candidate, references, [],
                                                                   answer_context, window, 10000)
            self.assertEqual(prepared, data)
            self.assertEqual(estimate, estimate_qwen_input(candidate.messages, []))
            with self.assertRaisesRegex(ValueError, "候选请求已变化"):
                await check_candidate_before_save(store.load(), replace(candidate, summary="测试通过"), references, [],
                                                  answer_context, window, 10000)
            with self.assertRaisesRegex(ValueError, "候选请求已变化"):
                await check_candidate_before_save(store.load(), candidate, [Message("user", "不同资料")], [],
                                                  answer_context, window, 10000)
            large_tools = [ToolDefinition("read", "很长的工具描述" * 10000, {"type": "object"})]
            with self.assertRaises(ContextBudgetError):
                await check_candidate_before_save(store.load(), candidate, references, large_tools,
                                                  answer_context, window, 10000)
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaisesRegex(ValueError, "切点"):
                make_compaction_record(store.load(), replace(candidate, cut_index=1))
            store.append_item(Message("user", "新要求"))
            with self.assertRaisesRegex(ValueError, "历史已变化"):
                make_compaction_record(store.load(), candidate)


if __name__ == "__main__":
    unittest.main()
