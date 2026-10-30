"""完整候选请求的配对、字符和窗口检查。"""

from copy import deepcopy
import unittest

from mini_pi.compaction import build_compacted_request
from mini_pi.context import check_compacted_request
from mini_pi.context_budget import ContextBudgetError, ContextWindowBudget
from mini_pi.context_size import estimate_qwen_input
from mini_pi.memory.context_helpers import messages_char_count
from mini_pi.memory.errors import MemoryContextError
from mini_pi.models import Message, ToolDefinition, ToolResult


class CompactedRequestBudgetTests(unittest.TestCase):
    def test_window_is_checked_without_a_character_limit(self):
        messages = build_compacted_request([], "旧摘要", [Message("user", "继续")], [])
        estimate = estimate_qwen_input(messages, [])
        window = ContextWindowBudget(estimate.estimated_input_tokens + 10, 10)
        self.assertEqual(check_compacted_request(messages, [], estimate_qwen_input, window, None), estimate)
        with self.assertRaises(ContextBudgetError):
            check_compacted_request(messages, [], estimate_qwen_input,
                                    ContextWindowBudget(estimate.estimated_input_tokens + 9, 10), None)

    def test_reference_and_tools_count_toward_final_window(self):
        recent = [Message("user", "继续")]
        base = build_compacted_request([], "旧摘要", recent, [])
        with_ref = build_compacted_request([], "旧摘要", recent, [Message("user", "资料" * 500)])
        tools = [ToolDefinition("read", "工具说明" * 500, {"type": "object"})]
        estimate = estimate_qwen_input(base, [])
        budget = ContextWindowBudget(estimate.estimated_input_tokens + 10, 10)
        char_limit = messages_char_count(with_ref) + 1
        check_compacted_request(base, [], estimate_qwen_input, budget, char_limit)
        with self.assertRaises(ContextBudgetError):
            check_compacted_request(with_ref, [], estimate_qwen_input, budget, char_limit)
        with self.assertRaises(ContextBudgetError):
            check_compacted_request(base, tools, estimate_qwen_input, budget, char_limit)

    def test_incomplete_tool_result_and_character_overflow_fail(self):
        messages = [Message("user", "摘要"), ToolResult("orphan", "read", "结果")]
        with self.assertRaises(MemoryContextError):
            check_compacted_request(messages, [], estimate_qwen_input, ContextWindowBudget(10000, 10), 10000)
        valid = [Message("user", "摘要")]
        before = deepcopy(valid)
        with self.assertRaises(MemoryContextError):
            check_compacted_request(valid, [], estimate_qwen_input, ContextWindowBudget(10000, 10), 1)
        self.assertEqual(valid, before)


if __name__ == "__main__":
    unittest.main()
