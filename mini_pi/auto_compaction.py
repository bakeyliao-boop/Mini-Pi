"""D17：自动压缩的配置与控制。"""

from mini_pi.compaction_trigger import should_compact  # 复用触发点检查
from mini_pi.context_size import InputSizeEstimate  # 构造用于配置检查的估算值
from dataclasses import dataclass

@dataclass(frozen=True)
class AutoCompactionSettings:
    trigger_tokens:int
    keep_recent_tokens:int

def check_auto_compaction_settings(settings, window_budget):
    if not isinstance(settings, AutoCompactionSettings):  # 必须提供自动压缩配置
        raise ValueError("自动压缩配置格式不正确")
    if type(settings.keep_recent_tokens) is not int or settings.keep_recent_tokens <= 0:  # 近期保留量必须为正整数
        raise ValueError("近期保留量必须是正整数")

    empty_estimate = InputSizeEstimate(0, 0, "config-check")  # 用零输入检查配置，不代表实际请求
    should_compact(
        empty_estimate, window_budget, settings.trigger_tokens  # 复用已有的窗口和触发点检查
    )
