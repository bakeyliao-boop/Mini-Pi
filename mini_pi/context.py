"""D13-D：请求上下文接口；保留完整历史，核心转交逻辑由学习者手敲。"""

import asyncio
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol

from mini_pi.context_budget import ContextWindowBudget, check_estimated_window
from mini_pi.context_output import shorten_read_result
from mini_pi.context_size import InputSizeEstimate
from mini_pi.memory.context import add_reference_messages
from mini_pi.memory.context_helpers import check_complete_messages, messages_char_count
from mini_pi.memory.errors import MemoryContextError
from mini_pi.models import ConversationItem, Message, ToolDefinition, ToolResult
from mini_pi.provider import ModelProvider
from mini_pi.run_deadline import await_before_deadline


@dataclass
class ContextParts:
    history:list[ConversationItem]
    references:list[Message]

class ContextBuilder(Protocol):
    async def build(self, history: Sequence[ConversationItem]) -> list[ConversationItem]:
        """从历史副本组装本次请求消息；不得执行历史工具调用。"""
        ...


async def build_separate_context(builder: ContextBuilder, parts: ContextParts):
    snapshot = deepcopy(parts)  # 隔离历史和本轮资料
    history_messages = await builder.build(snapshot.history)  # 构建器只接收历史
    history_messages = deepcopy(list(history_messages))  # 隔离构建结果
    return add_reference_messages(history_messages, snapshot.references)  # 最后加入资料

def check_request_chars(messages,max_context_chars):
    if type(max_context_chars) is not int or max_context_chars <= 0:
        raise MemoryContextError("字符上限必须是正整数")
    if messages_char_count(messages) > max_context_chars:
        raise MemoryContextError("请求消息超过字符预算")

def check_compacted_request(messages, tools, estimator, budget, max_context_chars):
    if not callable(estimator):  # 必须提供完整请求的估算方法
        raise ValueError("请求估算器必须可以调用")
    if not isinstance(budget, ContextWindowBudget):  # 必须提供回答模型的窗口预算
        raise ValueError("请求窗口预算配置不正确")

    message_snapshot = deepcopy(messages)  # 复制完整候选消息
    tool_snapshot = deepcopy(tools)  # 复制本次工具定义
    check_complete_messages(message_snapshot)  # 检查工具调用与结果配对
    if max_context_chars is not None:
        check_request_chars(message_snapshot, max_context_chars)  # 检查完整消息的字符上限

    estimate = estimator(message_snapshot, tool_snapshot)  # 估算消息和工具定义
    if not isinstance(estimate, InputSizeEstimate):  # 确认估算结果格式
        raise ValueError("请求估算结果格式不正确")

    check_estimated_window(
        estimate.estimated_input_tokens,  # 完整请求的输入估算量
        budget.reserved_output_tokens,  # 为回答预留的空间
        budget.context_window_tokens,  # 回答模型的窗口大小
        budget.safety_margin_tokens,  # 估算误差的额外余量
    )
    return estimate  # 返回通过检查的估算结果

class FullHistoryContext:
    async def build(self, history: Sequence[ConversationItem]) -> list[ConversationItem]:
        """首版保留所有消息；筛选与裁剪留到后续章节。"""
        return list(history)

class ReadOutputContext:
    def __init__(self,max_output_chars:int):
        if type(max_output_chars) is not int or max_output_chars <= 0:  # 拒绝非正整数，包括布尔值
            raise ValueError("max_output_chars必须是正整数")  # 配置错误立即暴露
        self._max_output_chars = max_output_chars  # 保存配置，供每轮build复用

    async def build(self,history:Sequence[ConversationItem])->list[ConversationItem]:
        snapshot = deepcopy(list(history))
        check_complete_messages(snapshot)
        for index,item in enumerate(snapshot):
            if isinstance(item,ToolResult):
                snapshot[index] = shorten_read_result(
                    item,self._max_output_chars,
                    )
        check_complete_messages(snapshot)
        return snapshot

