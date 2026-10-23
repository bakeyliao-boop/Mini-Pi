"""D13-A：先独立验证循环对 error/aborted 的决策，不依赖供应商接线。

模拟模型明确给出停止原因，真实文件确认错误回复中的调用没有执行。
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy
from mini_pi.tools.read_file import ReadFileExecutor
from mini_pi.tools.tool_router import ToolRouter


class LoopModelStopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_model_stop_", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / "sample.py"
        self.target.write_bytes(b"value = 1\n")
        self.reader = ReadFileExecutor(self.root)
        self.editor = EditFileExecutor(EditPolicy(self.root, ["sample.py"]))
        self.router = ToolRouter({"read_file": self.reader, "edit_file": self.editor})
        self.store = SessionStore(self.root / "session.jsonl")

    async def check_stop(self, reason, *, with_call=False, prior_read=False):
        call = ToolCall("edit_blocked", "edit_file", {
            "path": "sample.py", "old_text": "value = 1", "new_text": "value = 2",
        })
        stopped = Message(
            "assistant", "保留的模型回复。", [call] if with_call else [],
            stop_reason=reason, error_message="受控停止说明",
        )
        steps = []
        if prior_read:
            steps.append(Message("assistant", "先读取。", [
                ToolCall("read_done", "read_file", {"path": "sample.py"}),
            ]))
        steps.extend([stopped, Message("assistant", "这次请求不应发生。")])
        provider = MockProvider(steps)
        with patch.object(self.router, "execute", wraps=self.router.execute) as execute:
            result = await run_loop(
                provider, self.router, [Message("user", "检查模型停止状态。")],
                [self.reader.definition, self.editor.definition], self.store,
            )
        expected = "cancelled" if reason == "aborted" else "error"
        self.assertEqual(result.status, expected)
        self.assertEqual(result.error, "受控停止说明")
        self.assertIsNone(result.task_passed)
        self.assertEqual(len(provider.requests), 2 if prior_read else 1)
        self.assertEqual([item.args[0].id for item in execute.await_args_list], ["read_done"] if prior_read else [])
        self.assertEqual(self.target.read_bytes(), b"value = 1\n")
        loaded = self.store.load()
        self.assertEqual(loaded.history, result.messages)
        self.assertEqual(loaded.history[-1], stopped)
        ends = [row["data"] for row in loaded.records if row["type"] == "run_end"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]["status"], expected)
        self.assertEqual(ends[0]["error"], result.error)
        feedback = [item for item in result.messages if isinstance(item, ToolResult)]
        self.assertEqual([item.tool_call_id for item in feedback], ["read_done"] if prior_read else [])

    async def test_error_message_finishes_as_error(self):
        await self.check_stop("error")

    async def test_error_message_never_executes_its_tool_calls(self):
        await self.check_stop("error", with_call=True)

    async def test_aborted_message_never_executes_its_tool_calls(self):
        await self.check_stop("aborted", with_call=True)

    async def test_completed_result_is_preserved_before_later_error(self):
        await self.check_stop("error", prior_read=True)


if __name__ == "__main__":
    unittest.main()
