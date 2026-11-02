"""D18：使用真实临时文件和模拟规则验证执行前检查。"""

import asyncio
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import mini_pi.tool_hooks as hooks
from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.run_deadline import RunDeadlineExceeded
from mini_pi.session_store import SessionStore
from mini_pi.tools.read_file import ReadFileExecutor
from mini_pi.tools.tool_router import ToolRouter


class LegacyExecutor:
    def __init__(self):
        self.execute = AsyncMock(side_effect=self._execute)

    async def _execute(self, call):
        return ToolResult(call.id, call.name, output="旧入口正常")


class ExecuteToolWithRuleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="d18-rule-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "safe.txt").write_text("安全文件内容", encoding="utf-8")
        (self.root / "other.txt").write_text("另一个文件", encoding="utf-8")
        self.reader = ReadFileExecutor(self.root)
        self.router = ToolRouter({"read_file": self.reader})
        self.call = ToolCall("read-1", "read_file", {"path": "safe.txt"})

    async def test_denial_reaches_next_model_request_and_saved_history(self):
        model = MockProvider([
            Message("assistant", "读取文件", [self.call]),
            Message("assistant", "已收到拒绝原因", stop_reason="stop"),
        ])
        rule = AsyncMock(return_value="规则禁止读取该文件")
        store = SessionStore(self.root / "session.jsonl", "rule-run")
        with patch.object(self.reader, "_execute_validated", wraps=self.reader._execute_validated) as read:
            result = await run_loop(
                model, self.router, [Message("user", "读取文件")], [self.reader.definition],
                session_store=store, before_tool_call=rule,
            )
        read.assert_not_awaited()
        self.assertEqual(result.status, "finished")
        self.assertEqual(len(model.requests), 2)
        seen = next(item for item in model.requests[1] if isinstance(item, ToolResult))
        self.assertEqual((seen.tool_call_id, seen.error), ("read-1", "执行前规则拒绝：规则禁止读取该文件"))
        self.assertIn(seen, store.load().history)

    async def test_allow_executes_real_read_once_after_rule(self):
        rule = AsyncMock(return_value=None)
        with patch.object(self.reader, "_execute_validated", wraps=self.reader._execute_validated) as read:
            result = await hooks.execute_tool_with_rule(self.router, self.call, rule, None)
        rule.assert_awaited_once()
        read.assert_awaited_once()
        self.assertEqual(result.tool_call_id, "read-1")
        self.assertEqual(result.tool_name, "read_file")
        self.assertIsNone(result.error)
        self.assertEqual(result.output, "安全文件内容")

    async def test_deny_returns_reason_with_original_id_and_never_reads(self):
        rule = AsyncMock(return_value="规则禁止读取该文件")
        with patch.object(self.reader, "_execute_validated", wraps=self.reader._execute_validated) as read:
            result = await hooks.execute_tool_with_rule(self.router, self.call, rule, None)
        rule.assert_awaited_once()
        read.assert_not_awaited()
        self.assertEqual(result.tool_call_id, "read-1")
        self.assertEqual(result.tool_name, "read_file")
        self.assertEqual(result.error, "执行前规则拒绝：规则禁止读取该文件")
        self.assertEqual(result.output, "")

    async def test_invalid_arguments_never_call_rule_or_read(self):
        call = ToolCall("bad-1", "read_file", {"path": 123})
        rule = AsyncMock(return_value=None)
        with patch.object(self.reader, "_execute_validated", wraps=self.reader._execute_validated) as read:
            result = await hooks.execute_tool_with_rule(self.router, call, rule, None)
        rule.assert_not_awaited()
        read.assert_not_awaited()
        self.assertEqual(result.tool_call_id, "bad-1")
        self.assertIn("path 必须是非空字符串", result.error or "")

    async def test_unadapted_tool_does_not_bypass_enabled_rule(self):
        legacy = LegacyExecutor()
        router = ToolRouter({"legacy": legacy})
        call = ToolCall("legacy-1", "legacy", {})
        rule = AsyncMock(return_value=None)
        result = await hooks.execute_tool_with_rule(router, call, rule, None)
        rule.assert_not_awaited()
        legacy.execute.assert_not_awaited()
        self.assertEqual(result.tool_call_id, "legacy-1")
        self.assertTrue(result.error)

    async def test_rule_error_returns_tool_error_and_never_reads(self):
        rule = AsyncMock(side_effect=ValueError("模拟规则错误"))
        with patch.object(self.reader, "_execute_validated", wraps=self.reader._execute_validated) as read:
            result = await hooks.execute_tool_with_rule(self.router, self.call, rule, None)
        read.assert_not_awaited()
        self.assertEqual(result.tool_call_id, "read-1")
        self.assertTrue(result.error)

    async def test_rule_mutation_cannot_change_validated_execution(self):
        async def mutate(call):
            call.id = "changed-id"
            call.arguments["path"] = "other.txt"
            return None
        result = await hooks.execute_tool_with_rule(self.router, self.call, mutate, None)
        self.assertEqual(result.tool_call_id, "read-1")
        self.assertEqual(result.output, "安全文件内容")
        self.assertEqual(self.call.id, "read-1")
        self.assertEqual(self.call.arguments, {"path": "safe.txt"})

    async def test_rule_requests_cancel_before_tool_start(self):
        async def cancel_after_rule(_call):
            asyncio.current_task().cancel()
            return None
        with patch.object(self.reader, "_execute_validated", wraps=self.reader._execute_validated) as read:
            task = asyncio.create_task(hooks.execute_tool_with_rule(self.router, self.call, cancel_after_rule, None))
            with self.assertRaises(asyncio.CancelledError):
                await task
        read.assert_not_awaited()

    async def test_elapsed_deadline_after_rule_prevents_tool_start(self):
        async def cross_deadline(_call):
            # 在规则内部同步消耗时间：验证规则返回后仍需检查同一截止时间。
            time.sleep(0.08)
            return None
        deadline = asyncio.get_running_loop().time() + 0.04
        with patch.object(self.reader, "_execute_validated", wraps=self.reader._execute_validated) as read:
            with self.assertRaises(RunDeadlineExceeded):
                await hooks.execute_tool_with_rule(self.router, self.call, cross_deadline, deadline)
        read.assert_not_awaited()

    async def test_without_rule_uses_legacy_executor(self):
        legacy = LegacyExecutor()
        call = ToolCall("legacy-1", "legacy", {})
        result = await hooks.execute_tool_with_rule(legacy, call, None, None)
        legacy.execute.assert_awaited_once_with(call)
        self.assertEqual(result.tool_call_id, "legacy-1")
        self.assertEqual(result.output, "旧入口正常")

    async def test_unrecognized_rule_output_never_reads(self):
        for value in ("", False, {"allow": True}):
            with self.subTest(value=value):
                rule = AsyncMock(return_value=value)
                with patch.object(self.reader, "_execute_validated", wraps=self.reader._execute_validated) as read:
                    result = await hooks.execute_tool_with_rule(self.router, self.call, rule, None)
                read.assert_not_awaited()
                self.assertEqual(result.tool_call_id, "read-1")
                self.assertTrue(result.error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
