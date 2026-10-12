"""模型适配器接口：供应商请求与响应格式由具体适配器转换。"""

from collections.abc import Sequence
from typing import Protocol

from mini_pi.models import ConversationItem, Message, ToolDefinition


class ModelProvider(Protocol):
    async def generate(
        self,
        history: Sequence[ConversationItem],
        tools: Sequence[ToolDefinition],
    ) -> Message:
        """根据历史和工具定义返回 assistant 消息，不修改输入历史。

        适配器把 ToolResult 转换为供应商的工具结果消息，并保留调用 ID。
        输出使用 Message/ToolCall，避免原始供应商格式进入核心循环。
        模型请求失败应抛出异常，交给上层运行控制处理。
        """
        ...
