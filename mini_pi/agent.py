"""D13-B：管理一次活动运行；核心生命周期逻辑由学习者分段敲入。"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from mini_pi.executor import ToolExecutor
from mini_pi.loop import run_loop
from mini_pi.message_queue import PendingMessageQueue
from mini_pi.models import ConversationItem, RunResult, ToolDefinition
from mini_pi.provider import ModelProvider
from mini_pi.session_store import SessionStore


RunEndHook = Callable[[RunResult | None, BaseException | None], Awaitable[None]]


# 在下方手敲 Agent；导入和回调类型由助手准备。

@dataclass
class _ActiveRun:
    idle:asyncio.Event
    task:asyncio.Task[RunResult] | None = None
    started:bool = False
    abort_requested: bool = False
    closing:bool = False


class Agent:
    def __init__(
        self,
        provider: ModelProvider,
        executor: ToolExecutor,
        tools: list[ToolDefinition],
        *,
        on_run_end: RunEndHook | None = None,
    ):
        self._provider = provider
        self._executor = executor
        self._tools = list(tools)
        self._on_run_end = on_run_end
        self._active_run = None
        self._steering_queue = PendingMessageQueue()  # 本Agent独立的方向调整队列
        self._follow_up_queue = PendingMessageQueue()  # 另建后续队列，避免两类消息混用

    @property
    def is_running(self) -> bool:
        return self._active_run is not None

    def steer(self,text:str)->None:
        self._steering_queue.enqueue(text)

    def follow_up(self,text:str)->None:
        self._follow_up_queue.enqueue(text)

    def _reserve_run(self)->_ActiveRun:
        """拒绝重入，并登记本次活动运行"""
        if self._active_run is not None:
            raise RuntimeError("Agent已有活动运行，请等待收尾完成")

        run = _ActiveRun(idle=asyncio.Event())
        self._active_run = run
        return run

    def prompt(
        self,
        initial_messages: list[ConversationItem],
        *,
        session_store: SessionStore | None = None,
        already_saved: int = 0,
        max_model_turns: int | None = None,
        total_timeout_seconds: float | None = None,
    ) -> asyncio.Future[RunResult]:
        """立即提交一次运行；占用与调度逻辑由学习者手敲。"""
        options = {
            "session_store": session_store,
            "already_saved": already_saved,
            "max_model_turns": max_model_turns,
            "total_timeout_seconds": total_timeout_seconds,
        }
        loop = asyncio.get_running_loop()  #取得事件循环
        messages = list(initial_messages)  #复制本次输入消息列表
        run =self._reserve_run()  #申请并且占用Agent运行名额
        operation = self._run(run,messages,options)  #用运行记录、消息、配置创建待调度的协程

        try:
            run.task = loop.create_task(operation)
        except BaseException:
            operation.close()
            if self._active_run is run:
                self._active_run = None
            run.idle.set()
            raise

        return asyncio.shield(run.task)  #隔开等待者的取消和实际任务的取消。


    async def _run(
        self,
        run: _ActiveRun,
        messages: list[ConversationItem],
        options: dict,
    ) -> RunResult:
        result = None
        error = None
        run.started = True

        try:
            if run.abort_requested:
                asyncio.current_task().cancel()

            result = await run_loop(
                self._provider,
                self._executor,
                messages,
                self._tools,
                get_steering_messages=self._steering_queue.drain_one,
                get_follow_up_messages=self._follow_up_queue.drain_one,
                **options,
            )
            return result
        except BaseException as caught:
            error = caught
            raise
        finally:
            run.closing = True
            try:
                if self._on_run_end is not None:
                    await self._on_run_end(result, error)
            finally:
                if self._active_run is run:
                    self._active_run = None
                run.idle.set()
    def abort(self) -> None:  # 请求取消当前运行，不在这里释放占位
        """请求取消当前运行，不提前释放占位"""
        run = self._active_run  #取得运行记录
        if run is None or run.closing or run.abort_requested:  # 空闲、收尾中或已请求取消时跳过
            return  ## 退出 abort，不会释放运行占位

        run.abort_requested = True  # 登记取消，未启动时由 _run 在启动后处理
        if run.started and run.task is not None:  # 已启动且持有 Task 才直接请求取消
            run.task.cancel()  # 请求取消，保留占位直至收尾结束

    def wait_for_idle(self) -> Awaitable[None]:  # 调用时确定本次等待的对象
        run = self._active_run  # 捕获当前运行，后续不跟随新任务切换

        async def wait() -> None:  # 返回给调用方等待的内部协程
            if run is not None:  # 调用时空闲则无需等待
                await run.idle.wait()  # 等收尾通知，取消等待不会取消实际运行

        return wait()  # 返回协程，等待代码在被 await 时执行
