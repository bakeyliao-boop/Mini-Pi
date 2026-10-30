"""摘要请求空间检查：估算包含提示与旧过程，并预留输出。"""

from copy import deepcopy
from types import SimpleNamespace
import unittest

from mini_pi.compaction import build_summary_request, check_summary_budget, prepare_summary_call
from mini_pi.context_budget import ContextBudgetError, ContextWindowBudget
from mini_pi.context_size import InputSizeEstimate, estimate_qwen_input
from mini_pi.models import Message


class SummaryBudgetTests(unittest.TestCase):
    def test_prepare_checks_actual_output_limit_and_does_not_call_provider(self):
        class Provider:
            def __init__(self, limit):
                self.max_completion_tokens = limit
                self.calls = 0

            async def generate(self, messages, tools):
                self.calls += 1
                raise AssertionError("准备阶段不应请求模型")

        history = [Message("user", "修复登录")]
        window = ContextWindowBudget(10000, 200, 10)
        provider = Provider(200)
        request, estimate = prepare_summary_call(history, provider, estimate_qwen_input, window)
        self.assertEqual([m.role for m in request], ["system", "user"])
        self.assertEqual(estimate, estimate_qwen_input(request, []))
        self.assertEqual(provider.calls, 0)
        for limit in (201, 0, -1, True, None):
            invalid = Provider(limit)
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                prepare_summary_call(history, invalid, estimate_qwen_input, window)
            self.assertEqual(invalid.calls, 0)
        with self.assertRaises(ValueError):
            prepare_summary_call(history, SimpleNamespace(), estimate_qwen_input, window)

    def test_exact_budget_passes_and_one_token_over_fails(self):
        request = build_summary_request([Message("user", "修复登录")])
        estimate = estimate_qwen_input(request, [])
        reserve, margin = 40, 5
        exact = estimate.estimated_input_tokens + reserve + margin
        self.assertEqual(check_summary_budget(request, estimate_qwen_input,
                                             ContextWindowBudget(exact, reserve, margin)), estimate)
        with self.assertRaises(ContextBudgetError):
            check_summary_budget(request, estimate_qwen_input, ContextWindowBudget(exact - 1, reserve, margin))

    def test_estimator_receives_no_tools_and_cannot_mutate_request(self):
        request = build_summary_request([Message("user", "任务")])
        before = deepcopy(request)
        def estimator(messages, tools):
            self.assertEqual(tools, [])
            messages[1].content = "被估算器修改"
            return InputSizeEstimate(4, 1, "test")
        check_summary_budget(request, estimator, ContextWindowBudget(100, 20))
        self.assertEqual(request, before)

    def test_invalid_configuration_or_result_fails(self):
        request = build_summary_request([Message("user", "任务")])
        for estimator, budget in ((None, ContextWindowBudget(100, 10)),
                                  (estimate_qwen_input, None),
                                  (lambda messages, tools: 1, ContextWindowBudget(100, 10))):
            with self.subTest(estimator=estimator, budget=budget), self.assertRaises(ValueError):
                check_summary_budget(request, estimator, budget)


if __name__ == "__main__":
    unittest.main()
