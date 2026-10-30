"""D17：准备摘要记录，不执行会话写入。"""

from copy import deepcopy
from dataclasses import asdict
from mini_pi.compaction import build_compacted_history, split_for_summary
from mini_pi.context import ContextParts, ContextProvider, check_request_chars
from mini_pi.context_budget import ContextWindowBudget, check_estimated_window
from mini_pi.compaction_binding import check_before_compaction_save
from mini_pi.compaction_pipeline import CompactionCandidate
from mini_pi.models import Message
from mini_pi.session_records import check_compaction_data

def make_compaction_record(loaded, candidate):
    if not isinstance(candidate, CompactionCandidate):  # 必须是候选摘要结果
        raise ValueError("摘要候选结果格式不正确")

    snapshot = deepcopy(candidate)  # 固定本次要整理的候选结果
    check_before_compaction_save(loaded, snapshot.binding)  # 核对会话、历史和切点
    if snapshot.cut_index != snapshot.binding.cut_index:  # 候选结果与标签必须指向同一切点
        raise ValueError("候选切点与摘要标签不一致")

    data = asdict(snapshot.binding)  # 将来源标签转换成字典
    data["summary"] = snapshot.summary  # 加入摘要文字
    check_compaction_data(data)  # 检查待保存记录的格式
    return data  # 返回待保存内容；这里不写文件

async def check_candidate_before_save(
    loaded, candidate, references, tools, answer_context, answer_window, max_context_chars, *, deadline=None
):
    if (not isinstance(answer_context, ContextProvider) or answer_context._window_budget is None
            or answer_context._window_budget != answer_window):
        raise ValueError("候选请求必须使用回答入口的窗口预算")

    session_snapshot = deepcopy(loaded)  # 固定当前加载的会话
    candidate_snapshot = deepcopy(candidate)  # 固定候选摘要及请求
    reference_snapshot = deepcopy(references)  # 固定本轮参考资料
    tool_snapshot = deepcopy(tools)  # 固定回答模型的工具定义

    if not isinstance(reference_snapshot,list) or any(
        not isinstance(item,Message) or item.role != 'user' or item.tool_calls
        for item in reference_snapshot
    ):
        raise ValueError("参考消息必须是用户消息且不包含工具调用")
    if reference_snapshot and max_context_chars is None:
        raise ValueError("参考消息存在时必须提供字符上限")

    data = make_compaction_record(session_snapshot, candidate_snapshot)  # 核对来源并准备记录
    system, _, recent = split_for_summary(
        session_snapshot.history, candidate_snapshot.binding.cut_index  # 从当前历史重新分组
    )
    history = build_compacted_history(system, candidate_snapshot.summary, recent)
    expected, tool_snapshot, estimate = await answer_context.prepare_for_compaction(
        ContextParts(history, reference_snapshot), tool_snapshot, deadline=deadline  # 裁剪长结果，再加入资料
    )
    if expected != candidate_snapshot.messages:  # 候选消息与重新组装的内容不一致
        raise ValueError("候选请求已变化，需要重新准备摘要")
    if max_context_chars is not None:
        check_request_chars(expected, max_context_chars)  # 检查完整消息的字符上限

    budget = answer_context._window_budget  # 与实际回答使用同一预算
    check_estimated_window(
        estimate.estimated_input_tokens,
        budget.reserved_output_tokens,
        budget.context_window_tokens,
        budget.safety_margin_tokens,
    )
    return data, estimate  # 返回待保存记录和最新估算

def check_answer_output_limit(provider, answer_window):
    if not isinstance(answer_window, ContextWindowBudget):  # 必须提供回答窗口配置
        raise ValueError("回答窗口预算配置不正确")

    output_limit = getattr(provider, "max_completion_tokens", None)  # 读取回答模型的输出上限
    if type(output_limit) is not int or output_limit <= 0:  # 上限必须是明确的正整数
        raise ValueError("回答模型必须提供正整数输出上限")
    if output_limit > answer_window.reserved_output_tokens:  # 实际上限不能超过预留
        raise ValueError("回答模型输出上限不能超过预留空间")
