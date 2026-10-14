"""助手准备：实际 JSONL 配合模拟模型，验收 D11 入口的副作用边界。

入口骨架尚未实现时这些用例应报 NotImplementedError；不会跳过或假装通过。
"""

from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock

from mini_pi.executor import ToolExecutor
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_recovery import PendingCall, find_pending_calls
from mini_pi.session_resume import resume_session
from mini_pi.session_store import SessionStore


READ_ONLY_TOOLS = frozenset({"read_file", "list_files"})


class SessionResumeGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(
            prefix="_resume_gate_", dir=Path(__file__).resolve().parent,
        )
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "session.jsonl"

    def _save_history(self, history, finished=False):
        """助手构造会话夹具；保存请求本身不会执行工具。"""
        store = SessionStore(self.path, "run_A")
        store.append_entry("run_start", {"status": "running"})
        for item in history:
            store.append_item(item)
        if finished:
            store.append_entry("run_end", {"status": "finished", "task_passed": None})

    async def _assert_blocked(self, calls, expected_state):
        self._save_history([
            Message("user", "检查文件。"),
            Message("assistant", "发出请求，结果尚未记录。", calls),
        ])
        before = self.path.read_bytes()
        provider = MockProvider([Message("assistant", "门禁应阻止这次模型请求。")])
        executor = AsyncMock(spec=ToolExecutor)
        store = SessionStore(self.path, "run_B")

        result = await resume_session(
            store, provider, executor, "继续检查。", [], READ_ONLY_TOOLS,
        )

        self.assertEqual(result.plan.state, expected_state)
        self.assertEqual(result.plan.pending_calls, [PendingCall("run_A", call) for call in calls])
        self.assertIsNone(result.run_result)
        self.assertEqual(provider.requests, [])
        executor.execute.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    async def test_read_interrupted_stops_before_model_tools_or_any_new_record(self):
        await self._assert_blocked([
            ToolCall("read_001", "read_file", {"path": "discount.py"}),
        ], "read_interrupted")

    async def test_needs_review_stops_before_model_tools_or_any_new_record(self):
        await self._assert_blocked([
            ToolCall("edit_001", "edit_file", {
                "path": "discount.py", "old_text": "old", "new_text": "new",
            }),
        ], "needs_review")

    async def test_mixed_pending_calls_stop_the_whole_resume(self):
        await self._assert_blocked([
            ToolCall("read_001", "read_file", {"path": "discount.py"}),
            ToolCall("edit_001", "edit_file", {
                "path": "discount.py", "old_text": "old", "new_text": "new",
            }),
        ], "needs_review")

    async def test_run_tests_is_not_treated_as_read_only(self):
        await self._assert_blocked([
            ToolCall("tests_001", "run_tests", {}),
        ], "needs_review")

    async def test_invalid_pairing_stops_before_model_tools_or_any_new_record(self):
        self._save_history([ToolResult("orphan_001", "edit_file", "孤立结果")])
        before = self.path.read_bytes()
        provider = MockProvider([Message("assistant", "不应请求模型。")])
        executor = AsyncMock(spec=ToolExecutor)

        with self.assertRaisesRegex(ValueError, "没有前置请求"):
            await resume_session(
                SessionStore(self.path, "run_B"), provider, executor,
                "继续。", [], READ_ONLY_TOOLS,
            )

        self.assertEqual(provider.requests, [])
        executor.execute.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    async def test_ready_preserves_context_without_replay_or_duplicate_records(self):
        history = [
            Message("user", "读取 discount.py。"),
            Message("assistant", "读取文件。", [
                ToolCall("read_001", "read_file", {"path": "discount.py"}),
            ]),
            ToolResult("read_001", "read_file", "return price * rate"),
            Message("assistant", "读取完成，尚未修改。"),
        ]
        self._save_history(history, finished=True)
        before = self.path.read_bytes()
        new_user = Message("user", "解释保存的公式。")
        answer = Message("assistant", "它计算优惠金额；本次依据保存结果解释。")
        provider = MockProvider([answer])
        executor = AsyncMock(spec=ToolExecutor)
        store = SessionStore(self.path, "run_B")

        result = await resume_session(
            store, provider, executor, new_user.content, [], READ_ONLY_TOOLS,
        )

        self.assertEqual(result.plan.state, "ready")
        self.assertEqual(result.plan.pending_calls, [])
        self.assertIsNotNone(result.run_result)
        self.assertEqual(result.run_result.status, "finished")
        self.assertIsNone(result.run_result.task_passed)
        self.assertEqual(provider.requests, [history + [new_user]])
        executor.execute.assert_not_called()
        self.assertEqual(result.run_result.messages, history + [new_user, answer])
        self.assertTrue(self.path.read_bytes().startswith(before))
        loaded = store.load()
        self.assertEqual(loaded.history, result.run_result.messages)
        self.assertEqual(find_pending_calls(loaded), [])
        self.assertEqual(len(loaded.records), 10)
        new_records = [record for record in loaded.records if record["run_id"] == "run_B"]
        self.assertEqual([record["type"] for record in new_records], [
            "run_start", "message", "message", "run_end",
        ])
        self.assertEqual([record["data"] for record in new_records[1:3]], [
            asdict(new_user), asdict(answer),
        ])
        self.assertEqual(sum(record["type"] == "tool_result" for record in loaded.records), 1)


if __name__ == "__main__":
    unittest.main()
