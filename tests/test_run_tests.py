"""D09：实际启动固定测试进程，验证结果分类和完整输出证据。"""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.models import ToolCall
from mini_pi.tools.run_tests import RunTestsExecutor


class RunTestsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        test_parent = Path(__file__).resolve().parent
        self.temp = TemporaryDirectory(prefix="_run_tests_", dir=test_parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workdir = self.root / "workspace"
        self.workdir.mkdir()
        self.evidence_dir = self.root / "evidence"

    def executor(self, script: str, **options) -> RunTestsExecutor:
        return RunTestsExecutor(
            self.workdir,
            (sys.executable, "-X", "utf8", "-c", script),
            self.evidence_dir,
            **options,
        )

    async def test_success_returns_exit_code_output_and_elapsed_time(self):
        call = ToolCall("call_pass", "run_tests", {})
        result = await self.executor("print('tests passed')").execute(call)
        payload = json.loads(result.output)

        self.assertEqual((result.tool_call_id, result.tool_name), (call.id, call.name))
        self.assertIsNone(result.error)
        self.assertEqual(payload["outcome"], "tests_passed")
        self.assertEqual(payload["exit_code"], 0)
        self.assertIn("tests passed", payload["output"])
        self.assertGreaterEqual(payload["elapsed_seconds"], 0)
        self.assertFalse(payload["truncated"])
        self.assertEqual(
            Path(payload["full_output_path"]).read_text(encoding="utf-8"),
            "tests passed\n",
        )

    async def test_failing_assertion_is_test_feedback_not_tool_start_error(self):
        script = (
            "import sys; "
            "print('expected=80, actual=20'); "
            "print('assertion failed', file=sys.stderr); "
            "sys.exit(1)"
        )
        result = await self.executor(script).execute(ToolCall("call_fail", "run_tests", {}))
        payload = json.loads(result.output)

        self.assertEqual(payload["outcome"], "tests_failed")
        self.assertEqual(payload["exit_code"], 1)
        self.assertIn("expected=80, actual=20", payload["output"])
        self.assertIn("assertion failed", payload["output"])
        self.assertIsNone(result.error)

    async def test_timeout_is_distinct_from_failing_test(self):
        result = await self.executor(
            "import time; print('started', flush=True); time.sleep(2)",
            timeout_seconds=0.2,
        ).execute(ToolCall("call_timeout", "run_tests", {}))
        payload = json.loads(result.output)

        self.assertEqual(payload["outcome"], "timeout")
        self.assertIsNone(payload["exit_code"])
        self.assertIn("超时", result.error or "")
        self.assertTrue(Path(payload["full_output_path"]).exists())

    async def test_missing_executable_is_execution_error(self):
        executor = RunTestsExecutor(
            self.workdir,
            (str(self.workdir / "missing-test-program.exe"),),
            self.evidence_dir,
        )
        result = await executor.execute(ToolCall("call_start", "run_tests", {}))
        payload = json.loads(result.output)

        self.assertEqual(payload["outcome"], "execution_error")
        self.assertIsNone(payload["exit_code"])
        self.assertIn("执行失败", result.error or "")

    async def test_truncated_model_output_keeps_complete_local_evidence(self):
        result = await self.executor(
            "print('z' * 200)", max_output_chars=25
        ).execute(ToolCall("call_long", "run_tests", {}))
        payload = json.loads(result.output)

        self.assertTrue(payload["truncated"])
        self.assertEqual(len(payload["output"]), 25)
        self.assertEqual(
            Path(payload["full_output_path"]).read_text(encoding="utf-8"),
            "z" * 200 + "\n",
        )

    async def test_model_supplied_command_is_rejected_before_process_start(self):
        executor = self.executor("print('must not run')")
        call = ToolCall("call_bad", "run_tests", {"command": "other command"})

        with patch("subprocess.run") as run:
            result = await executor.execute(call)

        run.assert_not_called()
        self.assertEqual(result.output, "")
        self.assertIn("参数错误", result.error or "")
        self.assertFalse(self.evidence_dir.exists())


if __name__ == "__main__":
    unittest.main()
