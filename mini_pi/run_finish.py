"""D12-06：统一确认结束结果、保存 run_end 并返回；核心函数由学习者手敲。"""

import asyncio

from mini_pi.models import RunResult
from mini_pi.session_store import SessionStore

async def finish_run(
    result:RunResult,
    session_store:SessionStore | None,
    )->RunResult:
    try:
        await asyncio.sleep(0)
    except asyncio.CancelledError:
        result = RunResult(
            status="cancelled",
            messages=result.messages,
            )
    if session_store is not None:
        session_store.append_entry("run_end", {
            "status": result.status,
            "task_passed": result.task_passed,
            "error": result.error,
        })

    return result
