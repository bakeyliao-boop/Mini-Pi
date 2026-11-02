"""D09：列出工作目录内的文件和目录。"""

import asyncio
from pathlib import Path

from mini_pi.models import ToolCall, ToolDefinition, ToolResult


class ListFilesExecutor:
    """列出目录项；核心参数检查和执行逻辑由学习者分段实现。"""

    def __init__(self, workdir: str | Path):
        self.workdir = Path(workdir).resolve()
        if not self.workdir.is_dir():
            raise ValueError("工作目录必须是已存在的目录")
        self.definition = ToolDefinition(
            name="list_files",
            description="列出工作目录内的目录项。path 可选，默认为当前目录；limit 可选，默认为 500。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                },
                "additionalProperties": False,
            },
        )

    def collect_names(self,directory:Path)->list[str]:
        """扫描目录并生成名称列表，由后台线程调用"""
        names = []
        for entry in directory.iterdir():
            suffix = "/" if entry.is_dir() else ""
            names.append(entry.name + suffix)
        return names

    def validate_call(self, call: ToolCall) -> dict[str, object]:  # 检查工具名和参数
        if call.name != self.definition.name:
            raise ValueError(f"不支持的工具：{call.name}")

        arguments = call.arguments
        if not isinstance(arguments, dict):
            raise ValueError("参数错误：arguments 必须是字典")
        if set(arguments) - {"path", "limit"}:
            raise ValueError("参数错误：只接受 path 和 limit")

        path = arguments.get("path", ".")  # 未指定路径时使用当前目录
        limit = arguments.get("limit", 500)  # 未指定数量时最多显示 500 项
        if not isinstance(path, str) or not path.strip():
            raise ValueError("参数错误：path 必须是非空字符串")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("参数错误：limit 必须是 1 到 500 的整数")

        return {"path": path, "limit": limit}  # 将检查后的参数交给后续流程

    async def execute(self, call: ToolCall) -> ToolResult:  # 保留原来的工具入口
        try:
            arguments = self.validate_call(call)
        except ValueError as error:
            return self._error(call, str(error))
        return await self._execute_validated(call, **arguments)  # 参数通过后继续执行

    async def _execute_validated(
        self, call: ToolCall, path: str, limit: int
    ) -> ToolResult:  # 使用已检查的参数列目录
        relative_path = Path(path)  # 保留原有的路径检查和读取
        if relative_path.is_absolute() or relative_path.drive:
            return self._error(call, "参数错误：path 必须是相对路径")

        try:
            directory = (self.workdir / relative_path).resolve()
            directory.relative_to(self.workdir)
        except (ValueError, OSError, RuntimeError):
            return self._error(call, "参数错误：path 指向工作目录之外或无法解析")

        try:
            # entries = await asyncio.to_thread(list, directory.iterdir())
            names = await asyncio.to_thread(self.collect_names,directory)
        except FileNotFoundError:
            return self._error(call, f"执行失败：目录不存在：{path}")
        except NotADirectoryError:
            return self._error(call, f"执行失败：目标不是目录：{path}")
        except OSError as error:
            return self._error(call, f"执行失败：读取目录失败：{error}")

        # names = []
        # for entry in entries:
        #     suffix = "/" if entry.is_dir() else ""
        #     names.append(entry.name + suffix)

        names.sort(key=str.casefold)
        shown = names[:limit]
        output = "\n".join(shown) if shown else "(empty directory)"
        if len(names) > limit:
            output += f"\n[已截断：仅显示前 {limit} 项，共 {len(names)} 项]"
        return ToolResult(call.id, call.name, output)

    @staticmethod
    def _error(call: ToolCall, reason: str) -> ToolResult:
        return ToolResult(call.id, call.name, output="", error=reason)
