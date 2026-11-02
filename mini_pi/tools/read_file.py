"""读取指定工作目录内的 UTF-8 文本，预期错误通过统一结果反馈。"""

import asyncio
from pathlib import Path

from mini_pi.models import ToolCall, ToolDefinition, ToolResult


class ReadFileExecutor:
    """当前支持 read_file；路径检查不等于完整的操作系统沙箱。"""

    def __init__(self, workdir: str | Path):
        self.workdir = Path(workdir).resolve()
        if not self.workdir.is_dir():
            raise ValueError("工作目录必须是已存在的目录")
        self.definition = ToolDefinition(
            name="read_file",
            description="读取工作目录内的 UTF-8 文本文件，path 必须是非空相对路径。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1, "pattern": r"\S"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        )

    def validate_call(self, call: ToolCall) -> dict[str, str]:  # 单独检查工具名和参数
        if call.name != self.definition.name:
            raise ValueError(f"不支持的工具：{call.name}")
        if not isinstance(call.arguments, dict):
            raise ValueError("arguments 必须是参数字典")
        if set(call.arguments) != {"path"}:
            raise ValueError("read_file 必须且只能提供 path 参数")

        path = call.arguments["path"]
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path 必须是非空字符串")
        return {"path": path}  # 返回检查通过的参数

    async def execute(self, call: ToolCall) -> ToolResult:  # 保留原来的工具入口
        try:
            path = self.validate_call(call)["path"]
        except ValueError as error:
            return self._error(call, str(error))

        return await self._execute_validated(call, path)  # 参数通过后，进入读取部分

    async def _execute_validated(self, call: ToolCall, path: str) -> ToolResult:  # 使用已检查的路径
        relative_path = Path(path)  # 后续继续原有的路径安全检查与读取
        if relative_path.is_absolute() or relative_path.drive:
            return self._error(call, "path 必须是工作目录内的相对路径")

        try:
            target = (self.workdir / relative_path).resolve()
            target.relative_to(self.workdir)
        except (ValueError, OSError, RuntimeError):
            return self._error(call, "path 无法解析或指向工作目录之外")

        try:
            output = await asyncio.to_thread(target.read_text, encoding="utf-8")
        except FileNotFoundError:
            return self._error(call, f"文件不存在：{path}")
        except IsADirectoryError:
            return self._error(call, f"目标不是文本文件：{path}")
        except UnicodeError:
            return self._error(call, f"文件不是有效的 UTF-8 文本：{path}")
        except OSError as error:
            return self._error(call, f"读取失败：{error}")

        return ToolResult(call.id, call.name, output)

    @staticmethod
    def _error(call: ToolCall, reason: str) -> ToolResult:
        return ToolResult(call.id, call.name, output="", error=reason)
