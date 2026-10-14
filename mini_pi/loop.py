"""D06：请求模型、执行工具，并将结果反馈到下一轮请求。"""

from mini_pi.executor import ToolExecutor
from mini_pi.models import ConversationItem, RunResult, ToolDefinition
from mini_pi.provider import ModelProvider
from mini_pi.session_store import SessionStore


async def run_loop(
    provider: ModelProvider,
    executor: ToolExecutor,
    initial_messages: list[ConversationItem],
    tools: list[ToolDefinition],
    session_store: SessionStore | None = None,
) -> RunResult:
    history = list(initial_messages)

    if session_store is not None:
        session_store.append_entry("run_start", {"status": "running"})
        for item in history:
            session_store.append_item(item)

    while True:
        message = await provider.generate(history, tools)
        history.append(message)
        if session_store is not None:
            session_store.append_item(message)

        tool_calls = message.tool_calls
        if not tool_calls:
            run_result = RunResult(status="finished", messages=history)
            if session_store is not None:
                session_store.append_entry("run_end",
                {"status":run_result.status,
                  "task_passed":run_result.task_passed,
                  "error":run_result.error,})
            return run_result

        for call in tool_calls:
            result = await executor.execute(call)
            history.append(result)
            if session_store is not None:
                session_store.append_item(result)
