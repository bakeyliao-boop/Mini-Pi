"""D06：请求模型、执行工具，并将结果反馈到下一轮请求。"""

import asyncio
import math
from collections.abc import Awaitable, Callable, Sequence
from copy import deepcopy

from mini_pi.auto_compaction import AutoCompactionSettings, check_auto_compaction_settings
from mini_pi.compaction import SummaryAborted, SummaryError
from mini_pi.compaction_pipeline import prepare_compaction_candidate
from mini_pi.compaction_record import check_answer_output_limit
from mini_pi.compaction_restore import build_live_restored_history  # 根据已保存的摘要生成本轮模型请求视图
from mini_pi.compaction_save import save_compaction_candidate
from mini_pi.compaction_trigger import should_compact
from mini_pi.context import ContextParts, ContextProvider
from mini_pi.context_budget import ContextBudgetError, ContextWindowBudget, check_estimated_window
from mini_pi.context_size import InputSizeEstimate
from mini_pi.executor import ToolExecutor
from mini_pi.memory.errors import MemoryContextError
from mini_pi.models import ConversationItem, Message, RunResult, ToolDefinition, ToolResult
from mini_pi.provider import ModelProvider
from mini_pi.run_deadline import RunDeadlineExceeded, await_before_deadline
from mini_pi.run_finish import finish_run
from mini_pi.session_store import SessionStore
from mini_pi.summary_call_budget import SummaryCallBudget


