"""D13-D：统一新任务与恢复入口；任务调度核心由学习者分段手敲。"""

import asyncio
from dataclasses import dataclass

from mini_pi.agent import Agent, RunEndHook
from mini_pi.bootstrap import ToolBundle
from mini_pi.context import ContextBuilder, ContextProvider, FullHistoryContext
from mini_pi.loop import PrepareMessages
from mini_pi.models import Message, RunResult
from mini_pi.provider import ModelProvider
from mini_pi.recovery_policy import plan_recovery
from mini_pi.session_recovery import find_pending_calls
from mini_pi.session_resume import ResumeResult
from mini_pi.session_store import SessionStore


@dataclass(frozen=True)
class RunBudget:
    """每次运行使用同一份显式预算；合法性由既有运行门禁检查。"""

    max_model_turns: int | None = None
    total_timeout_seconds: float | None = None


class Harness:
    def __init__(
        self,
        provider: ModelProvider,
        tools: ToolBundle,
        *,
        budget: RunBudget | None = None,
        on_run_end: RunEndHook | None = None,
        context_builder: ContextBuilder | None = None,
        prepare_messages: PrepareMessages | None = None,
    ):
        """只保存配置并组装一个共享Agent，不启动模型或工具。"""
        if prepare_messages is not None and context_builder is not None:
            raise ValueError("首版记忆准备与自定义context_builder不能同时配置；须先确定最终消息预算与变换顺序")
        self._tools = tools
        self._prepare_messages = prepare_messages  # 两入口共享明确配置，默认关闭
        self._budget = budget if budget is not None else RunBudget()
        builder = context_builder if context_builder is not None else FullHistoryContext()
        context_provider = ContextProvider(provider,builder)
        self.agent = Agent(
            context_provider,
            tools.executor,
            tools.definitions,
            on_run_end = on_run_end,
            )

    def run(self, user_text: str, session_store: SessionStore) -> asyncio.Future[RunResult]:
        """新任务入口；调用方提供本次新会话Store，已有记录须走恢复。"""
        if self.agent.is_running:
            raise RuntimeError("Harness已有活动运行，请等待收尾")
        if not isinstance(user_text,str) or not user_text.strip():
            raise ValueError("任务内容必须是非空字符串")
        if session_store.path.exists():
            raise FileExistsError("会话已存在，请使用恢复入口")

        return self.agent.prompt(
            [Message("user",user_text)],
            session_store=session_store,
            max_model_turns=self._budget.max_model_turns,
            prepare_messages=self._prepare_messages,  # 不旁路Agent或恢复ready门禁
            total_timeout_seconds=self._budget.total_timeout_seconds,
            )

    async def resume(self, user_text: str, session_store: SessionStore) -> ResumeResult:
        """调用方用旧路径创建新Store；ready后经共享Agent增量继续。"""
        if self.agent.is_running:
            raise RuntimeError("Harness已有活动运行，请等待收尾")
        if not isinstance(user_text,str) or not user_text.strip():
            raise ValueError("任务内容必须是非空字符串")
        loaded = session_store.load()
        pending = find_pending_calls(loaded)
        plan = plan_recovery(pending,self._tools.read_only_tools)
        if plan.state != "ready":
            return ResumeResult(plan=plan,run_result=None)

        if session_store.run_id in {row["run_id"] for row in loaded.records}:
            raise ValueError("恢复必须使用新的run_id")
        history = loaded.history + [Message("user",user_text)]
        run_result = await self.agent.prompt(
            history,
            session_store=session_store,
            already_saved=len(loaded.history),
            max_model_turns=self._budget.max_model_turns,  # 本次模型请求次数上限
            prepare_messages=self._prepare_messages,  # 不旁路Agent或恢复ready门禁
            total_timeout_seconds=self._budget.total_timeout_seconds,  # 本次循环总时限
        )
        return ResumeResult(plan=plan,run_result=run_result)  # 返回恢复判断和运行结果
