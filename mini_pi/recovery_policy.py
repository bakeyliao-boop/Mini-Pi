"""D11：把缺少结果的调用转换为恢复状态；判断本身不执行工具。"""

from dataclasses import dataclass

from mini_pi.session_recovery import PendingCall


@dataclass(frozen=True)
class RecoveryPlan:
    """恢复判断及其依据；具体后续动作由恢复入口安排。"""

    state: str
    pending_calls: list[PendingCall]


def plan_recovery(
    pending_calls: list[PendingCall],
    read_only_tools: frozenset[str],
) -> RecoveryPlan:
    """只读工具范围由程序配置；缺少写入结果时留待核对。"""
    if not pending_calls:
        return RecoveryPlan("ready",pending_calls)
    for item in pending_calls:
        if item.call.name not in read_only_tools:  #如果结果丢失的工具可能修改外部状态，就暂停自动恢复，人工检查
            return RecoveryPlan("needs_review",pending_calls)
    return RecoveryPlan("read_interrupted",pending_calls)
