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
    already_saved: int = 0,
) -> RunResult:
    history = list(initial_messages)
    # 助手准备：只接收可信调用方提供的已存历史长度，不改变模型可见历史。
    if type(already_saved) is not int or not 0 <= already_saved <= len(history):
        raise ValueError("already_saved 必须是 0 到历史长度之间的整数")

    if session_store is not None:
        session_store.append_entry("run_start", {"status": "running"})
        for item in history[already_saved:]:
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
