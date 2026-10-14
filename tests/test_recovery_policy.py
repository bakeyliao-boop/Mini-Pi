"""助手准备：核对恢复分类边界，测试不执行任何工具。"""

import unittest

from mini_pi.models import ToolCall
from mini_pi.recovery_policy import plan_recovery
from mini_pi.session_recovery import PendingCall


READ_ONLY_TOOLS = frozenset({"read_file", "list_files"})


class RecoveryPolicyTests(unittest.TestCase):
    def _pending(self, *names):
        return [
            PendingCall("run_A", ToolCall(f"call_{index}", name, {}))
            for index, name in enumerate(names, start=1)
        ]

    def test_no_pending_is_ready(self):
        plan = plan_recovery([], READ_ONLY_TOOLS)
        self.assertEqual(plan.state, "ready")
        self.assertEqual(plan.pending_calls, [])

    def test_all_explicitly_read_only_calls_are_read_interrupted(self):
        pending = self._pending("read_file", "list_files")
        plan = plan_recovery(pending, READ_ONLY_TOOLS)
        self.assertEqual(plan.state, "read_interrupted")
        self.assertEqual(plan.pending_calls, pending)

    def test_edit_unknown_and_run_tests_need_review(self):
        for name in ("edit_file", "unknown_tool", "run_tests"):
            with self.subTest(tool=name):
                pending = self._pending(name)
                plan = plan_recovery(pending, READ_ONLY_TOOLS)
                self.assertEqual(plan.state, "needs_review")
                self.assertEqual(plan.pending_calls, pending)

    def test_mixed_calls_need_review_regardless_of_order(self):
        for names in (("read_file", "edit_file"), ("edit_file", "read_file")):
            with self.subTest(names=names):
                pending = self._pending(*names)
                plan = plan_recovery(pending, READ_ONLY_TOOLS)
                self.assertEqual(plan.state, "needs_review")
                self.assertEqual(plan.pending_calls, pending)

    def test_read_file_is_not_inferred_read_only_from_its_name(self):
        plan = plan_recovery(self._pending("read_file"), frozenset())
        self.assertEqual(plan.state, "needs_review")


if __name__ == "__main__":
    unittest.main()
