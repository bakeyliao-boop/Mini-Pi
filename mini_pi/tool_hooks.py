"""工具执行前规则；规则与工具共用本次运行的时限。"""

import asyncio
from collections.abc import Awaitable, Callable
from copy import deepcopy

from mini_pi.models import ToolCall, ToolResult
from mini_pi.run_deadline import RunDeadlineExceeded, await_before_deadline


# 规则接收已检查的工具调用；None 表示允许，非空字符串表示拒绝原因。
BeforeToolCall = Callable[[ToolCall], Awaitable[str | None]]
async def  execute_tool_with_rule(executor,call:ToolCall,rule:BeforeToolCall | None,deadline:float | None) -> ToolResult:
    if rule is None:
        return await await_before_deadline(lambda: executor.execute(call), deadline)

    prepare = getattr(executor,'prepare_call',None)
    if not callable(prepare):
        return ToolResult(call.id,call.name,output='',error='工具执行器不支持执行前规则')

    prepared = prepare(call)
    if isinstance(prepared, ToolResult):
        return prepared

    tool,arguments = prepared
    checked_call = deepcopy(call)
    checked_call.arguments = deepcopy(arguments)

    try:
        reason = await await_before_deadline(lambda:rule(checked_call),deadline)
    except (asyncio.CancelledError, RunDeadlineExceeded):
        raise
    except Exception as error:
        return ToolResult(call.id,call.name,output='',error=f'执行前规则出错:{error}')
    if reason is not None:
        if not isinstance(reason,str) or not reason.strip():
            return ToolResult(call.id,call.name,output='',error='执行前规则返回值不正确')
        return ToolResult(  # 把规则的拒绝作为工具结果返回
            call.id, call.name, output='',
            error=f'执行前规则拒绝：{reason}',  # 标明拒绝来自规则
        )
    return await await_before_deadline(
        lambda: tool._execute_validated(call, **arguments), deadline
        )
