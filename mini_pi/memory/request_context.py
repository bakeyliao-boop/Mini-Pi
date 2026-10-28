"""MEM-04请求准备：连接检索与组装，供run_loop每轮调用；核心由学习者手敲。"""

import asyncio

from mini_pi.memory.context import build_context
from mini_pi.memory.context_helpers import checked_context_inputs
from mini_pi.memory.embedding import Embedder
from mini_pi.memory.models import Conditions, MemoryScope
from mini_pi.memory.selection import MemoryCandidate
from mini_pi.memory.store import MemoryStore
from mini_pi.models import ConversationItem


async def prepare_context(
    store: MemoryStore,
    scope: MemoryScope,
    query: str,
    recent_messages: list[ConversationItem] | tuple[ConversationItem, ...],
    *,
    embedder: Embedder,
    task_material: list[MemoryCandidate] | tuple[MemoryCandidate, ...] = (),
    at: str,
    conditions: Conditions = (),
    top_k: int,
    min_score: float,
    max_context_chars: int,
    reference_only:bool = False,
) -> list[ConversationItem]:
    """可信调用方给出本次query和适用背景，返回本次独立请求消息。

    query暂由调用方明确，不自动从工具输出生成；不调用回答模型或写入。
    异常/取消向上传播，由后续loop接线处理结束记录和总时限。
    本地同步读取及组装不是硬实时可抢占操作。
    """
    await asyncio.sleep(0)  # 先响应已经到达的取消，避免继续启动检索
    _, task_material, recent_messages = checked_context_inputs(  # _接收本步不用的空命中集合
        (), task_material, recent_messages, max_context_chars,  # 复用格式检查，提前快照任务材料并深复制近期消息
    )  # 快照固定本次输入，避免等待检索时原消息发生变化

    hits = await store.search(  # 等待已有向量检索完成；错误和取消直接向上传播
        scope, query,  # 可信范围与自然语言问题分别传入
        at=at, embedder=embedder, conditions=conditions,  # 保持同一问题时间、模型和适用条件
        top_k=top_k, min_score=min_score,  # 使用调用方明确提供的数量和阈值
    )  # 此处只获得命中，尚未调用回答模型

    await asyncio.sleep(0)  # 检索返回时若已请求取消，就不再继续组装
    return build_context(  # 复用刚验收的主记录复核、资料插入和预算检查
        store, scope, hits, recent_messages,  # 使用检索结果与本次消息快照
        task_material=task_material, at=at, conditions=conditions,  # 任务材料和适用背景保持一致
        max_context_chars=max_context_chars,  # 超预算由组装层明确报错
        reference_only=reference_only,
    )  # 返回独立请求消息，后续再接入run_loop
