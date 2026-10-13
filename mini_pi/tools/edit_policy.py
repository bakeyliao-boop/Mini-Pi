"""D08：独立的编辑范围策略；配置由程序提供，路径检查由学习者迁移。"""

from collections.abc import Sequence
from pathlib import Path


class EditPolicy:
    """Mini-Pi 的工作目录和允许清单策略；不负责读取、替换或写入。"""

    def __init__(self, workdir: str | Path, allowed_files: Sequence[str]):
        # 助手准备：沿用现有构造配置，不增加文件名黑名单。
        self.workdir = Path(workdir).resolve()
        if not self.workdir.is_dir():
            raise ValueError("工作目录必须是已存在的目录")
        self.allowed_files: set[Path] = set()
        for name in allowed_files:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("允许清单必须包含非空相对文件路径")
            relative = Path(name)
            if relative.is_absolute() or relative.drive or ".." in relative.parts:
                raise ValueError("允许清单必须使用工作目录内的相对路径")
            self.allowed_files.add(relative)

    def resolve_edit_path(self, path: str) -> Path:
        """检查编辑范围，返回允许编辑的真实目标；不执行文件读写。"""
        relative = Path(path)
        if relative.is_absolute() or relative.drive:
            raise ValueError("编辑路径必须是相对路径")

        target = (self.workdir / relative).resolve()

        try:
            actual_relative = target.relative_to(self.workdir)  #a是否是b的子集
        except ValueError:
            raise ValueError("目标在工作目录之外")

        if actual_relative not in self.allowed_files:
            raise ValueError("目标不在被允许的编辑清单中")
        return target
