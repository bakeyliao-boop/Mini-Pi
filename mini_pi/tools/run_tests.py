"""D09：按程序预设的参数数组运行测试，模型不能指定命令。"""

import json
import math
import subprocess
import time
from uuid import uuid4
from collections.abc import Sequence
from pathlib import Path

from mini_pi.models import ToolCall, ToolDefinition, ToolResult
from mini_pi.tools.managed_process import run_managed_process


class RunTestsExecutor:
    """测试命令由程序配置；学习者分段实现校验、执行与结果反馈。"""

    def __init__(
        self,
        workdir: str | Path,
        command: Sequence[str],
        evidence_dir: str | Path,
        timeout_seconds: float = 30.0,
        max_output_chars: int = 4000,
    ):
        self.workdir = Path(workdir).resolve()
        if not self.workdir.is_dir():
            raise ValueError("工作目录必须是已存在的目录")
        if isinstance(command, (str, bytes)) or not command or any(
            not isinstance(part, str) or not part for part in command
        ):
            raise ValueError("固定测试命令必须是非空字符串参数数组")
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("测试超时必须是正数")
        if type(max_output_chars) is not int or max_output_chars <= 0:
            raise ValueError("模型可见输出上限必须是正整数")

        self.command = tuple(command)
        self.evidence_dir = Path(evidence_dir).resolve()
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars
        self.definition = ToolDefinition(
            name="run_tests",
            description="运行程序预设的测试命令；不接受模型提供的命令或其他参数。",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        )

    async def execute(self, call: ToolCall) -> ToolResult:
        """校验空参数，执行固定命令，并反馈退出码、耗时与测试输出。"""
        if call.name != self.definition.name:
            return self._error(call, f"不支持的工具：{call.name}")
        if not isinstance(call.arguments, dict) or call.arguments:
            return self._error(call, "参数错误：run_tests 不接受参数")

        # 命令由构造函数固定，模型只能请求运行，不能选择运行什么。
        started = time.monotonic()
        try:
            completed = await run_managed_process(
                self.command,
                cwd=self.workdir,
                timeout=self.timeout_seconds,
                evidence_dir=self.evidence_dir,
            )
            exit_code = completed.returncode
            raw_output = completed.stdout or b""
            outcome = "tests_passed" if exit_code == 0 else "tests_failed"
        except subprocess.TimeoutExpired as error:
            exit_code = None
            raw_output = error.stdout or b""
            outcome = "timeout"
        except OSError as error:
            exit_code = None
            raw_output = str(error).encode("utf-8")
            outcome = "execution_error"

        elapsed_seconds = time.monotonic() - started
        full_output = raw_output.decode("utf-8", errors="replace")
        truncated = len(full_output) > self.max_output_chars
        visible_output = full_output[-self.max_output_chars:] if truncated else full_output
        payload = {
            "outcome": outcome,
            "exit_code": exit_code,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "output": visible_output,
            "truncated": truncated,
            "full_output_path": None,
        }

        # 完整输出留在本地；模型只接收有长度上限的片段和证据路径。
        try:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            output_path = self.evidence_dir / f"run-tests-{uuid4().hex}.txt"
            output_path.write_text(full_output, encoding="utf-8", newline="")
            payload["full_output_path"] = str(output_path)
        except OSError as error:
            return ToolResult(
                call.id,
                call.name,
                output=json.dumps(payload, ensure_ascii=False),
                error=f"执行失败：保存测试输出失败：{error}",
            )

        # 非零退出码是测试结论，测试工具本身已正常执行。
        tool_error = None
        if outcome == "timeout":
            tool_error = f"超时：测试超过 {self.timeout_seconds} 秒"
        elif outcome == "execution_error":
            tool_error = f"执行失败：{full_output}"
        return ToolResult(
            call.id,
            call.name,
            output=json.dumps(payload, ensure_ascii=False),
            error=tool_error,
        )

    @staticmethod
    def _error(call: ToolCall, reason: str) -> ToolResult:
        return ToolResult(call.id, call.name, output="", error=reason)
