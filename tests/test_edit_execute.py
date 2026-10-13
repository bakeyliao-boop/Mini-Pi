"""D08：统一工具入口与 D06 反馈链验证；不调用模型服务。"""

import asyncio
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy


class EditExecuteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parent
        self.temp = TemporaryDirectory(prefix="_edit_execute_", dir=parent)
        self.workspace = Path(self.temp.name).resolve()
        self.workspace.relative_to(parent)
        self.addCleanup(self.temp.cleanup)
        self.target = self.workspace / "discount.py"
        self.first = "def discount_amount(price, rate):\n    return price * rate\n\n"
        self.old = "def final_price(price, rate):\n    return price * rate"
        self.new = "def final_price(price, rate):\n    return price * (1 - rate)"
        self.original = (self.first + self.old + "\n").encode("utf-8")
        self.expected = (self.first + self.new + "\n").encode("utf-8")
        self.target.write_bytes(self.original)
        policy = EditPolicy(self.workspace, ["discount.py", "missing.py", "nested"])
        self.executor = EditFileExecutor(policy)
        self.arguments = {"path": "discount.py", "old_text": self.old, "new_text": self.new}

    async def test_success_returns_matching_result_and_diff_after_real_write(self):
        call = ToolCall("call_001", "edit_file", self.arguments)
        result = await self.executor.execute(call)
        self.assertIsInstance(result, ToolResult)
        self.assertEqual(result.tool_call_id, call.id)
        self.assertEqual(result.tool_name, call.name)
        self.assertIsNone(result.error)
        self.assertIn("--- a/discount.py", result.output)
        self.assertIn("+++ b/discount.py", result.output)
        self.assertIn("-    return price * rate", result.output)
        self.assertIn("+    return price * (1 - rate)", result.output)
        self.assertEqual(self.target.read_bytes(), self.expected)

    async def test_expected_call_and_filesystem_failures_return_errors_without_writes(self):
        (self.workspace / "nested").mkdir()
        calls = (
            ToolCall("bad_name", "unknown_tool", self.arguments),
            ToolCall("bad_type", "edit_file", dict(self.arguments, path=123)),
            ToolCall("missing", "edit_file", dict(self.arguments, path="missing.py")),
            ToolCall("directory", "edit_file", dict(self.arguments, path="nested")),
            ToolCall("unlisted", "edit_file", dict(self.arguments, path="settings.py")),
            ToolCall("missing_text", "edit_file", dict(self.arguments, old_text="missing text")),
            ToolCall("ambiguous", "edit_file", dict(self.arguments, old_text="return price * rate")),
            ToolCall("no_change", "edit_file", dict(self.arguments, new_text=self.old)),
        )
        for call in calls:
            with self.subTest(call_id=call.id):
                result = await self.executor.execute(call)
                self.assertEqual(result.tool_call_id, call.id)
                self.assertEqual(result.tool_name, call.name)
                self.assertEqual(result.output, "")
                self.assertTrue(result.error)
                self.assertEqual(self.target.read_bytes(), self.original)

    async def test_real_read_only_refusal_is_returned_as_an_error_result(self):
        original_mode = self.target.stat().st_mode
        try:
            self.target.chmod(stat.S_IREAD)
            if os.access(self.target, os.R_OK | os.W_OK):
                self.skipTest("当前进程仍有读写权限，不能验证真实权限拒绝")
            call = ToolCall("read_only", "edit_file", self.arguments)
            result = await self.executor.execute(call)
            self.assertEqual(result.tool_call_id, call.id)
            self.assertTrue(result.error)
            self.assertEqual(result.output, "")
            self.assertEqual(self.target.read_bytes(), self.original)
        finally:
            self.target.chmod(original_mode)

    async def test_write_refusal_is_reported_without_a_success_result(self):
        # 注入写入开始前的失败，不声称覆盖部分写入恢复或真实 ACL 改动。
        call = ToolCall("write_refused", "edit_file", self.arguments)
        with patch.object(Path, "write_bytes", side_effect=PermissionError("模拟实际写入拒绝")):
            result = await self.executor.execute(call)
        self.assertEqual(result.tool_call_id, call.id)
        self.assertEqual(result.output, "")
        self.assertIn("模拟实际写入拒绝", result.error or "")
        self.assertEqual(self.target.read_bytes(), self.original)

    async def test_loop_receives_error_and_success_then_sends_both_to_next_request(self):
        bad = ToolCall("call_bad", "edit_file", dict(self.arguments, path=123))
        good = ToolCall("call_good", "edit_file", self.arguments)
        request = Message("assistant", "先处理两个编辑调用。", [bad, good])
        user = Message("user", "编辑 discount.py。")

        def answer(history, tools):
            self.assertEqual(history[:2], [user, request])
            results = history[2:]
            self.assertEqual(len(results), 2)
            self.assertTrue(all(isinstance(item, ToolResult) for item in results))
            self.assertEqual([item.tool_call_id for item in results], [bad.id, good.id])
            self.assertTrue(results[0].error)
            self.assertIsNone(results[1].error)
            self.assertIn("+    return price * (1 - rate)", results[1].output)
            self.assertEqual(tools, [self.executor.definition])
            self.assertEqual(self.target.read_bytes(), self.expected)
            return Message("assistant", "已收到编辑结果，本次尚未运行业务测试。")

        provider = MockProvider([request, answer])
        run = await asyncio.wait_for(
            run_loop(provider, self.executor, [user], [self.executor.definition]),
            timeout=3,
        )
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(run.status, "finished")
        self.assertIsNone(run.task_passed)
        self.assertEqual(self.target.read_bytes(), self.expected)


if __name__ == "__main__":
    unittest.main()
