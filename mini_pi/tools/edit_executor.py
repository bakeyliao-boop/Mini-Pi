"""D08：编辑执行器；先建立受限路径检查，后续接入校验与实际写入。"""

import os
import asyncio
from collections.abc import Sequence
from pathlib import Path

from mini_pi.models import ToolCall, ToolDefinition, ToolResult
from mini_pi.tools.edit_diff import render_edit_diff
from mini_pi.tools.edit_file import replace_unique_text
from mini_pi.tools.edit_policy import EditPolicy


class EditFileExecutor:
    """编辑范围由程序配置；模型提出的路径仍需经过核心检查。"""
    def __init__(self,policy:EditPolicy):
        self.policy = policy
        # 助手准备：声明工具接口；实际调用仍需通过核心参数校验。
        self.definition = ToolDefinition(
            name="edit_file",
            description="以唯一旧文本匹配编辑被授权的 UTF-8 文件，返回修改差异。new_text 可以为空以删除旧文本。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1, "pattern": r"\S"},
                    "old_text": {"type": "string", "minLength": 1},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
                "additionalProperties": False,
            },
        )

    def resolve_edit_path(self,path:str)->Path:
        return self.policy.resolve_edit_path(path)

    def check_file_access(self,target:Path)->None:
        """检查文件的读写条件,不读取内容或修改文件"""
        if not target.exists():
            raise FileNotFoundError("目标文件不存在")
        if not target.is_file():
            raise ValueError("目标必须是普通文件")
        if not os.access(target,os.R_OK | os.W_OK):
            raise PermissionError("目标文件不可读或写")

    def read_editable_file(self,path:str)->tuple[Path,str]:
        """检查范围和读写条件，读取文本，不修改文件"""
        target = self.resolve_edit_path(path)
        self.check_file_access(target)

        raw = target.read_bytes()
        content = raw.decode("utf-8")
        return target,content

    def prepare_edit(self,path:str,old_text:str,new_text:str)->tuple[Path,str,str]:
        """读取并生成修改后的文本，不写回文件"""
        target,before = self.read_editable_file(path)
        after = replace_unique_text(before,old_text,new_text)

        if after == before:
            raise ValueError("替换后内容没有变化")

        return target,before,after

    def apply_edit(self,path:str,old_text:str,new_text:str)->tuple[Path,str,str]:
        """完成检查，替换和实际写入，返回编辑前后的文本"""
        target,before,after = self.prepare_edit(path,old_text,new_text)
        target.write_bytes(after.encode("utf-8"))
        return target,before,after
    def validate_edit_call(self, call: ToolCall) -> dict[str, str]:
        """校验工具名称和参数，返回合法的字符串参数。"""
        if call.name != self.definition.name:
            raise ValueError(f"不支持的工具：{call.name}")
        if not isinstance(call.arguments, dict):
            raise ValueError("arguments 必须是参数字典")

        required = {"path", "old_text", "new_text"}
        if set(call.arguments) != required:
            raise ValueError("必须且只能提供 path、old_text、new_text")

        values: dict[str, str] = {}
        for field in ("path", "old_text", "new_text"):
            value = call.arguments[field]
            if not isinstance(value, str):
                raise ValueError(f"{field} 必须是字符串")
            values[field] = value

        if not values["path"].strip() or not values["old_text"]:
            raise ValueError("path 和 old_text 不能为空")

        return values
    async def execute(self,call:ToolCall)->ToolResult:
        """执行编辑调用，成功和预期失败都返回关联原调用的结果"""
        try:
            args = self.validate_edit_call(call)
            _,before,after = await asyncio.to_thread(
            self.apply_edit,
            args["path"],args["old_text"],args["new_text"],
            )
            diff = render_edit_diff(args["path"],before,after)
        except (ValueError,OSError) as error:
            return ToolResult(call.id,call.name,output="",error=str(error))

        return ToolResult(call.id,call.name,output=diff)



    # 旧实现保留用于学习对照；已由独立的 EditPolicy 替代，不参与执行。
    # def __init__(self, workdir: str | Path, allowed_files: Sequence[str]):
    #     self.workdir = Path(workdir).resolve()
    #     if not self.workdir.is_dir():
    #         raise ValueError("工作目录必须是已存在的目录")
    #     self.allowed_files: set[Path] = set()
    #     for name in allowed_files:
    #         if not isinstance(name, str) or not name.strip():
    #             raise ValueError("允许清单必须包含非空相对文件路径")
    #         relative = Path(name)
    #         if relative.is_absolute() or relative.drive or ".." in relative.parts:
    #             raise ValueError("允许清单必须使用工作目录内的相对路径")
    #         self.allowed_files.add(relative)

    # def resolve_edit_path(self, path: str) -> Path:
    #     """解析实际目标，检查工作目录和允许清单；不执行文件读写。"""
    #     relative = Path(path)
    #     if relative.is_absolute() or relative.drive:
    #         raise ValueError("编辑路径必须是相对路径")
    #
    #     target = (self.workdir / relative).resolve()
    #     try:
    #         actual_relative = target.relative_to(self.workdir)
    #     except ValueError:
    #         raise ValueError("目标在工作目录之外")
    #     if actual_relative not in self.allowed_files:
    #         raise ValueError("目标不在被允许的编辑清单中")
    #
    #     return target

    # def reject_protected_path(self, relative: Path) -> None:
    #     """检查相对路径中的受保护文件和目录；本函数不读写文件。"""
    #     for part in relative.parts:
    #         if part.lower() == ".git":
    #             raise ValueError("Git 内部目录禁止编辑")
    #     name = relative.name.lower()
    #     if name == "agents.md" or name == ".env" or name.startswith(".env."):
    #         raise ValueError("目标属于受保护文件")