class ContextProvider:
    def __init__(
        self,
        provider: ModelProvider,
        builder: ContextBuilder,
        *,
        input_estimator: Callable[[Sequence[ConversationItem], Sequence[ToolDefinition]], InputSizeEstimate] | None = None,
        window_budget: ContextWindowBudget | None = None,
    ):
        """保存组装、估算与预算配置，构造时不启动请求。"""
        if (input_estimator is None) != (window_budget is None):
            raise ValueError("估算器与窗口预算必须同时配置")
        if input_estimator is not None and not callable(input_estimator):
            raise ValueError('input_estimator必须可以调用')
        if window_budget is not None:
            check_estimated_window(
                0,window_budget.reserved_output_tokens,
                window_budget.context_window_tokens,window_budget.safety_margin_tokens,
                )
        self._provider = provider  # 保存实际模型
        self._builder = builder  # 保存构建器
        self._input_estimator = input_estimator  # 保存估算器
        self._window_budget = window_budget  # 保存预算
        self.last_estimate: InputSizeEstimate | None = None  # 最近一次估算记录

    async def prepare_for_compaction(self, parts, tools, *, deadline=None):
        if not isinstance(parts, ContextParts):  # 统一接收历史和参考资料
            raise ValueError("请求内容必须是 ContextParts")
        if self._window_budget is None:  # 需要已配置的窗口预算和估算器
            raise ValueError("压缩准备必须配置窗口预算")

        self.last_estimate = None  # 清除上次估算
        parts_snapshot = deepcopy(parts)  # 固定历史和本轮资料
        tool_snapshot = deepcopy(list(tools))  # 固定工具定义

        messages = await await_before_deadline(
            lambda: build_separate_context(self._builder, parts_snapshot),  # 整理历史并加入资料
            deadline,  # 使用本次运行的总时限
        )
        await await_before_deadline(
            lambda: asyncio.sleep(0), deadline  # 整理结束后检查取消和时限
        )
        check_complete_messages(messages)  # 检查工具调用和结果配对

        size = self._input_estimator(
            deepcopy(messages), deepcopy(tool_snapshot)  # 估算完整消息和工具定义
        )
        if not isinstance(size, InputSizeEstimate):  # 检查估算结果
            raise ValueError("请求估算结果格式不正确")

        self.last_estimate = size  # 保存本次估算
        await await_before_deadline(
            lambda: asyncio.sleep(0), deadline  # 估算结束后再检查取消和时限
        )
        return messages, tool_snapshot, size  # 返回完整请求和估算，不发送

    async def send_prepared(self,messages,tools,*,deadline=None,max_context_chars=None):
        if self._window_budget is None:
            raise ValueError('发送准备好的请求必须配置窗口预算')

        self.last_estimate = None
        message_snapshot = deepcopy(list(messages))
        tool_snapshot =  deepcopy(list(tools))

        await await_before_deadline(
            lambda: asyncio.sleep(0),deadline
            )
        check_complete_messages(message_snapshot)
        if max_context_chars is not None:
            check_request_chars(message_snapshot,max_context_chars)

        size = self._input_estimator(
            deepcopy(message_snapshot),deepcopy(tool_snapshot)
            )
        if not isinstance(size,InputSizeEstimate):
            raise ValueError('请求估算结果格式不正确')
        self.last_estimate = size

        await await_before_deadline(
            lambda: asyncio.sleep(0),deadline
            )
        check_estimated_window(
            size.estimated_input_tokens,  # 输入估算量
            self._window_budget.reserved_output_tokens,  # 回答预留
            self._window_budget.context_window_tokens,  # 模型窗口
            self._window_budget.safety_margin_tokens,  # 估算余量
        )
        return await await_before_deadline(
            lambda: self._provider.generate(message_snapshot,tool_snapshot),
            deadline,
            )

    async def generate(
        self,
        history: Sequence[ConversationItem] | ContextParts,  # 接收原有列表或分开的历史与资料
        tools: Sequence[ToolDefinition],  # 本次工具定义
        *,
        deadline: float | None = None,  # 同一次运行的截止时间，不在构建后重新计时。
        max_context_chars: int | None=None,
    ) -> Message:
        self.last_estimate = None  # 清除上次估算，避免混淆

        tool_snapshot = deepcopy(list(tools))

        if isinstance(history,ContextParts):
            if self._window_budget is None:
                raise ValueError("分开组装必须配置窗口预算")
            if type(max_context_chars) is not int or max_context_chars <= 0:
                raise ValueError("分开组装必须配置正整数字符上限")

            messages = await await_before_deadline(
                lambda:build_separate_context(self._builder,history),
                deadline,
                )
            check_request_chars(messages,max_context_chars)
        else:
            snapshot = deepcopy(list(history))
            messages = await self._builder.build(snapshot)
            messages = deepcopy(list(messages))
        # snapshot = deepcopy(list(history))  # 复制消息及嵌套内容
        # tool_snapshot = deepcopy(list(tools))  # 估算和发送使用同一份工具定义
        # messages = await self._builder.build(snapshot)  # 先整理上下文
        # messages = deepcopy(list(messages))  # 隔离构建器返回的对象

        if self._window_budget is not None:  # 配置了预算才执行估算门禁
            await await_before_deadline(
                lambda: asyncio.sleep(0),  # 构建结束后，先响应取消并检查总时限
                deadline,  # 继续使用同一次运行的截止时间
            )
            check_complete_messages(messages)  # 校验构建完成的实际候选消息，失败就不继续发送
            size = self._input_estimator(messages, tool_snapshot)  # 统计整理后的消息和工具定义
            self.last_estimate = size  # 保存本次估算，包括超预算的情况
            await await_before_deadline(
                lambda: asyncio.sleep(0),  # 同步估算返回后，优先响应取消和总时限。
                deadline,
            )
            check_estimated_window(
                size.estimated_input_tokens,  # 输入估算量
                self._window_budget.reserved_output_tokens,  # 输出预留
                self._window_budget.context_window_tokens,  # 总窗口
                self._window_budget.safety_margin_tokens,  # 误差余量
            )

        return await await_before_deadline(
            lambda: self._provider.generate(messages, tool_snapshot),  # 最终复核通过后才启动实际请求。
            deadline,  # 实际模型等待仍使用同一截止时间。
        )
