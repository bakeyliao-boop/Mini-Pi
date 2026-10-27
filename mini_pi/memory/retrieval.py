"""MEM-03：业务可用性判断，数据库读取复用 backend。

is_usable 接收由 backend 严格解码并核对来源的 MemoryEntry。
scope 及场景条件由可信调用方提供，不是模型自行声称的身份或权限。
"""

from mini_pi.memory.models import Conditions, MemoryEntry, MemoryScope
from mini_pi.memory.retrieval_helpers import normalize_read_request


def is_usable(
    entry: MemoryEntry, scope: MemoryScope, *, conditions: Conditions, at: str,
) -> bool:
    """判断当前允许使用的版本是否适用于问题时间；不修改记录。"""
    conditions, at = normalize_read_request(scope, conditions, at)

    if entry.scope != scope:
        return False
    if entry.state == "retracted":
        return False

    context_conditions = dict(conditions)
    for key, expected in entry.draft.conditions:
        if context_conditions.get(key) != expected:
            return False

    if at < entry.draft.valid_from:
        return False
    if entry.valid_to is not None and at >= entry.valid_to:
        return False

    return True
