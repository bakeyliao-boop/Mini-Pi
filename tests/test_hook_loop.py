"""D18 运行循环的执行前规则：临时文件与模拟模型，无外部调用。"""

import asyncio
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolDefinition, ToolResult
from mini_pi.session_store import SessionStore
from mini_pi.tools.read_file import ReadFileExecutor
from mini_pi.tools.tool_router import ToolRouter


class LegacyTool:
    def __init__(self):
        self.execute = AsyncMock(side_effect=self._execute)

    async def _execute(self, call):
        return ToolResult(call.id, call.name, "旧工具成功")


class LoopHookTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="mini-pi-d18-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "sample.txt").write_text("临时文件内容", encoding="utf-8")
        self.reader = ReadFileExecutor(self.root)
        self.legacy = LegacyTool()
        self.router = ToolRouter({"read_file": self.reader, "legacy": self.legacy})
        self.call = ToolCall("read-1", "read_file", {"path": "sample.txt"})
        self.session = SessionStore(self.root / "session.jsonl", "run")

    async def run_case(self, call=None, *, rule=None, timeout=None):
        call = call if call is not None else self.call
        provider = MockProvider([
            Message("assistant", "调用工具", [call], stop_reason="toolUse"),
            Message("assistant", "已收到工具反馈", stop_reason="stop"),
        ])
        tools = [self.reader.definition, ToolDefinition("legacy", "旧接口测试工具", {"type": "object"})]
        result = await run_loop(provider, self.router, [Message("user", "处理样例")], tools,
                                session_store=self.session, before_tool_call=rule,
                                total_timeout_seconds=timeout)
        return result, provider

    def tool_result(self, provider):
        self.assertEqual(len(provider.requests), 2)
        results = [item for item in provider.requests[1] if isinstance(item, ToolResult)]
        self.assertEqual(len(results), 1)
        return results[0]

    async def test_rejected_call_does_not_read_and_reason_reaches_model(self):
        rule = AsyncMock(return_value="规则不允许读取")
        with patch.object(self.reader, "_execute_validated", wraps=self.reader._execute_validated) as read:
            result, provider = await self.run_case(rule=rule)
        self.assertEqual(result.status, "finished")
        read.assert_not_awaited()
        rule.assert_awaited_once()
        tool_result = self.tool_result(provider)
        self.assertEqual((tool_result.tool_call_id, tool_result.error), ("read-1", "执行前规则拒绝：规则不允许读取"))
        self.assertIn(tool_result, self.session.load().history)

    async def test_allowed_call_really_reads_temporary_file(self):
        rule = AsyncMock(return_value=None)
        with patch.object(self.reader, "_execute_validated", wraps=self.reader._execute_validated) as read:
            result, provider = await self.run_case(rule=rule)
        self.assertEqual(result.status, "finished")
        rule.assert_awaited_once()
        read.assert_awaited_once()
        tool_result = self.tool_result(provider)
        self.assertEqual((tool_result.tool_call_id, tool_result.output, tool_result.error),
                         ("read-1", "临时文件内容", None))

    async def test_no_rule_preserves_legacy_tool(self):
        call = ToolCall("legacy-1", "legacy", {})
        result, provider = await self.run_case(call=call)
        self.assertEqual(result.status, "finished")
        self.legacy.execute.assert_awaited_once_with(call)
        self.assertEqual(self.tool_result(provider).output, "旧工具成功")

    async def test_invalid_arguments_do_not_start_rule_or_tool(self):
        rule = AsyncMock(return_value=None)
        call = ToolCall("bad-1", "read_file", {"path": 123})
        with patch.object(self.reader, "_execute_validated", wraps=self.reader._execute_validated) as read:
            result, provider = await self.run_case(call=call, rule=rule)
        self.assertEqual(result.status, "finished")
        rule.assert_not_awaited()
        read.assert_not_awaited()
        item = self.tool_result(provider)
        self.assertEqual(item.tool_call_id, "bad-1")
        self.assertIn("path 必须是非空字符串", item.error)

    async def test_unadapted_tool_is_denied_when_rule_enabled(self):
        rule = AsyncMock(return_value=None)
        call = ToolCall("legacy-1", "legacy", {})
        result, provider = await self.run_case(call=call, rule=rule)
        self.assertEqual(result.status, "finished")
        rule.assert_not_awaited()
        self.legacy.execute.assert_not_awaited()
        item = self.tool_result(provider)
        self.assertEqual(item.tool_call_id, "legacy-1")
        self.assertTrue(item.error)

    async def test_cancellation_after_rule_stops_tool(self):
        async def rule(_call):
            asyncio.current_task().cancel()
            return None
        with patch.object(self.reader, "_execute_validated", wraps=self.reader._execute_validated) as read:
            task = asyncio.create_task(self.run_case(rule=rule))
            result, provider = await task
        self.assertEqual(result.status, "cancelled")
        read.assert_not_awaited()
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(self.session.load().records[-1]["data"]["status"], "cancelled")

    async def test_deadline_after_rule_stops_tool(self):
        async def rule(_call):
            time.sleep(0.2)  # 模拟规则同步耗时越过同一运行截止时间。
            return None
        with patch.object(self.reader, "_execute_validated", wraps=self.reader._execute_validated) as read:
            result, provider = await self.run_case(rule=rule, timeout=0.1)
        self.assertEqual(result.status, "timeout")
        read.assert_not_awaited()
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(self.session.load().records[-1]["data"]["status"], "timeout")


if __name__ == "__main__":
    unittest.main(verbosity=2)