PrepareMessages = Callable[[list[ConversationItem]], Awaitable[list[ConversationItem]]]
PrepareReferences = Callable[[list[ConversationItem]], Awaitable[list[Message]]]
PrepareModelHistory = Callable[[list[ConversationItem]], list[ConversationItem]]  # 接收原始历史，返回模型请求视图


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
    prepare_references: PrepareReferences | None = None,
    prepare_model_history: PrepareModelHistory | None = None,  # 可选的模型历史整理入口
    max_context_chars: int | None = None,
    auto_compaction: AutoCompactionSettings | None = None,  # 可选的自动压缩配置
    summary_provider: ModelProvider | None = None,  # 用来生成摘要的模型
    summary_window: ContextWindowBudget | None = None,  # 摘要模型的窗口预算
    summary_estimator: Callable[[Sequence[ConversationItem], Sequence[ToolDefinition]], InputSizeEstimate] | None = None,  # 估算摘要请求
    item_estimator: Callable[[ConversationItem], int] | None = None,  # 估算单条历史，用来选择切点
) -> RunResult:
    history = list(initial_messages)
    if auto_compaction is not None:  # 调用方尝试启用自动压缩
        if not isinstance(session_store, SessionStore):  # 摘要需要保存到会话
            raise ValueError("自动压缩需要会话存储")
        if not isinstance(provider, ContextProvider) or provider._window_budget is None:  # 需要回答窗口预算
            raise ValueError("自动压缩需要配置回答窗口预算")
        check_answer_output_limit(
            provider._provider, provider._window_budget  # 提前核对回答模型的实际输出上限
        )
        if prepare_messages is not None:  # 旧入口已经混合历史和资料，暂不支持自动压缩
            raise ValueError("自动压缩不能使用旧的消息准备入口")

        check_auto_compaction_settings(
            auto_compaction, provider._window_budget  # 检查触发点和近期保留量
        )
        if not callable(getattr(summary_provider, "generate", None)):  # 摘要模型必须能生成响应
            raise ValueError("自动压缩需要摘要模型")
        if not isinstance(summary_window, ContextWindowBudget):  # 摘要模型需要自己的窗口预算
            raise ValueError("自动压缩需要摘要窗口预算")
        if not callable(summary_estimator) or not callable(item_estimator):  # 两种估算方法都要提供
            raise ValueError("自动压缩需要摘要请求和单条历史的估算方法")

        check_estimated_window(
            0, summary_window.reserved_output_tokens,  # 先检查摘要输出预留
            summary_window.context_window_tokens, summary_window.safety_margin_tokens,  # 摘要窗口和余量
        )
        summary_output_limit = getattr(summary_provider, "max_completion_tokens", None)  # 摘要模型的输出上限
        if type(summary_output_limit) is not int or summary_output_limit <= 0:  # 上限必须明确
            raise ValueError("摘要模型必须提供正整数输出上限")
        if summary_output_limit > summary_window.reserved_output_tokens:  # 上限不能超过预留
            raise ValueError("摘要模型输出上限不能超过预留空间")
    if prepare_messages is not None and not callable(prepare_messages):  # 配置错误先于任何会话追加
        raise ValueError("prepare_messages 必须是可调用的异步入口或 None")

    if prepare_references is not None and not callable(prepare_references):
        raise ValueError("prepare_references 必须可以调用")
    if prepare_model_history is not None and not callable(prepare_model_history):
        raise ValueError("prepare_model_history 必须可以调用")

    if prepare_messages is not None and (
        prepare_references is not None or prepare_model_history is not None
    ):
        raise ValueError("旧的消息准备入口不能与新入口同时使用")

    if prepare_references is not None or prepare_model_history is not None:
        if not isinstance(provider, ContextProvider) or provider._window_budget is None:
            raise ValueError("新入口必须使用已配置窗口预算的 ContextProvider")
        if prepare_references is not None and (type(max_context_chars) is not int or max_context_chars <= 0):
            raise ValueError("参考资料入口必须配置正整数字符上限")
        if max_context_chars is not None and (type(max_context_chars) is not int or max_context_chars <= 0):
            raise ValueError("字符上限必须是正整数")
    elif max_context_chars is not None:
        raise ValueError("字符上限需要与新入口一起配置")
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

    summary_call_budget = SummaryCallBudget(1) if auto_compaction is not None else None  # 启用时创建本次运行的摘要计数器

    if session_store is not None:
        session_store.append_entry("run_start", {"status": "running"})
        for item in history[already_saved:]:
            session_store.append_item(item)

    skip_steering_once = False  # 本次运行独立的一次性标记

    compacted_session = None #本次运行还没有保存过摘要

    async def call_provider(items:list[ConversationItem] | ContextParts) -> Message:
        if isinstance(provider,ContextProvider):
            if isinstance(items,ContextParts):
                return await provider.generate(
                    items,tools,
                    deadline=deadline,
                    max_context_chars=max_context_chars,
                    )
            return await provider.generate(
                items,tools,deadline=deadline,
                )
        if isinstance(items,ContextParts):  #如果没有配置context provider又同时收到了分开的历史和资料
            raise ValueError("分开组装需要ContextProvider")
        return await provider.generate(items,tools)
    # async def call_provider(items: list[ConversationItem]) -> Message:  # 统一调用已配置的Provider
    #     if isinstance(provider, ContextProvider):  # Harness创建的是这层上下文包装器
    #         return await provider.generate(
    #             items, tools, deadline=deadline,  # 传递本次运行已有的截止时间
    #         )
    #     return await provider.generate(items, tools)  # 普通适配器维持原接口

    async def prepare_reference_messages(history_for_references):  # 复用参考资料准备和原有格式检查
        if prepare_references is None:  # 没有参考资料入口时返回空列表
            return []
        references = await await_before_deadline(
            lambda: prepare_references(deepcopy(history_for_references)), deadline
        )
        if not isinstance(references, list):
            raise ValueError("参考资料必须是列表")
        if any(not isinstance(item, Message) or item.role != "user" or item.tool_calls for item in references):
            raise ValueError("参考资料格式不正确")
        return references

    async def request_model() -> Message:  # 内部协程，复用本次运行的历史和队列入口
        nonlocal skip_steering_once,compacted_session  # 与自然停止分支共享同一标记

        queued_message_delivered = skip_steering_once
        if not skip_steering_once and get_steering_messages is not None: #这次允许从队列取消息
            for queued in get_steering_messages():
                queued_message_delivered = True
                history.append(queued)
                if session_store is not None:
                    session_store.append_item(queued)
        skip_steering_once = False
        # if not skip_steering_once and get_steering_messages is not None:  # 已选好消息则跳过一次取队列
        #     for queued in get_steering_messages():  # 统一使用queued变量保存取出的消息
        #         history.append(queued)  # 加入即将发送给模型的历史
        #         if session_store is not None:  # 开启保存时同步记录
        #             session_store.append_item(queued)  # 保留实际递送顺序
        # skip_steering_once = False  # 标记只生效一次

        if prepare_references is not None or prepare_model_history is not None or auto_compaction is not None:
            history_snapshot = deepcopy(history)
            try:
                references = await prepare_reference_messages(history_snapshot)  # 按当前原始历史准备参考资料

                model_history = history_snapshot
                if compacted_session is not None:
                    model_history = build_live_restored_history(
                        compacted_session,deepcopy(history_snapshot)
                        )
                elif prepare_model_history is not None:
                    model_history = prepare_model_history(deepcopy(history_snapshot))
                if not isinstance(model_history, list):
                    raise ValueError("模型历史必须是列表")
            except (asyncio.CancelledError, RunDeadlineExceeded):
                raise
            except Exception as error:
                raise RequestPreparationError(str(error)) from error

            if auto_compaction is not None:
                parts = ContextParts(model_history, deepcopy(references))
                messages, prepared_tools, estimate = await provider.prepare_for_compaction(
                    parts, tools, deadline=deadline  # 准备完整请求但不发送
                )
                if should_compact(estimate, provider._window_budget, auto_compaction.trigger_tokens):
                    loaded = session_store.load()  # 核对会话中保存的原始历史
                    if loaded.history != history_snapshot:
                        raise RequestPreparationError("会话历史已变化，不能生成摘要")
                    if any(record["type"] == "compaction" for record in loaded.records):
                        raise ContextBudgetError("会话已有摘要，暂不支持再次压缩")

                    session_id = session_store.ensure_session_id()
                    try:
                        candidate = await prepare_compaction_candidate(
                            history_snapshot, references, prepared_tools,
                            summary_provider, item_estimator, summary_estimator,
                            summary_window, provider._window_budget, summary_call_budget,
                            auto_compaction.keep_recent_tokens, max_context_chars,
                            session_id=session_id, answer_context=provider, deadline=deadline,
                        )
                    except SummaryAborted as error:
                        raise asyncio.CancelledError() from error
                    except SummaryError as error:
                        raise RequestPreparationError(str(error)) from error

                    if candidate is None:
                        raise ContextBudgetError("找不到可用的摘要切点")
                    try:  # 保存阶段的错误沿用请求准备的处理方式
                        await save_compaction_candidate(
                            session_store, candidate, references, prepared_tools,
                            provider, provider._window_budget, max_context_chars, deadline=deadline,
                        )
                    except (asyncio.CancelledError, RunDeadlineExceeded, ContextBudgetError):
                        raise  # 取消、超时和预算不足保留各自的结果
                    except Exception as error:
                        raise RequestPreparationError(str(error)) from error
                    try:  # 准备摘要后的请求
                        compacted_session = session_store.load()  # 读回刚保存摘要的会话
                        steering_added = False  # 记录摘要后是否取到了新消息
                        if not queued_message_delivered and get_steering_messages is not None:  # 本次还没取过排队消息
                            for queued in get_steering_messages():  # 尝试取一条 steering
                                steering_added = True  # 摘要后确实取到了新消息
                                queued_message_delivered = True  # 本次已经取过消息
                                history.append(queued)  # 加入原始历史
                                session_store.append_item(queued)  # 同步保存到会话
                        history_snapshot = deepcopy(history)  # 取得最新的原始历史
                        if steering_added:  # 新消息可能影响需要的参考资料
                            references = await prepare_reference_messages(history_snapshot)  # 重新准备参考资料
                        model_history = build_live_restored_history(  # 生成摘要加近期消息
                            compacted_session, history_snapshot  # 使用已保存摘要和最新原始历史
                        )
                        parts = ContextParts(model_history, references)  # 组合模型历史和参考资料
                        messages, prepared_tools, _ = await provider.prepare_for_compaction(  # 重新准备完整请求
                            parts, tools, deadline=deadline  # 处理长文件结果并估算请求
                        )
                    except (asyncio.CancelledError, RunDeadlineExceeded, ContextBudgetError, MemoryContextError):
                        raise  # 取消、超时和预算问题保留各自处理方式
                    except Exception as error:
                        raise RequestPreparationError(str(error)) from error  # 其他准备失败
                return await provider.send_prepared(
                    messages, prepared_tools, deadline=deadline, max_context_chars=max_context_chars
                )

            if prepare_references is None and max_context_chars is None:
                return await await_before_deadline(lambda: call_provider(model_history), deadline)
            parts = ContextParts(model_history, deepcopy(references))
            return await await_before_deadline(lambda: call_provider(parts), deadline)

        if prepare_messages is None:  # 未配置时保留主线原路径，不启动任何记忆能力
            return await call_provider(history)
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
            lambda: call_provider(request_messages),
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
        except ContextBudgetError as error:  # 明确的窗口预算失败，保留原历史和错误依据。
            run_result = RunResult(
                status="budget_exhausted",
                messages=history,
                error=str(error),
            )
            return await finish_run(run_result, session_store)

        except (RequestPreparationError, MemoryContextError) as error:  # 统一接住明确的准备或消息校验失败
            run_result = RunResult(
                status="error",  # 校验失败不是预算耗尽，也不是任务验收失败
                messages=history,  # 保留原始历史，不写入整理后的请求副本
                error=str(error),  # 保存具体失败原因
            )
            return await finish_run(run_result, session_store)  # 记录run_end并结束本次运行
        # except RequestPreparationError as error:  # 准备失败才归error；默认builder/Provider错误仍向外抛
        #     return await finish_run(RunResult(status="error", messages=history, error=str(error)), session_store)
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
                return await finish_run(run_result,session_store)
            # result = await executor.execute(call)
            history.append(result)
            if session_store is not None:
                session_store.append_item(result)
