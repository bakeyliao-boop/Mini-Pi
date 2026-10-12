"""按预设步骤返回响应，并保存每次请求当时的历史快照；不调用真实模型。"""

from collections.abc import Callable, Sequence
from copy import deepcopy

from mini_pi.models import ConversationItem, Message, ToolDefinition


ResponseFactory = Callable[[Sequence[ConversationItem], Sequence[ToolDefinition]], Message]
MockResponse = Message | ResponseFactory


class MockProvider:
    """每一步可提供固定消息，也可根据收到的工具结果生成消息。"""

    def __init__(self, responses: Sequence[MockResponse]):
        self.responses = list(responses)
        self.requests: list[list[ConversationItem]] = []
        self.tool_requests: list[list[ToolDefinition]] = []

    async def generate(
        self,
        history: Sequence[ConversationItem],
        tools: Sequence[ToolDefinition],
    ) -> Message:
        request_index = len(self.requests)
        history_snapshot = deepcopy(list(history))
        tools_snapshot = deepcopy(list(tools))
        self.requests.append(history_snapshot)
        self.tool_requests.append(tools_snapshot)
        if request_index >= len(self.responses):
            raise AssertionError("模拟响应已用完：循环发起了预期之外的请求")

        response = self.responses[request_index]
        if callable(response):
            response = response(deepcopy(history_snapshot), deepcopy(tools_snapshot))
        if not isinstance(response, Message) or response.role != "assistant":
            raise ValueError("模拟模型必须返回 assistant Message")
        return deepcopy(response)
