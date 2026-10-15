"""D06：请求模型、执行工具，并将结果反馈到下一轮请求。"""

import asyncio
import math

from mini_pi.executor import ToolExecutor
from mini_pi.models import ConversationItem, RunResult, ToolDefinition
from mini_pi.provider import ModelProvider
from mini_pi.run_deadline import RunDeadlineExceeded, await_before_deadline
from mini_pi.session_store import SessionStore


async def run_loop(
    provider: ModelProvider,
    executor: ToolExecutor,
    initial_messages: list[ConversationItem],
    tools: list[ToolDefinition],
    session_store: SessionStore | None = None,
    already_saved: int = 0,
    max_model_turns: int | None = None,
    total_timeout_seconds: float | None = None,
) -> RunResult:
    history = list(initial_messages)
    # D12 助手准备：配置校验先于模型请求、工具执行与会话追加。
    if max_model_turns is not None and (
        type(max_model_turns) is not int or max_model_turns <= 0
    ):
        raise ValueError("max_model_turns 必须是正整数或 None")

    # D12 助手准备：时间上限允许正数秒，拒绝布尔值与非有限数。
    if total_timeout_seconds is not None and (
        type(total_timeout_seconds) not in (int, float)
        or not math.isfinite(total_timeout_seconds)
        or total_timeout_seconds <= 0
    ):
        raise ValueError("total_timeout_seconds 必须是有限正数或 None")

    # 助手准备：只接收可信调用方提供的已存历史长度，不改变模型可见历史。
    if type(already_saved) is not int or not 0 <= already_saved <= len(history):
        raise ValueError("already_saved 必须是 0 到历史长度之间的整数")
    event_loop = asyncio.get_running_loop()
    deadline = None
    if total_timeout_seconds is not None:
        deadline = event_loop.time() + total_timeout_seconds

    if session_store is not None:
        session_store.append_entry("run_start", {"status": "running"})
        for item in history[already_saved:]:
            session_store.append_item(item)


    model_turns = 0
    while True:
        if max_model_turns is not None and model_turns >= max_model_turns:
            run_result = RunResult(
                status="budget_exhausted",
                messages=history,
                )
            if session_store is not None:
                session_store.append_entry(
                    "run_end",
                    {"status":run_result.status,
                    "task_passed":run_result.task_passed,
                    "error":run_result.error,
                    })
            return run_result
        model_turns += 1
        try:
            message = await await_before_deadline(
                lambda:provider.generate(history,tools),
                deadline,
                )
        except RunDeadlineExceeded as error:
            run_result = RunResult(
                status="timeout",
                messages=history,
                error=str(error),
            )
            if session_store is not None:
                session_store.append_entry("run_end", {
                    "status": run_result.status,
                    "task_passed": run_result.task_passed,
                    "error": run_result.error,
                })
            return run_result
        except asyncio.CancelledError:
            run_result = RunResult(
                status="cancelled",
                messages=history,
            )
            if session_store is not None:
                session_store.append_entry("run_end", {
                    "status": run_result.status,
                    "task_passed": run_result.task_passed,
                    "error": run_result.error,
                })
            return run_result
        # message = await provider.generate(history, tools)
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
            try:
                result = await await_before_deadline(
                    lambda:executor.execute(call),
                    deadline,
                    )
            except RunDeadlineExceeded as error:
                run_result = RunResult(
                    status="timeout",
                    messages=history,
                    error=str(error),
                    )
                if session_store is not None:
                    session_store.append_entry("run_end",{
                    "status":run_result.status,
                    "task_passed":run_result.task_passed,
                    "error":run_result.error,})
                return run_result
            except asyncio.CancelledError:
                run_result = RunResult(
                    status="cancelled",
                    messages=history,
                )
                if session_store is not None:
                    session_store.append_entry("run_end", {
                        "status": run_result.status,
                        "task_passed": run_result.task_passed,
                        "error": run_result.error,
                    })
                return run_result
            # result = await executor.execute(call)
            history.append(result)
            if session_store is not None:
                session_store.append_item(result)
