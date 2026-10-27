"""MEM-W：执行已由可信调用方确认的计划；不提取候选或重新规划。"""

from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.models import MemoryEntry, MemoryScope
from mini_pi.memory.planning import RememberPlan, ReplacePlan, RetractPlan
from mini_pi.memory.store import MemoryStore
from mini_pi.memory.validation_helpers import require_text


ExecutionItem = MemoryEntry | RememberPlan | ReplacePlan | RetractPlan


def checked_execution_batch(
    scope: MemoryScope,
    items: list[ExecutionItem] | tuple[ExecutionItem, ...],
) -> tuple[ExecutionItem, ...]:
    """助手准备：只核对批次外壳并快照，逐项准入与数量限制由核心决定。"""
    if not isinstance(scope, MemoryScope):
        raise MemoryPolicyError("scope 必须使用 MemoryScope")
    require_text(scope.user_id, "user_id")
    require_text(scope.project_id, "project_id")
    if not isinstance(items, (list, tuple)):
        raise MemoryPolicyError("执行批次必须为列表或元组")
    return tuple(items)


def execute_plans(
    store: MemoryStore,
    scope: MemoryScope,
    items: list[ExecutionItem] | tuple[ExecutionItem, ...],
) -> tuple[MemoryEntry, ...]:
    """整批预检后最多执行一个变更计划；已有Entry只作为结果快照返回。

    多计划含重复同一计划也拒绝；单个Store操作自行保证事务、回执与CAS。
    执行原计划，不刷新版本或重新判断意图；异常保留，不冒称成功或零写入。
    """
    items = checked_execution_batch(scope,items)
    write_count = 0

    for item in items:
        if not isinstance(item,(MemoryEntry,RememberPlan,ReplacePlan,RetractPlan)):
            raise MemoryPolicyError("执行项必须是已存结果或明确计划")
        if item.scope != scope:
            raise MemoryPolicyError("执行项不属于当前用户或项目")
        if not isinstance(item,MemoryEntry):
            write_count += 1

    if write_count > 1:
        raise MemoryPolicyError("当前批次最多支持一个变更计划")

    results = []

    for item in items:
        if isinstance(item,MemoryEntry):
            result = item
        elif isinstance(item,RememberPlan):
            result = store.remember(
                item.scope,item.source,item.draft,
                )
        elif isinstance(item,ReplacePlan):
            result = store.replace(
                item.scope,item.source,item.draft,
                expected_version=item.expected_version,
                operation_id=item.operation_id,
                )
        else:
            result = store.retract(
                item.scope,item.source,item.key,
                conditions=item.conditions,
                expected_version=item.expected_version,
                operation_id=item.operation_id,
            )
        results.append(result)

    return tuple(results)
