"""检验实际规则与工具、模型请求及会话记录的衔接。"""

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from examples.d18_test_protection import protect_login_test
from mini_pi.bootstrap import build_tools
from mini_pi.harness import Harness
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore


class LoginProtectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="d18-protection-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "tests").mkdir()
        self.protected = self.root / "tests" / "test_login.py"
        self.other = self.root / "app.py"
        self.protected.write_text("old\n", encoding="utf-8")
        self.other.write_text("old\n", encoding="utf-8")
        self.tools = build_tools(
            self.root, ["tests/test_login.py", "app.py"],
            [sys.executable, "-c", "pass"], self.root / "evidence",
        )
        self.editor = self.tools.executor.executors["edit_file"]
        self.rule = protect_login_test(self.root)
        self.runs = 0

    async def run_call(self, path, rule):
        self.runs += 1
        call = ToolCall(
            f"edit-{self.runs}", "edit_file",
            {"path": path, "old_text": "old", "new_text": "new"},
        )
        model = MockProvider([
            Message("assistant", "编辑文件", [call], stop_reason="toolUse"),
            Message("assistant", "收到结果", stop_reason="stop"),
        ])
        store = SessionStore(self.root / f"session-{self.runs}.jsonl", f"run-{self.runs}")
        harness = Harness(model, self.tools, before_tool_call=rule)
        result = await harness.run("处理登录", store)
        self.assertEqual(result.status, "finished")
        returned = next(item for item in model.requests[-1] if isinstance(item, ToolResult))
        self.assertEqual(returned.tool_call_id, call.id)
        self.assertIn(returned, store.load().history)
        return returned

    async def test_protected_file_and_equivalent_path_are_rejected(self):
        for path in ("tests/test_login.py", "./tests/test_login.py"):
            with self.subTest(path=path):
                with patch.object(self.editor, "_execute_validated", wraps=self.editor._execute_validated) as execute:
                    result = await self.run_call(path, self.rule)
                self.assertEqual(result.error, "执行前规则拒绝：不能修改登录验收测试")
                execute.assert_not_awaited()
                self.assertEqual(self.protected.read_text(encoding="utf-8"), "old\n")

    async def test_other_file_allowed_and_rule_can_be_disabled(self):
        allowed = await self.run_call("app.py", self.rule)
        self.assertIsNone(allowed.error)
        self.assertEqual(self.other.read_text(encoding="utf-8"), "new\n")
        self.assertEqual(self.protected.read_text(encoding="utf-8"), "old\n")

        disabled = await self.run_call("tests/test_login.py", None)
        self.assertIsNone(disabled.error)
        self.assertEqual(self.protected.read_text(encoding="utf-8"), "new\n")

    async def test_tool_failure_is_distinct_from_rule_rejection_in_saved_history(self):
        self.other.write_text("different\n", encoding="utf-8")
        with patch.object(self.editor, "_execute_validated", wraps=self.editor._execute_validated) as execute:
            result = await self.run_call("app.py", self.rule)
        execute.assert_awaited_once()
        self.assertEqual(result.error, "未找到代替换的旧文本")
        self.assertFalse(result.error.startswith("执行前规则拒绝："))
        self.assertEqual(self.other.read_text(encoding="utf-8"), "different\n")


if __name__ == "__main__":
    unittest.main()
