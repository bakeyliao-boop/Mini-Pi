"""D18：模拟模型和真实临时目录验证 list_files 的执行前规则。"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore
from mini_pi.tools.list_files import ListFilesExecutor
from mini_pi.tools.tool_router import ToolRouter


class ListHookTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="d18-list-hook-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "sample.txt").write_text("sample", encoding="utf-8")
        self.tool = ListFilesExecutor(self.workspace)
        self.router = ToolRouter({"list_files": self.tool})
        self.store = SessionStore(self.root / "session.jsonl", "d18-list")

    async def run_case(self, arguments, rule):
        call = ToolCall("list-1", "list_files", arguments)
        model = MockProvider([Message("assistant", "列出文件", [call]), Message("assistant", "收到结果")])
        result = await run_loop(model, self.router, [Message("user", "检查目录")], [self.tool.definition],
                                session_store=self.store, before_tool_call=rule)
        self.assertEqual(result.status, "finished")
        output = next(item for item in model.requests[1] if isinstance(item, ToolResult))
        self.assertEqual(output.tool_call_id, "list-1")
        self.assertIn(output, self.store.load().history)
        return output

    async def test_allowed_default_arguments_are_visible_to_rule_and_directory_is_listed(self):
        rule = AsyncMock(return_value=None)
        output = await self.run_case({}, rule)
        self.assertEqual(rule.await_args.args[0].arguments, {"path": ".", "limit": 500})
        self.assertIn("sample.txt", output.output)
        self.assertIsNone(output.error)

    async def test_rejected_call_does_not_scan_and_reason_reaches_model(self):
        rule = AsyncMock(return_value="规则禁止列目录")
        with patch.object(self.tool, "collect_names", wraps=self.tool.collect_names) as scan:
            output = await self.run_case({}, rule)
        scan.assert_not_called()
        self.assertEqual(output.error, "执行前规则拒绝：规则禁止列目录")

    async def test_bad_arguments_never_invoke_rule_or_scan(self):
        rule = AsyncMock(return_value=None)
        with patch.object(self.tool, "collect_names", wraps=self.tool.collect_names) as scan:
            output = await self.run_case({"limit": True}, rule)
        rule.assert_not_awaited()
        scan.assert_not_called()
        self.assertIn("limit", output.error)

    async def test_allow_rule_still_rejects_path_outside_workspace(self):
        rule = AsyncMock(return_value=None)
        with patch.object(self.tool, "collect_names", wraps=self.tool.collect_names) as scan:
            output = await self.run_case({"path": "../"}, rule)
        rule.assert_awaited_once()
        scan.assert_not_called()
        self.assertIsNotNone(output.error)

    async def run_interrupted_case(self, rule, *, timeout=None):
        call = ToolCall("list-1", "list_files", {})
        model = MockProvider([Message("assistant", "列出文件", [call])])
        result = await run_loop(model, self.router, [Message("user", "检查目录")], [self.tool.definition],
                                session_store=self.store, before_tool_call=rule, total_timeout_seconds=timeout)
        return result, model

    async def test_cancel_after_rule_does_not_start_listing(self):
        async def cancel_rule(_call):
            asyncio.current_task().cancel()
            return None
        with patch.object(self.tool, "collect_names", wraps=self.tool.collect_names) as scan:
            result, model = await asyncio.create_task(self.run_interrupted_case(cancel_rule))
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(len(model.requests), 1)
        scan.assert_not_called()

    async def test_deadline_after_rule_does_not_start_listing(self):
        async def slow_rule(_call):
            time.sleep(0.3)  # 规则耗时跨过同一运行截止时间
            return None
        with patch.object(self.tool, "collect_names", wraps=self.tool.collect_names) as scan:
            result, model = await self.run_interrupted_case(slow_rule, timeout=0.15)
        self.assertEqual(result.status, "timeout")
        self.assertEqual(len(model.requests), 1)
        scan.assert_not_called()
