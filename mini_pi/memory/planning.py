"""MEM-W：从已核对的来源和字段形成计划；规划不执行持久变更。"""

from dataclasses import dataclass

from mini_pi.memory.codec import candidate_id, normalize_draft, normalize_source
from mini_pi.memory.errors import MemoryConflict, MemoryPolicyError
from mini_pi.memory.models import Conditions, MemoryDraft, MemoryEntry, MemoryScope, MemorySource
from mini_pi.memory.policy import validate_draft
from mini_pi.memory.store import MemoryStore
from mini_pi.memory.validation_helpers import normalize_conditions, require_text


@dataclass(frozen=True)
class RememberPlan:
    """助手准备：一次首次新增的完整输入；容器不校验语义或自动提交。"""

    scope: MemoryScope
    source: MemorySource
    draft: MemoryDraft


def plan_remember(
    store: MemoryStore,
    scope: MemoryScope,
    source: MemorySource,
    draft: MemoryDraft,
) -> RememberPlan:
    """只规划首次新增；已有系列停止本分支，重复/更新/撤回另行处理。"""
    validate_draft(scope,source,draft)
    source = normalize_source(source)
    draft = normalize_draft(draft)

    latest = store.latest(scope,draft.key,conditions=draft.conditions)
    if latest is not None:
        raise MemoryConflict("该系列已有记忆，需要判断重复、更新或者撤回")

    return RememberPlan(scope,source,draft)

def find_retry(
    store:MemoryStore,
    scope:MemoryScope,
    source:MemorySource,
    draft:MemoryDraft,
    )->MemoryEntry | None:
    """只读识别同候选重试，保存已留状态"""
    validate_draft(scope,source,draft)
    source = normalize_source(source)
    draft = normalize_draft(draft)

    memory_id = candidate_id(scope,source,draft)
    existing = store.get(scope,memory_id)  #按用户、项目范围和记忆 ID，从数据库读取一条记录。
    if existing is None:
        return None

    if existing.source != source or existing.draft != draft:
        raise MemoryConflict("同一候选的来源或定义发生变化")

    return existing


def plan_remember_or_retry(
    store: MemoryStore,
    scope: MemoryScope,
    source: MemorySource,
    draft: MemoryDraft,
) -> MemoryEntry | RememberPlan:
    """先识别同候选重试，再规划首次新增；不执行写入或自动更新。"""
    existing = find_retry(store,scope,source,draft)
    if existing is not None:
        return existing

    return plan_remember(store,scope,source,draft)


@dataclass(frozen=True)
class ReplacePlan:
    """助手准备：首次更新的完整请求；执行重试须复用原版本和操作编号。"""

    scope: MemoryScope
    source: MemorySource
    draft: MemoryDraft
    expected_version: int
    operation_id: str


def plan_replace(
    store: MemoryStore,
    scope: MemoryScope,
    source: MemorySource,
    draft: MemoryDraft,
    *,
    operation_id: str,
) -> ReplacePlan:
    """只规划首次显式更新；已有操作重试直接执行原计划，不重新规划。"""
    validate_draft(scope,source,draft)
    require_text(operation_id,"operation_id")
    source = normalize_source(source)
    draft = normalize_draft(draft)

    latest = store.latest(scope,draft.key,conditions=draft.conditions)
    if latest is None or latest.state != "active":
        raise MemoryConflict("目标系列不存在或者不允许更新")
    if latest.draft.kind != draft.kind:
        raise MemoryConflict("更新不能改变记忆类型")
    if draft.valid_from <= latest.draft.valid_from:
        raise MemoryConflict("新版生效时间必须更晚")

    return ReplacePlan(
        scope,source,draft,latest.version,operation_id,
          )


@dataclass(frozen=True)
class RetractPlan:
    """助手准备：一次明确撤回的完整请求；重试复用原计划，不重新规划。"""

    scope: MemoryScope
    source: MemorySource
    key: str
    conditions: Conditions
    expected_version: int
    operation_id: str


def normalize_retract_request(
    scope: MemoryScope,
    source: MemorySource,
    key: str,
    conditions: Conditions,
    operation_id: str,
) -> tuple[MemorySource, Conditions]:
    """助手准备：仅检查格式并规范化，不判断范围相等、角色或撤回意图。"""
    if not isinstance(scope, MemoryScope):
        raise MemoryPolicyError("scope 必须使用 MemoryScope")
    require_text(scope.user_id, "user_id")
    require_text(scope.project_id, "project_id")
    source = normalize_source(source)
    require_text(source.text, "撤回指令原文")
    require_text(key, "记忆属性名")
    require_text(operation_id, "operation_id")
    return source, normalize_conditions(conditions)


def plan_retract(
    store: MemoryStore,
    scope: MemoryScope,
    source: MemorySource,
    key: str,
    *,
    conditions: Conditions = (),
    operation_id: str,
) -> RetractPlan:
    """只规划已由上层确认意图与目标的首次撤回，不执行持久变更。"""
    source,conditions = normalize_retract_request(
        scope,source,key,conditions,operation_id,
        )
    if source.scope != scope:
        raise MemoryPolicyError("撤回指令不属于当前项目或用户")
    if source.role != "user":
        raise MemoryPolicyError("只接收原用户撤回指令")

    latest = store.latest(scope,key,conditions=conditions)
    if latest is None or latest.state != "active":
        raise MemoryConflict("目标系列不存在或不允许首次撤回")

    return RetractPlan(
        scope,source,key,conditions,latest.version,operation_id,
        )
