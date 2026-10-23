"""D13-A：先独立验收循环的 length 批次反馈，再放行真实适配器。

模拟模型直接返回带 length 的消息，使用真实临时文件和工具。
每个调用都应有未执行反馈；完整新调用才允许真正进入执行器。
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_recovery import find_pending_calls
from mini_pi.session_store import SessionStore
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy
from mini_pi.tools.read_file import ReadFileExecutor
from mini_pi.tools.tool_router import ToolRouter


class LoopTruncatedBatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_length_loop_", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / "sample.py"
        self.before = b"value = 1\n"
        self.after = b"value = 2\n"
        self.target.write_bytes(self.before)
        self.reader = ReadFileExecutor(self.root)
        self.editor = EditFileExecutor(EditPolicy(self.root, ["sample.py"]))
        self.router = ToolRouter({"read_file": self.reader, "edit_file": self.editor})
        self.store = SessionStore(self.root / "session.jsonl")
        self.observation = {}

    def edit(self, call_id="edit_001", *, incomplete=False):
        return ToolCall(
            call_id, "edit_file",
            None if incomplete else {"path": "sample.py", "old_text": "value = 1", "new_text": "value = 2"},
            raw_arguments='{"path":"sample.py","old_text":' if incomplete else None,
        )

    def truncated(self, *, incomplete=False):
        return Message("assistant", "部分回复。", [
            self.edit(incomplete=incomplete),
            ToolCall("read_001", "read_file", {"path": "sample.py"}),
        ], stop_reason="length")

    async def run_steps(self, steps, *, budget=None):
        self.provider = MockProvider(steps)
        with patch.object(self.router, "execute", wraps=self.router.execute) as execute:
            self.result = await run_loop(
                self.provider, self.router, [Message("user", "修正公式。")],
                [self.reader.definition, self.editor.definition], self.store,
                max_model_turns=budget,
            )
            self.executed = [item.args[0].id for item in execute.await_args_list]
        self.loaded = self.store.load()
        self.feedback = [item for item in self.result.messages if isinstance(item, ToolResult)]
        self.observation = {
            "status": self.result.status, "executed_call_ids": self.executed,
            "model_requests": len(self.provider.requests),
            "feedback": [{"id": item.tool_call_id, "error": item.error} for item in self.feedback],
            "file_contents": self.target.read_text(encoding="utf-8"),
        }
        self.assertEqual(self.loaded.history, self.result.messages)
        ends = [row["data"]["status"] for row in self.loaded.records if row["type"] == "run_end"]
        self.assertEqual(ends, [self.result.status])
        self.assertEqual(find_pending_calls(self.loaded), [])

    def assert_batch_rejected(self):
        rejected = [item for item in self.feedback if item.tool_call_id in {"edit_001", "read_001"}]
        self.assertEqual([item.tool_call_id for item in rejected], ["edit_001", "read_001"])
        self.assertTrue(all(item.error for item in rejected))
        self.assertTrue(all(item.output == "" for item in rejected))

    async def check_rejected(self, *, incomplete):
        await self.run_steps([self.truncated(incomplete=incomplete), Message("assistant", "已看到反馈。")])
        self.assertEqual(self.result.status, "finished")
        self.assertEqual(self.executed, [])
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertEqual(len(self.provider.requests), 2)
        self.assert_batch_rejected()
        next_feedback = [item for item in self.provider.requests[1] if isinstance(item, ToolResult)]
        self.assertEqual(next_feedback, self.feedback)

    async def test_valid_json_calls_are_all_rejected_before_executor(self):
        await self.check_rejected(incomplete=False)

    async def test_incomplete_call_and_valid_call_are_both_rejected(self):
        await self.check_rejected(incomplete=True)

    async def test_feedback_is_saved_before_budget_blocks_next_model_request(self):
        await self.run_steps([self.truncated()], budget=1)
        self.assertEqual(self.result.status, "budget_exhausted")
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual(self.executed, [])
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assert_batch_rejected()

    async def test_only_complete_new_call_executes_after_feedback(self):
        await self.run_steps([
            self.truncated(),
            Message("assistant", "完整重试。", [self.edit("edit_002")], stop_reason="tool_calls"),
            Message("assistant", "结束。", stop_reason="stop"),
        ])
        self.assertEqual(self.result.status, "finished")
        self.assertEqual(self.executed, ["edit_002"])
        self.assertEqual(len(self.provider.requests), 3)
        self.assertEqual(self.target.read_bytes(), self.after)
        self.assert_batch_rejected()
        self.assertEqual([item.tool_call_id for item in self.feedback], ["edit_001", "read_001", "edit_002"])
        self.assertIsNone(self.feedback[-1].error)

    async def test_text_only_length_does_not_force_another_request(self):
        await self.run_steps([Message("assistant", "文字被截断。", stop_reason="length")])
        self.assertEqual(self.result.status, "finished")
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual(self.executed, [])
        self.assertEqual(self.feedback, [])
        self.assertEqual(self.loaded.history[-1].stop_reason, "length")


if __name__ == "__main__":
    unittest.main()
