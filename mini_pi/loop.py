"""D06：请求模型、执行工具，并将结果反馈到下一轮请求。"""

import asyncio
import math
from collections.abc import Awaitable, Callable
from copy import deepcopy

from mini_pi.executor import ToolExecutor
from mini_pi.models import ConversationItem, Message, RunResult, ToolDefinition, ToolResult
from mini_pi.provider import ModelProvider
from mini_pi.run_deadline import RunDeadlineExceeded, await_before_deadline
from mini_pi.run_finish import finish_run
from mini_pi.session_store import SessionStore


PrepareMessages = Callable[[list[ConversationItem]], Awaitable[list[ConversationItem]]]


class RequestPreparationError(RuntimeError):
    """仅标记显式prepare_messages阶段失败，不吞掉模型/普通builder错误。"""


async def run_loop(
    provider: ModelProvider,
    executor: ToolExecutor,
    initial_messages: list[ConversationItem],
    tools: list[ToolDefinition],
    session_store: SessionStore | None = None,
    already_saved: int = 0,
    max_model_turns: int | None = None,
    total_timeout_seconds: float | None = None,
    get_steering_messages: Callable[[], list[Message]] | None = None,
    get_follow_up_messages: Callable[[], list[Message]] | None = None,
    prepare_messages: PrepareMessages | None = None,
) -> RunResult:
    history = list(initial_messages)
    if prepare_messages is not None and not callable(prepare_messages):  # 配置错误先于任何会话追加
        raise ValueError("prepare_messages 必须是可调用的异步入口或 None")
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

    skip_steering_once = False  # 本次运行独立的一次性标记

    async def request_model() -> Message:  # 内部协程，复用本次运行的历史和队列入口
        nonlocal skip_steering_once  # 与自然停止分支共享同一标记
        if not skip_steering_once and get_steering_messages is not None:  # 已选好消息则跳过一次取队列
            for queued in get_steering_messages():  # 统一使用queued变量保存取出的消息
                history.append(queued)  # 加入即将发送给模型的历史
                if session_store is not None:  # 开启保存时同步记录
                    session_store.append_item(queued)  # 保留实际递送顺序
        skip_steering_once = False  # 标记只生效一次
        if prepare_messages is None:  # 未配置时保留主线原路径，不启动任何记忆能力
            return await provider.generate(history, tools)
        try:  # 只有显式请求准备的错误转换为可记录的准备失败
            request_messages = await await_before_deadline(
                lambda: prepare_messages(deepcopy(history)),  # 队列已递送，注入只改深拷贝
                deadline,  # 与本轮模型和工具使用同一截止时间
            )
        except (asyncio.CancelledError, RunDeadlineExceeded):  # 取消及总时限保持各自终态
            raise
        except Exception as error:  # 只包围准备阶段，模型普通异常不在这里
            raise RequestPreparationError(str(error)) from error
        return await await_before_deadline(  # 准备结束后再次检查取消及截止，才真正进入Provider
            lambda: provider.generate(request_messages, tools),
            deadline,
        )

    model_turns = 0
    while True:
        if max_model_turns is not None and model_turns >= max_model_turns:
            run_result = RunResult(
                status="budget_exhausted",
                messages=history,
                )
            return await finish_run(run_result,session_store)
            # if session_store is not None:
            #     session_store.append_entry(
            #         "run_end",
            #         {"status":run_result.status,
            #         "task_passed":run_result.task_passed,
            #         "error":run_result.error,
            #         })
            # return run_result
        model_turns += 1
        try:
            message = await await_before_deadline(
                # lambda:provider.generate(history,tools),
                request_model,  # 参数之间保留逗号
                deadline,
                )
        except RunDeadlineExceeded as error:
            run_result = RunResult(
                status="timeout",
                messages=history,
                error=str(error),
            )
            return await finish_run(run_result, session_store)
        except asyncio.CancelledError:
            run_result = RunResult(
                status="cancelled",
                messages=history,
            )
            return await finish_run(run_result, session_store)
        except RequestPreparationError as error:  # 准备失败才归error；默认builder/Provider错误仍向外抛
            return await finish_run(RunResult(status="error", messages=history, error=str(error)), session_store)
        # message = await provider.generate(history, tools)
        history.append(message)
        if session_store is not None:
            session_store.append_item(message)

        if message.stop_reason in ("error","aborted"):
            run_result = RunResult(
                status="cancelled" if message.stop_reason == "aborted" else "error",
                messages=history,
                error=message.error_message,
                  )
            return await finish_run(run_result,session_store)

        tool_calls = message.tool_calls
        if not tool_calls:
            pending = []
            if get_steering_messages is not None:  # 使用与签名一致的复数参数名
                pending = get_steering_messages()
            if not pending and get_follow_up_messages is not None:
                pending = get_follow_up_messages()

            if pending:
                for queued in pending:
                    history.append(queued)
                    if session_store is not None:
                        session_store.append_item(queued)
                skip_steering_once = True
                continue

            run_result = RunResult(status="finished", messages=history)
            return await finish_run(run_result,session_store)
            # if session_store is not None:
            #     session_store.append_entry("run_end",
            #     {"status":run_result.status,
            #       "task_passed":run_result.task_passed,
            #       "error":run_result.error,})
            # return run_result

        if message.stop_reason == "length":
            for call in tool_calls:
                result = ToolResult(
                    tool_call_id=call.id,
                    tool_name=call.name,
                    output="",
                    error="未执行，模型回复长度被限制截断，请重新提供完整参数",
                )
                history.append(result)
                if session_store is not None:
                    session_store.append_item(result)
            continue

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
                return await finish_run(run_result, session_store)
            except asyncio.CancelledError:
                run_result = RunResult(
                    status="cancelled",
                    messages=history,
                )
                # if session_store is not None:
                #     session_store.append_entry("run_end", {
                #         "status": run_result.status,
                #         "task_passed": run_result.task_passed,
                #         "error": run_result.error,
                #     })
                # return run_result
                return await finish_run(run_result,session_store)
            # result = await executor.execute(call)
            history.append(result)
            if session_store is not None:
                session_store.append_item(result)
