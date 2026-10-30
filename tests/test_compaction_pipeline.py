"""从安全切点到候选请求的离线联合验证。"""

from copy import deepcopy
import json
import unittest

from mini_pi.compaction import SummaryError
from mini_pi.compaction_binding import check_compaction_binding
from mini_pi.compaction_pipeline import prepare_compaction_candidate
from mini_pi.context_budget import ContextBudgetError, ContextWindowBudget
from mini_pi.context import ContextProvider, FullHistoryContext, ReadOutputContext
from mini_pi.context_size import estimate_qwen_input
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolDefinition, ToolResult
from mini_pi.summary_call_budget import SummaryCallBudget


class CompactionPipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.history = [Message("system", "保留规则"), Message("user", "修复登录"),
                        Message("assistant", "运行测试", [ToolCall("t", "test", {})]),
                        ToolResult("t", "test", "测试失败"), Message("user", "继续")]
        self.references = [Message("user", "临时参考资料")]
        self.tools = [ToolDefinition("test", "运行测试", {"type": "object"})]
        self.provider = MockProvider([Message("assistant", "测试失败，待排查", stop_reason="stop")])
        self.provider.max_completion_tokens = 100
        self.budget = SummaryCallBudget(1)
        self.options = dict(summary_provider=self.provider, item_estimator=lambda item: 1,
                            request_estimator=estimate_qwen_input,
                            summary_window=ContextWindowBudget(10000, 100),
                            answer_window=ContextWindowBudget(10000, 100),
                            call_budget=self.budget, keep_recent_tokens=1, max_context_chars=10000,
                            session_id="session-a")
        self.options["answer_context"] = ContextProvider(MockProvider([]), FullHistoryContext(),
                                                         input_estimator=estimate_qwen_input,
                                                         window_budget=self.options["answer_window"])

    async def test_candidate_keeps_sources_separate_and_originals_unchanged(self):
        before = deepcopy((self.history, self.references, self.tools))
        candidate = await prepare_compaction_candidate(self.history, self.references, self.tools, **self.options)
        self.assertEqual(candidate.cut_index, 4)
        self.assertEqual(candidate.summary, "测试失败，待排查")
        self.assertEqual(candidate.binding.session_id, "session-a")
        self.assertEqual(candidate.binding.cut_index, candidate.cut_index)
        check_compaction_binding(candidate.binding, "session-a", self.history)
        self.assertEqual(candidate.messages[0], self.history[0])
        self.assertEqual(candidate.messages[1], self.references[0])
        self.assertIn(candidate.summary, candidate.messages[2].content)
        self.assertEqual(candidate.messages[3:], self.history[4:])
        records = json.loads(self.provider.requests[0][1].content)
        self.assertEqual([record["type"] for record in records], ["message", "message", "tool_result"])
        self.assertEqual(records[-1]["data"]["output"], "测试失败")
        self.assertNotIn("临时参考资料", self.provider.requests[0][1].content)
        self.assertEqual(candidate.request_estimate, estimate_qwen_input(candidate.messages, self.tools))
        self.assertEqual(self.budget.used_calls, 1)
        self.assertEqual((self.history, self.references, self.tools), before)

    async def test_binding_uses_history_before_async_summary_changes_source(self):
        original = deepcopy(self.history)
        def change_source(messages, tools):
            self.history[3].output = "已修改的测试结果"
            return Message("assistant", "测试失败，待排查", stop_reason="stop")
        self.provider.responses = [change_source]
        candidate = await prepare_compaction_candidate(self.history, self.references, self.tools, **self.options)
        check_compaction_binding(candidate.binding, "session-a", original)
        with self.assertRaisesRegex(ValueError, "历史已变化"):
            check_compaction_binding(candidate.binding, "session-a", self.history)
        records = json.loads(self.provider.requests[0][1].content)
        self.assertEqual(records[-1]["data"]["output"], "测试失败")

    async def test_no_cut_does_not_start_summary(self):
        self.options["keep_recent_tokens"] = 100
        self.assertIsNone(await prepare_compaction_candidate(self.history, self.references, self.tools, **self.options))
        self.assertEqual(self.provider.requests, [])
        self.assertEqual(self.budget.used_calls, 0)

    async def test_rejected_summary_or_answer_window_never_returns_candidate(self):
        self.provider.responses = [Message("assistant", "部分", stop_reason="length")]
        with self.assertRaises(SummaryError):
            await prepare_compaction_candidate(self.history, self.references, self.tools, **self.options)
        self.assertEqual(self.budget.used_calls, 1)

        self.provider.responses = [Message("assistant", "完成", stop_reason="stop")]
        self.provider.requests.clear()
        self.provider.tool_requests.clear()
        self.options["call_budget"] = SummaryCallBudget(1)
        self.options["answer_window"] = ContextWindowBudget(20, 10)
        self.options["answer_context"] = ContextProvider(MockProvider([]), FullHistoryContext(),
                                                         input_estimator=estimate_qwen_input,
                                                         window_budget=self.options["answer_window"])
        with self.assertRaises(ContextBudgetError):
            await prepare_compaction_candidate(self.history, self.references, self.tools, **self.options)
        self.assertEqual(self.options["call_budget"].used_calls, 1)
        self.assertEqual(len(self.provider.requests), 1)

    async def test_candidate_checks_recent_read_after_shortening(self):
        history = [Message("user", "修复登录"),
                   Message("assistant", "读取", [ToolCall("read", "read_file", {"path": "a"})]),
                   ToolResult("read", "read_file", "文件内容" * 2000), Message("user", "继续")]
        original = deepcopy(history)
        window = ContextWindowBudget(500, 100)
        answer = ContextProvider(MockProvider([]), ReadOutputContext(120), input_estimator=estimate_qwen_input,
                                 window_budget=window)
        candidate = await prepare_compaction_candidate(
            history, [], [], self.provider, lambda item: 1, estimate_qwen_input,
            ContextWindowBudget(10000, 100), window, self.budget, 2, None,
            session_id="session-a", answer_context=answer,
        )
        read = next(item for item in candidate.messages if isinstance(item, ToolResult))
        self.assertEqual(len(read.output), 120)
        self.assertLessEqual(candidate.request_estimate.estimated_input_tokens + 100, 500)
        self.assertEqual(history, original)


if __name__ == "__main__":
    unittest.main()
