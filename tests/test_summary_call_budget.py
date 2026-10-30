"""摘要调用次数上限与非法配置。"""

import unittest

from mini_pi.context_budget import ContextBudgetError
from mini_pi.summary_call_budget import SummaryCallBudget, SummaryCallBudgetExceeded


class SummaryCallBudgetTests(unittest.TestCase):
    def test_limit_is_recorded_and_rejected_attempt_does_not_increment(self):
        budget = SummaryCallBudget(2)
        self.assertEqual(budget.used_calls, 0)
        budget.take()
        budget.take()
        self.assertEqual(budget.used_calls, 2)
        with self.assertRaises(SummaryCallBudgetExceeded) as caught:
            budget.take()
        self.assertIsInstance(caught.exception, ContextBudgetError)
        self.assertEqual(budget.used_calls, 2)

    def test_invalid_limit_is_rejected(self):
        for limit in (0, -1, True, 1.5, None):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                SummaryCallBudget(limit)


if __name__ == "__main__":
    unittest.main()
