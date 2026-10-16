"""D11 恢复入口：助手准备容器与接口，门禁和继续逻辑由学习者手敲。"""

from dataclasses import dataclass

from mini_pi.executor import ToolExecutor
from mini_pi.loop import run_loop
from mini_pi.models import Message, RunResult, ToolDefinition
from mini_pi.provider import ModelProvider
from mini_pi.recovery_policy import RecoveryPlan, plan_recovery
from mini_pi.session_recovery import find_pending_calls
from mini_pi.session_store import SessionStore


@dataclass(frozen=True)
class ResumeResult:
    """plan 表示恢复判断；未进入循环时 run_result 为 None。"""

    plan: RecoveryPlan
    run_result: RunResult | None


async def resume_session(
    session_store: SessionStore,
    provider: ModelProvider,
    executor: ToolExecutor,
    user_text: str,
    tools: list[ToolDefinition],
    read_only_tools: frozenset[str],
    max_model_turns: int | None = None,
    total_timeout_seconds: float | None = None,
) -> ResumeResult:
    """恢复已存在的会话；调用方提供同一路径、使用新 run_id 的 Store。

    read_only_tools 由调用方明确配置；判断通过后才保存新消息并进入循环。
    """
    # 加载、找 pending、判断，并返回被门禁挡住的状态。
    loaded = session_store.load()
    pending = find_pending_calls(loaded)
    plan = plan_recovery(pending,read_only_tools)

    if plan.state != "ready":
        return ResumeResult(plan=plan,run_result=None) #保留刚才的恢复判断，没有进入run_loop
    # 仅 ready 组装历史、调用 run_loop 并返回运行结果。
    history = loaded.history + [Message("user",user_text)]
    run_result = await run_loop(
        provider=provider,
        executor=executor,
        initial_messages=history,
        tools=tools,
        session_store=session_store,
        already_saved=len(loaded.history),
        max_model_turns=max_model_turns,
        total_timeout_seconds=total_timeout_seconds,
        )
    return ResumeResult(plan=plan,run_result=run_result)
