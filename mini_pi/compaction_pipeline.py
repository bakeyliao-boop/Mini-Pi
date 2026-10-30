"""D17：候选压缩结果的单次准备；不写会话、不调用回答模型。"""

import asyncio
from copy import deepcopy
from dataclasses import dataclass

from mini_pi.compaction import (
    build_compacted_history, build_compacted_request, choose_cut, generate_summary, split_for_summary,
)
from mini_pi.compaction_binding import CompactionBinding, make_compaction_binding
from mini_pi.context import ContextParts, ContextProvider, check_compacted_request, check_request_chars
from mini_pi.context_budget import check_estimated_window
from mini_pi.context_size import InputSizeEstimate
from mini_pi.models import ConversationItem, Message
from mini_pi.run_deadline import await_before_deadline


@dataclass
class CompactionCandidate:
    """仅用于当前会话的候选结果；下标不能当作跨会话持久身份。"""

    cut_index: int
    summary: str
    messages: list[ConversationItem]
    summary_estimate: InputSizeEstimate
    request_estimate: InputSizeEstimate
    binding: CompactionBinding

async def prepare_compaction_candidate(
    history, references, tools,  # 原始历史、本轮资料和回答模型的工具定义
    summary_provider, item_estimator, request_estimator,  # 摘要模型与两种估算方法
    summary_window, answer_window, call_budget,  # 两次请求的窗口和摘要调用次数
    keep_recent_tokens, max_context_chars, *, session_id, answer_context, deadline=None,  # 固定会话编号与总时限
):
    history_snapshot = deepcopy(history)  # 固定本次历史
    reference_snapshot = deepcopy(references)  # 固定本轮资料
    tool_snapshot = deepcopy(tools)  # 固定回答模型的工具定义

    if (
        not isinstance(answer_context, ContextProvider)
        or answer_context._window_budget is None
        or answer_context._window_budget != answer_window
    ):
        raise ValueError("候选请求必须使用回答入口的窗口预算")
    if not isinstance(reference_snapshot,list) or any(
        not isinstance(item,Message) or item.role != 'user' or item.tool_calls
        for item in reference_snapshot
    ):
        raise ValueError("参考消息必须是用户消息且不包含工具调用")
    if reference_snapshot and max_context_chars is None:
        raise ValueError("参考消息存在时必须提供字符上限")

    await await_before_deadline(
        lambda: asyncio.sleep(0), deadline  # 先响应取消并检查时限
    )
    cut = choose_cut(history_snapshot, keep_recent_tokens, item_estimator)  # 寻找安全切点
    await await_before_deadline(
        lambda: asyncio.sleep(0), deadline  # 切点计算后再检查时限
    )
    if cut is None:  # 没有可以使用的切点
        return None  # 不请求摘要模型

    binding = make_compaction_binding(session_id, history_snapshot, cut)  # 请求摘要前绑定同一份历史
    system, old, recent = split_for_summary(history_snapshot, cut)  # 分出三部分
    summary, summary_estimate = await generate_summary(
        old, summary_provider, request_estimator, summary_window, call_budget,
        deadline=deadline,  # 摘要调用使用同一次运行的总时限
    )

    compacted_history = build_compacted_history(system,summary,recent)
    messages,tool_snapshot,request_estimate = await answer_context.prepare_for_compaction(
        ContextParts(compacted_history,reference_snapshot),tool_snapshot,
        deadline=deadline,  # 压缩请求使用同一次运行的总时限
    )

    if max_context_chars is not None:
        check_request_chars(messages,max_context_chars)
    check_estimated_window(
        request_estimate.estimated_input_tokens,
        answer_window.reserved_output_tokens,
        answer_window.context_window_tokens,
        answer_window.safety_margin_tokens,
    )

    await await_before_deadline(
        lambda: asyncio.sleep(0), deadline  # 检查结束后再确认时限
    )
    return CompactionCandidate(
        cut, summary, messages, summary_estimate, request_estimate,
        binding=binding,  # 同时带上来源标签
    )
