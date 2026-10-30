"""D13-D：统一新任务与恢复入口；任务调度核心由学习者分段手敲。"""

import asyncio
from dataclasses import dataclass
from collections.abc import Callable, Sequence
from functools import partial

from mini_pi.agent import Agent, RunEndHook
from mini_pi.auto_compaction import AutoCompactionSettings
from mini_pi.bootstrap import ToolBundle
from mini_pi.context import ContextBuilder, ContextProvider, FullHistoryContext, ReadOutputContext
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context_size import InputSizeEstimate
from mini_pi.compaction_restore import build_live_restored_history, read_saved_compaction
from mini_pi.loop import PrepareMessages, PrepareReferences
from mini_pi.models import ConversationItem, Message, RunResult, ToolDefinition
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
        prepare_references: PrepareReferences | None = None,  # 本轮参考资料准备入口
        max_context_chars: int | None = None,  # 完整请求的字符上限
        input_estimator: Callable[[Sequence[ConversationItem], Sequence[ToolDefinition]], InputSizeEstimate] | None = None,  # 输入大小估算器
        window_budget: ContextWindowBudget | None = None,  # 单次请求窗口预算，与轮数和总时限分开
        auto_compaction: AutoCompactionSettings | None = None,  # 可选自动摘要配置
        summary_provider: ModelProvider | None = None,  # 生成摘要的模型
        summary_window: ContextWindowBudget | None = None,  # 摘要模型的窗口预算
        summary_estimator: Callable[[Sequence[ConversationItem], Sequence[ToolDefinition]], InputSizeEstimate] | None = None,
        item_estimator: Callable[[ConversationItem], int] | None = None,  # 单条历史大小估算
    ):
        """只保存配置并组装一个共享Agent，不启动模型或工具。"""
        if prepare_messages is not None and context_builder is not None:
            if type(context_builder) is not ReadOutputContext:
                raise ValueError("记忆准备与其他构建器不能同时配置；当前只支持ReadOutputContext")
            if input_estimator is None or window_budget is None:
                raise ValueError("联合接线必须配置估算器和窗口预算")
        if prepare_references is not None:  # 启用只准备资料的新入口
            if prepare_messages is not None:  # 新旧入口不能同时使用
                raise ValueError("不能同时配置两种记忆准备入口")
            if not callable(prepare_references):  # 新入口必须可以调用
                raise ValueError("prepare_references 必须可以调用")
            if input_estimator is None or window_budget is None:  # 需要最终窗口检查
                raise ValueError("分开组装必须配置估算器和窗口预算")
            if type(max_context_chars) is not int or max_context_chars <= 0:  # 检查字符上限
                raise ValueError("分开组装必须配置正整数字符上限")
        elif max_context_chars is not None:  # 没启用新入口时，不接受用不到的上限
            raise ValueError("字符上限需要与 prepare_references 一起配置")
        self._tools = tools
        self._prepare_messages = prepare_messages  # 两入口共享明确配置，默认关闭
        self._prepare_references = prepare_references  # 保存新入口
        self._max_context_chars = max_context_chars  # 保存字符上限
        self._window_budget = window_budget  # 恢复摘要时确认最终窗口检查已配置
        self._auto_compaction = auto_compaction  # 保存自动摘要所需配置
        self._summary_provider = summary_provider
        self._summary_window = summary_window
        self._summary_estimator = summary_estimator
        self._item_estimator = item_estimator
        self._budget = budget if budget is not None else RunBudget()
        builder = context_builder if context_builder is not None else FullHistoryContext()
        if window_budget is not None:  # 已配置窗口预算时，核对适配器暴露的实际输出上限
            output_limit = getattr(provider, "max_completion_tokens", None)  # 当前Qwen适配器提供这个属性
            if output_limit is not None:  # 未暴露上限的适配器，由调用方保证配置一致
                if type(output_limit) is not int or output_limit <= 0:
                    raise ValueError("模型输出上限必须是正整数")
                if output_limit > window_budget.reserved_output_tokens:  # 实际输出上限不能超过预留
                    raise ValueError("输出预留不能小于模型配置的输出上限")
        context_provider = ContextProvider(
            provider, builder,
            input_estimator=input_estimator,
            window_budget=window_budget,
        )
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
            prepare_references=self._prepare_references,  # 转交本轮资料准备入口
            max_context_chars=self._max_context_chars,  # 转交完整请求的字符上限
            auto_compaction=self._auto_compaction,  # 自动摘要触发配置
            summary_provider=self._summary_provider,  # 摘要模型
            summary_window=self._summary_window,  # 摘要模型窗口预算
            summary_estimator=self._summary_estimator,  # 摘要请求估算
            item_estimator=self._item_estimator,  # 单条历史估算
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
        prepare_model_history = None
        if read_saved_compaction(loaded) is not None:
            if self._prepare_messages is not None:
                raise ValueError("摘要恢复不能与旧的消息准备入口同时使用")
            if self._window_budget is None:
                raise ValueError("摘要恢复必须配置输入估算器和窗口预算")
            prepare_model_history = partial(build_live_restored_history, loaded)
        history = loaded.history + [Message("user",user_text)]
        run_result = await self.agent.prompt(
            history,
            session_store=session_store,
            already_saved=len(loaded.history),
            max_model_turns=self._budget.max_model_turns,  # 本次模型请求次数上限
            prepare_messages=self._prepare_messages,  # 不旁路Agent或恢复ready门禁
            prepare_references=self._prepare_references,  # 转交本轮资料准备入口
            prepare_model_history=prepare_model_history,  # 仅已有摘要时提供模型请求视图
            max_context_chars=self._max_context_chars,  # 转交完整请求的字符上限
            auto_compaction=self._auto_compaction,  # 自动摘要触发配置
            summary_provider=self._summary_provider,  # 摘要模型
            summary_window=self._summary_window,  # 摘要模型窗口预算
            summary_estimator=self._summary_estimator,  # 摘要请求估算
            item_estimator=self._item_estimator,  # 单条历史估算
            total_timeout_seconds=self._budget.total_timeout_seconds,  # 本次循环总时限
        )
        return ResumeResult(plan=plan,run_result=run_result)  # 返回恢复判断和运行结果
