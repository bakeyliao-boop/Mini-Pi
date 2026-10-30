"""摘要压缩触发点：完整请求的输入估算与阈值。"""

import unittest

from mini_pi.compaction_trigger import should_compact
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context_size import InputSizeEstimate, estimate_qwen_input
from mini_pi.models import Message, ToolDefinition


class CompactionTriggerTests(unittest.TestCase):
    def test_strict_threshold_and_space_for_output(self):
        budget = ContextWindowBudget(10000, 2000, 500)
        self.assertFalse(should_compact(InputSizeEstimate(0, 7000, "test"), budget, 7000))
        self.assertTrue(should_compact(InputSizeEstimate(0, 7001, "test"), budget, 7000))
        for trigger in (0, 7500, 8000, True):
            with self.subTest(trigger=trigger), self.assertRaises(ValueError):
                should_compact(InputSizeEstimate(0, 100, "test"), budget, trigger)

    def test_reference_and_tool_descriptions_can_trigger_compaction(self):
        messages = [Message("user", "继续排查")]
        baseline = estimate_qwen_input(messages, [])
        trigger = baseline.estimated_input_tokens + 5
        budget = ContextWindowBudget(10000, 100)
        with_reference = estimate_qwen_input([Message("user", "资料" * 1000), *messages], [])
        with_tool = estimate_qwen_input(messages, [ToolDefinition("read", "说明" * 1000, {"type": "object"})])
        self.assertFalse(should_compact(baseline, budget, trigger))
        self.assertTrue(should_compact(with_reference, budget, trigger))
        self.assertTrue(should_compact(with_tool, budget, trigger))

    def test_invalid_estimate_is_rejected(self):
        budget = ContextWindowBudget(1000, 100)
        for estimate in (None, InputSizeEstimate(0, -1, "test"), InputSizeEstimate(0, True, "test")):
            with self.subTest(estimate=estimate), self.assertRaises(ValueError):
                should_compact(estimate, budget, 500)


if __name__ == "__main__":
    unittest.main()
