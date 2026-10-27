"""D16：请求空间门禁；估算值不等于服务端精确token数。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextWindowBudget:
    """一次请求的估算窗口配置，不代表服务端精确token限制已验证。"""

    context_window_tokens: int
    reserved_output_tokens: int
    safety_margin_tokens: int = 0


class ContextBudgetError(RuntimeError):
    """请求估算超出配置窗口，禁止继续发送本次请求。"""


def check_estimated_window(  # 检查一次请求的估算空间，不发送请求
    estimated_input_tokens: int,  # 已组装完整输入的估算量
    reserved_output_tokens: int,  # 本次回答预留量
    context_window_tokens: int,  # 目标总窗口
    safety_margin_tokens: int = 0,  # 额外余量，默认不添加
) -> None:  # 通过时不返回消息，只允许调用方继续
    values = (  # 收集四项参数，供下面的循环逐项校验。
        estimated_input_tokens, reserved_output_tokens,
        context_window_tokens, safety_margin_tokens,
    )
    for value in values:
        if type(value) is not int or value < 0:
            raise ValueError('空间参数必须非负')

    if reserved_output_tokens == 0 or context_window_tokens == 0:
        raise ValueError('输出和预留空间必须大于0')

    required = estimated_input_tokens + reserved_output_tokens + safety_margin_tokens

    if required > context_window_tokens:
        raise ContextBudgetError(
            f"请求估算需要{required} tokens,超过配置窗口{context_window_tokens} tokens"
            )
