"""D06：请求模型、执行工具，并将结果反馈到下一轮请求。"""

from mini_pi.executor import ToolExecutor
from mini_pi.models import ConversationItem, RunResult, ToolDefinition
from mini_pi.provider import ModelProvider


async def run_loop(
    provider: ModelProvider,
    executor: ToolExecutor,
    initial_messages: list[ConversationItem],
    tools: list[ToolDefinition],
) -> RunResult:
    history = list(initial_messages)

    while True:
        message = await provider.generate(history, tools)
        history.append(message)

        tool_calls = message.tool_calls
        if not tool_calls:
            return RunResult(status="finished", messages=history)

        for call in tool_calls:
            result = await executor.execute(call)
            history.append(result)
