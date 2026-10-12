"""工具执行器接口：接收统一调用，返回关联原调用的统一结果。"""

from typing import Protocol

from mini_pi.models import ToolCall, ToolResult


class ToolExecutor(Protocol):
    async def execute(self, call: ToolCall) -> ToolResult:
        """检查并执行调用；预期执行错误以 ToolResult.error 返回。

        成功和预期失败均保留 call.id 与 call.name，便于反馈和回溯。
        """
        ...
