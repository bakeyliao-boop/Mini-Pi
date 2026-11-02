"""D18：使用模拟模型和真实受控进程验证 run_tests 的执行前规则。"""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore
from mini_pi.tools.run_tests import RunTestsExecutor
from mini_pi.tools.tool_router import ToolRouter


class RunTestsHookTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="d18-run-tests-hook-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.marker = self.workspace / "started.txt"
        script = "from pathlib import Path; Path('started.txt').write_text('started'); print('test passed')"
        self.tool = RunTestsExecutor(
            self.workspace, (sys.executable, "-c", script), self.root / "evidence"
        )
        self.router = ToolRouter({"run_tests": self.tool})
        self.store = SessionStore(self.root / "session.jsonl", "d18-run-tests")

    async def run_case(self, arguments, rule):
        call = ToolCall("test-1", "run_tests", arguments)
        model = MockProvider([
            Message("assistant", "运行测试", [call]),
            Message("assistant", "收到测试结果"),
        ])
        result = await run_loop(
            model, self.router, [Message("user", "运行测试")], [self.tool.definition],
            session_store=self.store, before_tool_call=rule,
        )
        self.assertEqual(result.status, "finished")
        output = next(item for item in model.requests[1] if isinstance(item, ToolResult))
        self.assertEqual((output.tool_call_id, output.tool_name), ("test-1", "run_tests"))
        self.assertIn(output, self.store.load().history)
        return output

    async def test_rule_allows_fixed_command_and_result_reaches_model(self):
        rule = AsyncMock(return_value=None)
        output = await self.run_case({}, rule)

        rule.assert_awaited_once()
        self.assertEqual(rule.await_args.args[0].arguments, {})
        self.assertTrue(self.marker.exists())
        self.assertIsNone(output.error)
        payload = json.loads(output.output)
        self.assertEqual(payload["outcome"], "tests_passed")
        self.assertIn("test passed", payload["output"])

    async def test_rule_rejection_never_starts_process_and_reason_reaches_model(self):
        rule = AsyncMock(return_value="规则禁止运行测试")
        with patch("mini_pi.tools.run_tests.run_managed_process", new_callable=AsyncMock) as process:
            output = await self.run_case({}, rule)

        rule.assert_awaited_once()
        process.assert_not_awaited()
        self.assertFalse(self.marker.exists())
        self.assertEqual(output.error, "执行前规则拒绝：规则禁止运行测试")

    async def test_bad_arguments_never_reach_rule_or_start_process(self):
        rule = AsyncMock(return_value=None)
        with patch("mini_pi.tools.run_tests.run_managed_process", new_callable=AsyncMock) as process:
            output = await self.run_case({"command": "different command"}, rule)

        rule.assert_not_awaited()
        process.assert_not_awaited()
        self.assertFalse(self.marker.exists())
        self.assertIn("参数错误", output.error)

    async def test_original_execute_still_runs_fixed_command(self):
        output = await self.tool.execute(ToolCall("direct-1", "run_tests", {}))

        self.assertTrue(self.marker.exists())
        self.assertIsNone(output.error)
        self.assertEqual(json.loads(output.output)["outcome"], "tests_passed")


if __name__ == "__main__":
    unittest.main()
