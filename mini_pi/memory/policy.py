"""MEM-01：来源、范围与原文片段入库门禁，由学习者手敲。"""

from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.validation_helpers import validate_shapes


def validate_draft(
    scope: MemoryScope, source: MemorySource, draft: MemoryDraft,
) -> None:
    """允许时返回 None；拒绝时抛 MemoryPolicyError，尚不执行数据库写入。"""
    validate_shapes(scope,source,draft)

    if source.scope != scope:
        raise MemoryPolicyError("来源不属于当前用户或项目")

    if source.role not in {"user","tool"}:
        raise MemoryPolicyError("只接收用户陈述或工具观察")

    if source.role == "tool" and draft.kind != "episodic":
        raise MemoryPolicyError("工具观察只能保存为情景记忆")

    if draft.start != 0 or draft.end != len(source.text):
        raise MemoryPolicyError("首版本只接收完整原文。")
