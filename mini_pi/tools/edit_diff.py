"""助手准备：将编辑前后的文本展示为差异，不读写文件。"""

from difflib import unified_diff


def render_edit_diff(path: str, before: str, after: str) -> str:
    """生成统一差异；保留行尾差别，并标出缺少末尾换行的行。"""
    lines = unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    parts: list[str] = []
    for line in lines:
        if line.endswith("\n"):
            parts.append(line)
        else:
            parts.append(line + "\n\\ No newline at end of file\n")
    return "".join(parts)
