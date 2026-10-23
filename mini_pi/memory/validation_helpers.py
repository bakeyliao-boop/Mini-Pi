"""助手准备：时间和条件的格式校验，不决定哪些来源允许入库。"""

from datetime import UTC, datetime

from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.models import Conditions, MemoryDraft, MemoryScope, MemorySource


def require_text(value: str, label: str) -> None:
    """检查输入形状，不截断或修改原始内容。"""
    if not isinstance(value, str) or not value.strip():
        raise MemoryPolicyError(f"{label} 必须是非空字符串")


def normalize_time(value: str) -> str:
    """拒绝无时区时间，统一 UTC；不从记录时间推断事实生效时间。"""
    if not isinstance(value, str):
        raise MemoryPolicyError("时间必须是带时区的 ISO 字符串")
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as error:
        raise MemoryPolicyError("时间必须是带时区的 ISO 字符串") from error
    if instant.utcoffset() is None:
        raise MemoryPolicyError("时间必须明确时区")
    return instant.astimezone(UTC).isoformat(timespec="microseconds")


def normalize_conditions(value: Conditions) -> Conditions:
    """条件用不可变键值对表示；重复键不能静默覆盖。"""
    if not isinstance(value, tuple):
        raise MemoryPolicyError("条件必须是键值对元组")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, tuple) or len(item) != 2:
            raise MemoryPolicyError("每个条件必须是二元组")
        key, text = item
        if not isinstance(key, str) or not key.strip():
            raise MemoryPolicyError("条件名必须是非空字符串")
        if not isinstance(text, str) or not text.strip() or key in seen:
            raise MemoryPolicyError("条件值必须非空，条件名不能重复")
        seen.add(key)
        result.append((key, text))
    return tuple(sorted(result))


def validate_shapes(
    scope: MemoryScope, source: MemorySource, draft: MemoryDraft,
) -> None:
    """只检查数据形状；来源准入和整段原文门禁留给 policy。"""
    if not isinstance(scope, MemoryScope) or not isinstance(source, MemorySource):
        raise MemoryPolicyError("scope/source 必须使用约定的数据容器")
    if not isinstance(source.scope, MemoryScope) or not isinstance(draft, MemoryDraft):
        raise MemoryPolicyError("来源范围和候选必须使用约定的数据容器")
    for item in (scope, source.scope):
        require_text(item.user_id, "user_id")
        require_text(item.project_id, "project_id")
    require_text(source.source_id, "source_id")
    require_text(source.role, "来源角色")
    require_text(source.text, "来源原文")
    require_text(draft.key, "记忆属性名")
    if draft.content is not None:
        require_text(draft.content, "规范化正文")
    if draft.kind not in ("semantic", "episodic", "procedural"):
        raise MemoryPolicyError("不支持的记忆类型")
    if type(draft.start) is not int or type(draft.end) is not int:
        raise MemoryPolicyError("原文位置必须是整数，不能使用布尔值")
    if not 0 <= draft.start < draft.end <= len(source.text):
        raise MemoryPolicyError("原文片段位置越界或为空")
    normalize_time(source.recorded_at)
    normalize_time(draft.valid_from)
    normalize_conditions(draft.conditions)
