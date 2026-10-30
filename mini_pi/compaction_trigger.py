"""D17：判断完整请求是否达到压缩触发点。"""

from mini_pi.context_budget import ContextWindowBudget, check_estimated_window
from mini_pi.context_size import InputSizeEstimate

def should_compact(estimate, budget, trigger_tokens):
    if not isinstance(estimate, InputSizeEstimate):  # 必须是完整请求的估算结果
        raise ValueError("请求估算结果格式不正确")
    if not isinstance(budget, ContextWindowBudget):  # 必须提供模型窗口配置
        raise ValueError("窗口预算配置不正确")

    check_estimated_window(
        0, budget.reserved_output_tokens,  # 先检查输出预留
        budget.context_window_tokens, budget.safety_margin_tokens,  # 检查窗口和误差余量
    )
    available = (
        budget.context_window_tokens
        - budget.reserved_output_tokens
        - budget.safety_margin_tokens
    )  # 给输入留下的最大估算空间

    if type(trigger_tokens) is not int or not 0 < trigger_tokens < available:  # 触发点要早于输入上限
        raise ValueError("压缩触发点必须小于输入可用空间")
    if type(estimate.estimated_input_tokens) is not int or estimate.estimated_input_tokens < 0:  # 检查估算值
        raise ValueError("输入估算量必须是非负整数")

    return estimate.estimated_input_tokens > trigger_tokens  # 超过触发点才需要压缩
