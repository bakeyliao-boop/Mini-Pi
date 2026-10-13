"""D09：真实本地工具、未知工具和 D06 循环通过同一入口分发。"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy
from mini_pi.tools.read_file import ReadFileExecutor
from mini_pi.tools.tool_router import ToolRouter


class ToolRouterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parent
        self.temp = TemporaryDirectory(prefix="_d09_router_", dir=parent)
        self.workspace = Path(self.temp.name).resolve()
        self.workspace.relative_to(parent)
        self.addCleanup(self.temp.cleanup)
        self.target = self.workspace / "discount.py"
        self.original = "def final_price(price, rate):\n    return price * rate\n"
        self.expected = "def final_price(price, rate):\n    return price * (1 - rate)\n"
        self.target.write_bytes(self.original.encode("utf-8"))
        self.reader = ReadFileExecutor(self.workspace)
        self.editor = EditFileExecutor(EditPolicy(self.workspace, ["discount.py"]))
        self.router = ToolRouter({"read_file": self.reader, "edit_file": self.editor})

    def edit_call(self, call_id: str) -> ToolCall:
        return ToolCall(call_id, "edit_file", {
            "path": "discount.py",
            "old_text": "return price * rate",
            "new_text": "return price * (1 - rate)",
        })

    async def test_known_names_reach_different_real_tools(self):
        read_call = ToolCall("call_read", "read_file", {"path": "discount.py"})
        edit_call = self.edit_call("call_edit")
        read_result = await self.router.execute(read_call)
        edit_result = await self.router.execute(edit_call)
        self.assertEqual((read_result.tool_call_id, read_result.tool_name), ("call_read", "read_file"))
        self.assertEqual(read_result.output, self.original)
        self.assertIsNone(read_result.error)
        self.assertEqual((edit_result.tool_call_id, edit_result.tool_name), ("call_edit", "edit_file"))
        self.assertIn("+    return price * (1 - rate)", edit_result.output)
        self.assertIsNone(edit_result.error)
        self.assertEqual(self.target.read_bytes(), self.expected.encode("utf-8"))

    async def test_unknown_name_returns_paired_error_without_writing(self):
        call = ToolCall("call_unknown", "delete_file", {"path": "discount.py"})
        result = await self.router.execute(call)
        self.assertIsInstance(result, ToolResult)
        self.assertEqual((result.tool_call_id, result.tool_name), (call.id, call.name))
        self.assertEqual(result.output, "")
        self.assertIn("未知工具", result.error or "")
        self.assertEqual(self.target.read_bytes(), self.original.encode("utf-8"))

    async def test_one_loop_turn_routes_read_edit_and_unknown_then_feeds_results_back(self):
        read_call = ToolCall("call_001", "read_file", {"path": "discount.py"})
        edit_call = self.edit_call("call_002")
        unknown_call = ToolCall("call_003", "delete_file", {"path": "discount.py"})
        request = Message("assistant", "依次读取、编辑、尝试未知工具。", [read_call, edit_call, unknown_call])
        user = Message("user", "修改折扣函数。")

        def answer(history, tools):
            self.assertEqual(history[:2], [user, request])
            results = history[2:]
            self.assertEqual(len(results), 3)
            self.assertTrue(all(isinstance(item, ToolResult) for item in results))
            self.assertEqual([item.tool_call_id for item in results], ["call_001", "call_002", "call_003"])
            self.assertEqual(results[0].output, self.original)
            self.assertIn("+    return price * (1 - rate)", results[1].output)
            self.assertIn("未知工具", results[2].error or "")
            self.assertEqual(self.target.read_bytes(), self.expected.encode("utf-8"))
            self.assertEqual(tools, [self.reader.definition, self.editor.definition])
            return Message("assistant", "已收到三个结果，还需要测试业务行为。")

        provider = MockProvider([request, answer])
        run = await asyncio.wait_for(
            run_loop(provider, self.router, [user], [self.reader.definition, self.editor.definition]),
            timeout=3,
        )
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(run.status, "finished")
        self.assertIsNone(run.task_passed)


if __name__ == "__main__":
    unittest.main()
