"""D17：摘要压缩相关逻辑；核心判断由学习者分段实现。"""

import asyncio
from copy import deepcopy

from mini_pi.context_budget import ContextWindowBudget, check_estimated_window
from mini_pi.context_size import InputSizeEstimate
from mini_pi.memory.context import add_reference_messages
from mini_pi.memory.context_helpers import check_complete_messages
from mini_pi.memory.errors import MemoryContextError
from mini_pi.models import Message
from mini_pi.run_deadline import await_before_deadline
from mini_pi.summary_call_budget import SummaryCallBudget
from mini_pi.summary_codec import encode_summary_history  # 将旧记录编码为摘要资料


class SummaryError(RuntimeError):
    """摘要结果不可采用。"""


class SummaryAborted(RuntimeError):
    """摘要模型返回中止；接入运行流程时需保留取消语义。"""

def is_safe_cut(history,cut_index):
    if type(cut_index) is not int or not 0 < cut_index < len(history):
        raise ValueError("切点必须在范围内")

    check_complete_messages(history)

    old = history[:cut_index]
    recent = history[cut_index:]

    if not any(
        not isinstance(item,Message) or item.role != "system"
        for item in old
        ):
        return False
    try:
        check_complete_messages(old)
        check_complete_messages(recent)
    except MemoryContextError:
        return False

    return True

def find_safe_cut(history, preferred_index):
    if type(preferred_index) is not int or not 0 < preferred_index < len(history):  # 期望位置必须在历史内部
        raise ValueError("期望切点必须在历史内部")

    check_complete_messages(history)  # 历史本身有未完成调用时，直接停止

    for index in range(preferred_index, 0, -1):  # 从期望位置开始，逐个向前检查
        if is_safe_cut(history, index):  # 复用刚才完成的安全判断
            return index  # 返回找到的第一个安全切点

    return None  # 找不到切点时，不进行压缩

def choose_cut(history,keep_recent_tokens,estimate_item):
    if type(keep_recent_tokens) is not int or keep_recent_tokens <= 0:
        raise ValueError("近期保留目标必须是正整数")
    if not callable(estimate_item):
        raise ValueError("estimate_item必须可以调用")

    check_complete_messages(history)
    total = 0

    for index in range(len(history)-1,-1,-1):
        item = history[index]
        if isinstance(item,Message) and item.role == "system":
            break

        size = estimate_item(deepcopy(item))  # 避免估算回调修改原始记录
        if type(size) is not int or size < 0:
            raise ValueError("估算大小估算必须是非负整数")

        total += size
        if total >= keep_recent_tokens:
            if index == 0:
                return None
            return find_safe_cut(history,index)
    return None

def split_for_summary(history,cut_index):
    snapshot = deepcopy(history)
    if not is_safe_cut(snapshot,cut_index):
        raise ValueError("切点不安全")

    system_end = 0
    while(
        system_end < cut_index
        and isinstance(snapshot[system_end],Message)
        and snapshot[system_end].role == "system"
        ):
        system_end += 1

    system_messages = snapshot[:system_end]
    old = snapshot[system_end:cut_index]
    recent = snapshot[cut_index:]
    return system_messages,old,recent

def check_summary_response(response):
    if not isinstance(response, Message):  # 摘要模型必须返回消息
        raise SummaryError("摘要响应格式不正确")
    if response.stop_reason == "aborted":  # 模型报告中止
        raise SummaryAborted("摘要生成已中止")
    if response.stop_reason != "stop":  # 只接受明确正常结束；截断和错误都不能采用
        raise SummaryError("摘要未正常完成")
    if response.role != "assistant" or response.tool_calls:  # 摘要应是助手文本，不执行工具
        raise SummaryError("摘要响应必须是不带工具调用的助手消息")
    if not isinstance(response.content, str) or not response.content.strip():  # 空白摘要不能采用
        raise SummaryError("摘要内容不能为空")

    return response.content  # 检查通过，返回候选摘要文字

def build_summary_request(old_history):
    if not isinstance(old_history,list) or not old_history:
        raise ValueError("待摘要历史必须是非空列表")

    snapshot = deepcopy(old_history)
    check_complete_messages(snapshot)
    if any(
        isinstance(item,Message) and item.role == "system"
        for item in snapshot
        ):
            raise ValueError("待摘要历史不能包括system消息")
    instruction = (
        "请根据提供的会话记录生成摘要，保留目标、约束、操作、"
        "验证结果和待办。区分用户要求、工具观察和未确认的推测；"
        "不要把建议写成已经完成的操作"
        )
    material = encode_summary_history(snapshot)

    return [
        Message("system",instruction),
        Message("user",material),
        ]

