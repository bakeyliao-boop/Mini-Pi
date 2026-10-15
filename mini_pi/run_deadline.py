"""D12：统一等待截止时间；接口与异常类型由助手准备，判断由学习者实现。"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar


ResultT = TypeVar("ResultT")


class RunDeadlineExceeded(TimeoutError):
    """本次运行的总时限已到；与模型或工具自身抛出的 TimeoutError 区分。"""


async def await_before_deadline(
    operation: Callable[[], Awaitable[ResultT]],
    deadline: float | None,
) -> ResultT:
    """operation 在门禁通过后才调用；返回真实结果，不制造模型或工具反馈。"""
    # 截止时间已到则拒绝启动；未配置则正常等待。
    if deadline is not None and asyncio.get_running_loop().time() >= deadline:
        raise RunDeadlineExceeded("运行总时间已到")
    if deadline is None:
        return await operation()
    # 在固定截止时间内等待，并识别本次总时限超时。
    timeout = asyncio.timeout_at(deadline)
    try:
        async with timeout:
            return await operation()
    except TimeoutError:
        if timeout.expired():
            raise RunDeadlineExceeded("运行总时间已到") from None
        raise
