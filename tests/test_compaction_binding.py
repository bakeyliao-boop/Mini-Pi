"""摘要来源标签的内容、稳定性和安全边界。"""

from copy import deepcopy
from dataclasses import replace
import unittest

from mini_pi.compaction_binding import check_compaction_binding, fingerprint_history, make_compaction_binding
from mini_pi.memory.errors import MemoryContextError
from mini_pi.models import Message, ToolCall, ToolResult


class CompactionBindingTests(unittest.TestCase):
    def setUp(self):
        self.history = [Message("system", "规则"), Message("user", "修复"),
                        Message("assistant", "测试", [ToolCall("t", "test", {"a": 1, "b": 2})]),
                        ToolResult("t", "test", "失败"), Message("user", "继续")]

    def test_binding_records_session_count_cut_and_full_history_fingerprint(self):
        before = deepcopy(self.history)
        binding = make_compaction_binding("session-a", self.history, 4)
        self.assertEqual((binding.session_id, binding.history_count, binding.cut_index), ("session-a", 5, 4))
        self.assertEqual(binding.history_fingerprint, fingerprint_history(before))
        self.history[-1].content = "近期内容被修改"
        self.assertNotEqual(binding.history_fingerprint, fingerprint_history(self.history))
        self.assertEqual(binding.history_fingerprint, fingerprint_history(before))

    def test_canonical_argument_order_and_unsafe_inputs(self):
        reordered = deepcopy(self.history)
        reordered[2].tool_calls[0].arguments = {"b": 2, "a": 1}
        self.assertEqual(fingerprint_history(self.history), fingerprint_history(reordered))
        with self.assertRaises(ValueError):
            make_compaction_binding("session-a", self.history, 3)
        with self.assertRaises(ValueError):
            make_compaction_binding("  ", self.history, 4)
        with self.assertRaises(MemoryContextError):
            make_compaction_binding("session-a", self.history[:3] + [Message("user", "继续")], 1)

    def test_matching_history_and_new_appended_items_pass(self):
        binding = make_compaction_binding("session-a", self.history, 4)
        appended = deepcopy(self.history) + [Message("assistant", "新的进展")]
        self.assertIsNone(check_compaction_binding(binding, "session-a", appended))

    def test_changed_truncated_wrong_session_and_unsafe_boundary_fail(self):
        binding = make_compaction_binding("session-a", self.history, 4)
        changed = deepcopy(self.history)
        changed[3].output = "通过"
        for label, candidate, session_id, history in (
            ("changed", binding, "session-a", changed),
            ("truncated", binding, "session-a", self.history[:-1]),
            ("wrong-session", binding, "session-b", self.history),
            ("unsafe-cut", replace(binding, cut_index=3), "session-a", self.history),
            ("bad-count", replace(binding, history_count=True), "session-a", self.history),
        ):
            with self.subTest(label=label), self.assertRaises(ValueError):
                check_compaction_binding(candidate, session_id, history)


if __name__ == "__main__":
    unittest.main()
