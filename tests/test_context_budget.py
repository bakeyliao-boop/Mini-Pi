"""D16估算窗口门禁：边界、预留空间、余量与配置错误。"""

import unittest

from mini_pi.context_budget import ContextBudgetError, check_estimated_window


class EstimatedWindowTests(unittest.TestCase):
    def test_request_below_window_passes_without_explicit_margin(self):
        self.assertIsNone(check_estimated_window(6000, 1500, 8000))

    def test_exact_window_including_margin_passes(self):
        self.assertIsNone(check_estimated_window(6500, 1000, 8000, 500))

    def test_one_token_over_window_reports_budget_error(self):
        with self.assertRaises(ContextBudgetError) as caught:
            check_estimated_window(6501, 1000, 8000, 500)
        self.assertIn("8001", str(caught.exception))
        self.assertIn("8000", str(caught.exception))

    def test_output_reservation_can_make_otherwise_fitting_input_fail(self):
        self.assertIsNone(check_estimated_window(7800, 200, 8000))
        with self.assertRaises(ContextBudgetError):
            check_estimated_window(7800, 201, 8000)

    def test_safety_margin_can_make_otherwise_fitting_request_fail(self):
        self.assertIsNone(check_estimated_window(7000, 1000, 8000, 0))
        with self.assertRaises(ContextBudgetError):
            check_estimated_window(7000, 1000, 8000, 1)

    def test_zero_input_and_margin_allowed_but_output_and_window_must_be_positive(self):
        self.assertIsNone(check_estimated_window(0, 1, 1, 0))
        for args in ((0, 0, 1, 0), (0, 1, 0, 0)):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    check_estimated_window(*args)

    def test_invalid_value_in_each_position_is_configuration_error(self):
        for position in range(4):
            for invalid in (True, False, -1, 1.5, "100", None):
                with self.subTest(position=position, value=invalid):
                    args = [6000, 1000, 8000, 500]
                    args[position] = invalid
                    with self.assertRaises(ValueError):
                        check_estimated_window(*args)


if __name__ == "__main__":
    unittest.main()
