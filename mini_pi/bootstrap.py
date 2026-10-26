"""D13-D：显式组装运行依赖；核心组装逻辑由学习者分段手敲。"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mini_pi.models import ToolDefinition
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy
from mini_pi.tools.list_files import ListFilesExecutor
from mini_pi.tools.read_file import ReadFileExecutor
from mini_pi.tools.run_tests import RunTestsExecutor
from mini_pi.tools.tool_router import ToolRouter


@dataclass(frozen=True)
class ToolBundle:
    """路由器负责执行，definitions发给模型，read_only_tools用于恢复判断。"""

    executor: ToolRouter
    definitions: list[ToolDefinition]
    read_only_tools: frozenset[str]


def build_tools(
    workdir: str | Path,
    allowed_files: Sequence[str],
    test_command: Sequence[str],
    evidence_dir: str | Path,
) -> ToolBundle:
    """只组装已有四工具，不执行命令、不改文件、不请求模型。"""
    if isinstance(allowed_files,(str,bytes)):
        raise ValueError("允许文件清单必须是路径序列")

    executors = {
    "list_files":ListFilesExecutor(workdir),
    "read_file":ReadFileExecutor(workdir),
    "edit_file":EditFileExecutor(EditPolicy(workdir,allowed_files)),
    "run_tests":RunTestsExecutor(workdir,test_command,evidence_dir),
    }

    return ToolBundle(
        executor=ToolRouter(executors),
        definitions=[tool.definition for tool in executors.values()],  # 从同一批执行器收集模型可见定义
        read_only_tools=frozenset({"list_files", "read_file"}),  # 使用真实工具名标记只读能力
    )
