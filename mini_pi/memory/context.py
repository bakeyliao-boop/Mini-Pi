"""MEM-04：组装每轮独立请求消息；核心由学习者分段敲入并接入run_loop。"""

from mini_pi.memory.context_helpers import (
    checked_context_inputs, encode_context_material, messages_char_count,
)
from mini_pi.memory.errors import MemoryContextError
from mini_pi.memory.models import Conditions, MemoryHit, MemoryScope
from mini_pi.memory.retrieval import is_usable
from mini_pi.memory.retrieval_helpers import normalize_read_request
from mini_pi.memory.selection import MemoryCandidate, validate_candidate_source
from mini_pi.memory.store import MemoryStore
from mini_pi.models import ConversationItem, Message


def build_context(
    store: MemoryStore,
    scope: MemoryScope,
    hits: list[MemoryHit] | tuple[MemoryHit, ...],
    recent_messages: list[ConversationItem] | tuple[ConversationItem, ...],
    *,
    task_material: list[MemoryCandidate] | tuple[MemoryCandidate, ...] = (),
    at: str,
    conditions: Conditions = (),
    max_context_chars: int,
) -> list[ConversationItem]:
    """完整近期消息加已确认同任务材料及适用记忆，输出独立请求快照。

    Scope、问题时间、条件和任务归属由可信调用方明确。此处不执行
    search/模型/写库；也不把候选标签当作同任务、事实成立或执行许可。
    首单元不裁剪；messages字符上限是本地限制，不是模型token保证。
    """
    conditions, at = normalize_read_request(scope, conditions, at)  # 助手准备：统一格式，复用已有辅助。
    hits, task_material, recent_messages = checked_context_inputs(
        hits, task_material, recent_messages, max_context_chars,
    )  # 助手准备：格式与完整工具组检查，并深复制近期消息。
    for candidate in task_material:  ## 逐条核对调用方选定的当前任务材料
        validate_candidate_source(scope,candidate)
        if candidate.proposed_route not in ("task_constraint","needs_review"):
            raise MemoryContextError("任务材料只能是任务相关或待核对候选")

    usable = []  # 保存本次仍可使用的长期记忆
    for hit in hits:
        entry = hit.entry
        if entry.scope != scope:
            raise MemoryContextError("检索命中不属于当前范围")

        current = store.get(scope,entry.memory_id)
        if current is None:
            raise MemoryContextError("检索命中的主记录不存在")

        if (
            current.source != entry.source
            or current.draft != entry.draft
            or current.version != entry.version
            or current.written_at != entry.written_at
            ):
                raise MemoryContextError("检索命中的定义发生变化")

        if not is_usable(current,scope,conditions=conditions,at=at):
            continue
        usable.append(current)

    request_messages = recent_messages
    if task_material or usable:  #“当前任务材料”或“可用长期记忆”是否有内容
        material = Message("user",encode_context_material(at,task_material,usable))
        insert_at = 0
        while(
            insert_at < len(request_messages)
            and isinstance(request_messages[insert_at],Message)
            and request_messages[insert_at].role == "system"
            ):
            insert_at += 1
        request_messages.insert(insert_at, material)  # 在system之后插入资料，保留其余消息顺序

    if messages_char_count(request_messages) > max_context_chars:
        raise MemoryContextError("请求消息超过字符预算")
    return request_messages
