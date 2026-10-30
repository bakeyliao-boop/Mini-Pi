"""D17：摘要模型调用次数的单次运行预算。"""

from mini_pi.context_budget import ContextBudgetError


class SummaryCallBudgetExceeded(ContextBudgetError):
    """本次运行的摘要调用次数已用完。"""

class SummaryCallBudget:
    def __init__(self, max_calls):
        if type(max_calls) is not int or max_calls <= 0:  # 上限必须是正整数
            raise ValueError("摘要调用上限必须是正整数")
        self._max_calls = max_calls  # 保存本次运行的调用上限
        self._used_calls = 0  # 本次运行还没有启动摘要请求

    @property
    def used_calls(self):
        return self._used_calls  # 供调用方查看已经启动的次数

    def take(self):
        if self._used_calls >= self._max_calls:  # 次数已用完
            raise SummaryCallBudgetExceeded("摘要调用次数已用完")
        self._used_calls += 1  # 允许启动一次请求，并记下这次尝试