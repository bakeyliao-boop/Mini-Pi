from pathlib import Path

from mini_pi.models import ToolCall


def protect_login_test(workdir: str | Path):
    protected_file = (Path(workdir) / "tests/test_login.py").resolve()  # 要保护的文件

    async def rule(call: ToolCall) -> str | None:
        if call.name != "edit_file":  # 不是编辑工具
            return None  # 允许继续

        requested_file = (Path(workdir) / call.arguments["path"]).resolve()  # 请求编辑的文件
        if requested_file == protected_file:  # 命中了受保护的文件
            return "不能修改登录验收测试"  # 规则只说明具体原因

        return None  # 其他文件允许继续

    return rule  # 返回规则，供调用方配置
