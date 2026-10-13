"""D09：统一工具分发入口；按 ToolCall.name 选择已有执行器。"""

from collections.abc import Mapping

from mini_pi.executor import ToolExecutor
from mini_pi.models import ToolCall, ToolResult


class ToolRouter:
    """助手准备执行器映射；学习者实现名称选择和未知工具反馈。"""

    def __init__(self, executors: Mapping[str, ToolExecutor]):
        self.executors = dict(executors)

    async def execute(self, call: ToolCall) -> ToolResult:
        """按工具名执行并返回与调用 ID 对应的结果。"""
        executor = self.executors.get(call.name)
        if executor is None:
            return ToolResult(
              call.id,
              call.name,
              output="",
              error=f"未知工具：{call.name}",
              )
        return await executor.execute(call)
