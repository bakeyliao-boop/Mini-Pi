"""D18 上层规则转发：真实临时文件、模拟模型，无外部调用。"""

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from mini_pi.agent import Agent
from mini_pi.bootstrap import build_tools
from mini_pi.harness import Harness
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore


class HarnessHookTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="d18-harness-hook-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.target = self.root / "test_login.py"
        self.target.write_text("old\n", encoding="utf-8")
        self.tools = build_tools(self.root, ["test_login.py"], [sys.executable, "-c", "pass"], self.root / "evidence")
        self.editor = self.tools.executor.executors["edit_file"]
        self.call = ToolCall("edit-1", "edit_file", {"path": "test_login.py", "old_text": "old", "new_text": "new"})
        self.session_path = self.root / "session.jsonl"

    def provider(self):
        return MockProvider([
            Message("assistant", "编辑测试", [self.call], stop_reason="toolUse"),
            Message("assistant", "已收到结果", stop_reason="stop"),
        ])

    def saved_result(self, store, model):
        self.assertEqual(len(model.requests), 2)
        result = next(item for item in model.requests[-1] if isinstance(item, ToolResult))
        self.assertEqual(result.tool_call_id, "edit-1")
        self.assertIn(result, store.load().history)
        return result

    async def test_new_task_rule_denies_and_model_receives_reason(self):
        model = self.provider()
        rule = AsyncMock(return_value="规则禁止修改验收测试")
        harness = Harness(model, self.tools, before_tool_call=rule)
        store = SessionStore(self.session_path, "new")
        with patch.object(self.editor, "_execute_validated", wraps=self.editor._execute_validated) as write:
            result = await harness.run("处理登录", store)
        self.assertEqual(result.status, "finished")
        write.assert_not_awaited()
        rule.assert_awaited_once()
        self.assertEqual(self.target.read_text(encoding="utf-8"), "old\n")
        self.assertEqual(self.saved_result(store, model).error, "执行前规则拒绝：规则禁止修改验收测试")

    async def test_resume_rule_denies_and_model_receives_reason(self):
        old = SessionStore(self.session_path, "old")
        old.append_entry("run_start", {"status": "running"})
        old.append_item(Message("user", "排查登录"))
        old.append_item(Message("assistant", "稍后继续"))
        old.append_entry("run_end", {"status": "finished"})
        model = self.provider()
        rule = AsyncMock(return_value="规则禁止修改验收测试")
        harness = Harness(model, self.tools, before_tool_call=rule)
        store = SessionStore(self.session_path, "resume")
        with patch.object(self.editor, "_execute_validated", wraps=self.editor._execute_validated) as write:
            result = await harness.resume("继续处理", store)
        self.assertEqual(result.plan.state, "ready")
        self.assertEqual(result.run_result.status, "finished")
        write.assert_not_awaited()
        rule.assert_awaited_once()
        self.assertEqual(self.target.read_text(encoding="utf-8"), "old\n")
        self.assertEqual(self.saved_result(store, model).error, "执行前规则拒绝：规则禁止修改验收测试")

    async def test_allow_rule_edits_file(self):
        model = self.provider()
        rule = AsyncMock(return_value=None)
        harness = Harness(model, self.tools, before_tool_call=rule)
        store = SessionStore(self.session_path, "new")
        result = await harness.run("处理登录", store)
        self.assertEqual(result.status, "finished")
        rule.assert_awaited_once()
        self.assertEqual(self.target.read_text(encoding="utf-8"), "new\n")
        self.assertIsNone(self.saved_result(store, model).error)

    async def test_no_rule_keeps_existing_tool_behavior(self):
        model = self.provider()
        harness = Harness(model, self.tools)
        store = SessionStore(self.session_path, "new")
        result = await harness.run("处理登录", store)
        self.assertEqual(result.status, "finished")
        self.assertEqual(self.target.read_text(encoding="utf-8"), "new\n")
        self.assertIsNone(self.saved_result(store, model).error)

    async def test_invalid_rule_rejected_before_creating_session(self):
        model = self.provider()
        with self.assertRaisesRegex(ValueError, "before_tool_call"):
            Harness(model, self.tools, before_tool_call="不是规则")
        self.assertFalse(self.session_path.exists())
        self.assertEqual(model.requests, [])

    async def test_direct_agent_prompt_forwards_rule(self):
        model = self.provider()
        rule = AsyncMock(return_value="规则禁止修改验收测试")
        agent = Agent(model, self.tools.executor, self.tools.definitions)
        store = SessionStore(self.session_path, "agent")
        result = await agent.prompt([Message("user", "处理登录")], session_store=store, before_tool_call=rule)
        self.assertEqual(result.status, "finished")
        self.assertEqual(self.target.read_text(encoding="utf-8"), "old\n")
        rule.assert_awaited_once()
        self.assertEqual(self.saved_result(store, model).error, "执行前规则拒绝：规则禁止修改验收测试")


if __name__ == "__main__":
    unittest.main(verbosity=2)
