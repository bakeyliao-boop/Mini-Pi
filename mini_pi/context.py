"""D13-D：请求上下文接口；保留完整历史，核心转交逻辑由学习者手敲。"""

from collections.abc import Sequence
from copy import deepcopy
from typing import Protocol

from mini_pi.models import ConversationItem, Message, ToolDefinition
from mini_pi.provider import ModelProvider


class ContextBuilder(Protocol):
    async def build(self, history: Sequence[ConversationItem]) -> list[ConversationItem]:
        """从历史副本组装本次请求消息；不得执行历史工具调用。"""
        ...


class FullHistoryContext:
    async def build(self, history: Sequence[ConversationItem]) -> list[ConversationItem]:
        """首版保留所有消息；筛选与裁剪留到后续章节。"""
        return list(history)


class ContextProvider:
    def __init__(self, provider: ModelProvider, builder: ContextBuilder):
        """保存真实适配器与可替换组装器，构造时不启动工作。"""
        self._provider = provider
        self._builder = builder

    async def generate(
        self,
        history: Sequence[ConversationItem],
        tools: Sequence[ToolDefinition],
    ) -> Message:
        """每次请求前组装副本；异常和取消沿既有运行链传播。"""
        snapshot = deepcopy(list(history))
        messages = await self._builder.build(snapshot)
        return await self._provider.generate(messages, tools)  # 将组装后的消息交给实际模型适配器
