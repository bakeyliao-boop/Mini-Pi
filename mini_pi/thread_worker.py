"""助手准备：同步工作线程的等待与取消收尾；不强制终止运行中的线程。"""

import asyncio
from collections.abc import Callable
from typing import TypeVar


ResultT = TypeVar("ResultT")


def _invoke(function, args, kwargs):
    """把同步结果/异常都变成普通返回值，避免取消后的 shield 额外打印异常。"""
    try:
        return function(*args, **kwargs), None
    except Exception as error:
        return None, error


async def run_sync_with_cleanup(function: Callable[..., ResultT], *args, **kwargs) -> ResultT:
    """正常传回结果/异常；取消时等待线程结束、消费结果，再传播原取消。

    不记录传入参数，避免凭证等内容进入日志。收尾可能超出调用方截止时间。
    """
    await asyncio.sleep(0)  # 启动前给已经到达的取消/超时信号一个检查点。
    worker = asyncio.create_task(
        asyncio.to_thread(_invoke, function, args, kwargs), name="mini-pi-sync-worker",
    )
    try:
        value, error = await asyncio.shield(worker)
        if error is not None:
            raise error
        return value
    except asyncio.CancelledError:
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                pass  # 重复取消不跳过已经启动的线程收尾。
            except Exception:
                break  # 工作线程自身失败仍已结束；下面消费异常，保持取消语义。
        if not worker.cancelled():
            worker.result()
        raise
