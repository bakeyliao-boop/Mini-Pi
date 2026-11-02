"""D09：统一工具分发入口；按 ToolCall.name 选择已有执行器。"""

from collections.abc import Mapping

from mini_pi.executor import ToolExecutor
from mini_pi.models import ToolCall, ToolResult


class ToolRouter:
    """助手准备执行器映射；学习者实现名称选择和未知工具反馈。"""

    def __init__(self, executors: Mapping[str, ToolExecutor]):
        self.executors = dict(executors)

    def prepare_call(self, call: ToolCall):  # 找到工具并检查参数
        executor = self.executors.get(call.name)  # 根据工具名找到执行器
        if executor is None:  # 没有这个工具
            return ToolResult(call.id, call.name, output="", error=f"未知工具：{call.name}")

        validate = getattr(executor, "validate_call", None)  # 找到工具的参数检查函数
        execute_validated = getattr(executor, "_execute_validated", None)  # 找到检查后的执行函数
        if not callable(validate) or not callable(execute_validated):  # 工具还没有拆成这两步
            return ToolResult(call.id, call.name, output="", error="工具暂不支持执行前规则")

        try:
            arguments = validate(call)  # 检查参数，不执行工具
        except ValueError as error:  # 参数不正确
            return ToolResult(call.id, call.name, output="", error=str(error))

        return executor, arguments  # 把工具和检查通过的参数交给后续流程
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