def check_summary_budget(request_messages, estimator, budget):
    if not callable(estimator):  # 必须提供请求大小估算方法
        raise ValueError("摘要估算器必须可以调用")
    if not isinstance(budget, ContextWindowBudget):  # 必须提供摘要请求的窗口配置
        raise ValueError("摘要窗口预算配置不正确")

    snapshot = deepcopy(request_messages)  # 估算器只接触副本
    check_complete_messages(snapshot)  # 检查摘要请求的消息结构
    estimate = estimator(snapshot, [])  # 估算完整摘要请求；摘要不使用工具

    if not isinstance(estimate, InputSizeEstimate):  # 估算器必须返回约定的结果
        raise ValueError("摘要估算结果格式不正确")

    check_estimated_window(
        estimate.estimated_input_tokens,  # 摘要请求的输入估算量
        budget.reserved_output_tokens,  # 为摘要输出预留的空间
        budget.context_window_tokens,  # 摘要模型的窗口大小
        budget.safety_margin_tokens,  # 估算误差的额外余量
    )
    return estimate  # 通过检查后，保留估算结果

def prepare_summary_call(old_history, provider, estimator, window_budget):
    request = build_summary_request(old_history)  # 组装摘要请求
    estimate = check_summary_budget(request, estimator, window_budget)  # 检查窗口空间

    output_limit = getattr(provider, "max_completion_tokens", None)  # 读取模型配置的输出上限
    if type(output_limit) is not int or output_limit <= 0:  # 模型必须明确给出正整数上限
        raise ValueError("摘要模型必须提供正整数输出上限")
    if output_limit > window_budget.reserved_output_tokens:  # 实际上限不能超过预留空间
        raise ValueError("摘要模型输出上限不能超过预留空间")

    return request, estimate  # 返回准备好的请求和估算结果

async def generate_summary(
    old_history,provider,estimator,window_budget,call_budget,*,deadline=None
    ):
    if not isinstance(call_budget,SummaryCallBudget):
        raise ValueError("摘要调用预算配置不正确")
    if not callable(getattr(provider,"generate",None)):
        raise ValueError("摘要模型必须可以生成响应")

    await await_before_deadline(
        lambda: asyncio.sleep(0),deadline
        )
    request,estimate = prepare_summary_call(
        old_history,provider,estimator,window_budget
        )

    async def start_request():
        call_budget.take()
        return await provider.generate(request,[])

    response = await await_before_deadline(
        start_request,deadline
        )
    await await_before_deadline(
        lambda: asyncio.sleep(0),deadline
        )
    summary = check_summary_response(response)
    return summary,estimate

def build_compacted_history(system_messages, summary, recent):
    if not isinstance(system_messages, list):  # 系统消息必须是列表
        raise ValueError("系统消息必须是列表")
    if any(
        not isinstance(item, Message) or item.role != "system"  # 每条都必须是 system 消息
        for item in system_messages
    ):
        raise ValueError("系统消息格式不正确")
    if not isinstance(summary, str) or not summary.strip():  # 摘要不能为空
        raise ValueError("摘要内容不能为空")
    if not isinstance(recent, list) or not recent:  # 必须保留近期记录
        raise ValueError("近期记录必须是非空列表")

    messages = deepcopy(system_messages)  # 保留系统消息的独立副本
    messages.append(Message("user", "以下是旧会话摘要，供继续任务参考：\n" + summary))  # 标明摘要来源
    messages.extend(deepcopy(recent))  # 在摘要后加入近期原文
    check_complete_messages(messages)  # 检查组装后的工具调用与结果
    return messages  # 返回候选请求历史

def build_compacted_request(system_messages, summary, recent, references):
    if not isinstance(references, list):  # 本轮资料必须是列表
        raise ValueError("参考资料必须是列表")
    if any(
        not isinstance(item, Message)  # 每条资料必须是消息
        or item.role != "user"  # 本阶段资料使用 user 形式
        or item.tool_calls  # 资料不能包含工具调用
        for item in references
    ):
        raise ValueError("参考资料格式不正确")

    messages = build_compacted_history(system_messages, summary, recent)  # 先组装摘要和近期记录
    messages = add_reference_messages(messages, deepcopy(references))  # 再加入本轮资料
    check_complete_messages(messages)  # 检查最终候选消息的工具配对
    return messages  # 返回完整候选消息
