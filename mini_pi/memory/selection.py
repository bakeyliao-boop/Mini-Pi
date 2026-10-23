"""MEM-W：规范化候选、来源核对与建议去向归组；核心由学习者手敲。

模型只提出 content/proposed_route/reason；可信调用方读取并绑定 Source。
本文件不读 Session、不联网、不写库，不证明候选语义或授予写入许可。
"""

from dataclasses import dataclass
from typing import Literal

from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.models import MemoryScope, MemorySource
from mini_pi.memory.validation_helpers import normalize_time, require_text


CandidateRoute = Literal[
    "long_term", "task_constraint", "ignore", "needs_review", "withdrawal",
]
_ROUTES = ("long_term", "task_constraint", "ignore", "needs_review", "withdrawal")


@dataclass(frozen=True)
class MemoryCandidate:
    """程序绑定的完整来源与模型建议；来源关联不等于语义支持。

    source 不是模型输出。真实提取适配器尚未接线，当前由可信调用方
    从已保存记录取得；content 允许必要规范化，不要求是原文子串。
    """

    source: MemorySource
    content: str
    proposed_route: CandidateRoute
    reason: str


def validate_candidate_shapes(
    scope: MemoryScope, candidate: MemoryCandidate,
) -> None:
    """助手准备：仅检查格式，范围相等和角色准入由核心函数核对。"""
    if not isinstance(scope, MemoryScope) or not isinstance(candidate, MemoryCandidate):
        raise MemoryPolicyError("scope/候选必须使用约定的数据容器")
    source = candidate.source
    if not isinstance(source, MemorySource) or not isinstance(source.scope, MemoryScope):
        raise MemoryPolicyError("来源及其范围必须使用约定的数据容器")
    for item in (scope, source.scope):
        require_text(item.user_id, "user_id")
        require_text(item.project_id, "project_id")
    require_text(source.source_id, "来源编号")
    require_text(source.role, "来源角色")
    require_text(source.text, "来源原文")
    normalize_time(source.recorded_at)
    require_text(candidate.content, "候选正文")
    require_text(candidate.reason, "候选选择理由")
    if not isinstance(candidate.proposed_route, str) or candidate.proposed_route not in _ROUTES:
        raise MemoryPolicyError("候选建议去向不受支持")


def validate_candidate_source(
    scope: MemoryScope,candidate: MemoryCandidate,
) -> None:
    """核对来源范围和角色，不判断正文语义或执行写入"""
    validate_candidate_shapes(scope,candidate)
    source = candidate.source
    if source.scope != scope:
        raise MemoryPolicyError("来源不属于当前用户或项目")
    if source.role not in {"user","tool"}:
        raise MemoryPolicyError("只接收用户陈述或工具观察作为候选来源")


def checked_candidate_batch(
    scope: MemoryScope,
    candidates: list[MemoryCandidate] | tuple[MemoryCandidate, ...],
) -> tuple[MemoryCandidate, ...]:
    """助手准备：检查批次外壳并快照；逐条来源准入由核心执行。

    空批次仍检查可信 Scope。仅接受 list/tuple，不隐式消费生成器；
    输出保留输入次序和对象，不检查或授予候选语义、去向与写入许可。
    """
    if not isinstance(scope, MemoryScope):
        raise MemoryPolicyError("scope 必须使用 MemoryScope")
    require_text(scope.user_id, "user_id")
    require_text(scope.project_id, "project_id")
    if not isinstance(candidates, (list, tuple)):
        raise MemoryPolicyError("候选批次必须为列表或元组")
    return tuple(candidates)


def route_candidates(
    scope: MemoryScope,
    candidates: list[MemoryCandidate] | tuple[MemoryCandidate, ...],
) -> dict[CandidateRoute, tuple[MemoryCandidate, ...]]:
    """按建议去向归组；不判断长期价值，不执行分流出口或写入操作。"""
    candidates = checked_candidate_batch(scope,candidates)
    groups = {route:[] for route in _ROUTES}

    for candidate in candidates:
        validate_candidate_source(scope,candidate)
        groups[candidate.proposed_route].append(candidate)

    return {
        route:tuple(items)
        for route,items in groups.items()
        }
