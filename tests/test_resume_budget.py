"""D12：恢复入口沿用本次运行预算，不重放或重复保存旧历史。

助手准备的验收：真实 JSONL/临时文件配合模拟模型与受控等待。
当前入口尚未接收预算参数时，新用例会明确报错，不跳过。
"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.run_deadline import await_before_deadline
from mini_pi.session_resume import resume_session
from mini_pi.session_store import SessionStore
from mini_pi.tools.read_file import ReadFileExecutor


READ_ONLY = frozenset({"read_file", "list_files"})


class WaitingModel:
    def __init__(self):
        self.requests = []
        self.cleaned = False

    async def generate(self, history, tools):
        self.requests.append(list(history))
        try:
            await asyncio.Future()
        finally:
            self.cleaned = True


class ResumeBudgetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_resume_budget_", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "session.jsonl"
        (self.root / "sample.txt").write_text("真实文件内容", encoding="utf-8")
        self.reader = ReadFileExecutor(self.root)
        self.old = [Message("user", "之前的任务。")]
        for number in range(3):
            self.old.extend([Message("assistant", f"旧回复 {number}"), Message("user", "继续。")])
        self.old.append(Message("assistant", "旧任务结束。"))

    def seed(self, history=None):
        store = SessionStore(self.path, "old_run")
        store.append_entry("run_start", {"status": "running"})
        for item in self.old if history is None else history:
            store.append_item(item)
        store.append_entry("run_end", {"status": "finished", "task_passed": None})
        self.before = self.path.read_bytes()
        return SessionStore(self.path, "new_run")

    async def resume(self, store, provider, executor=None, **config):
        # 独立看门狗防止漏接总时限导致测试无限等待。
        async with asyncio.timeout(2):
            return await resume_session(
                store, provider, self.reader if executor is None else executor,
                "本次继续。", [self.reader.definition], READ_ONLY, **config,
            )

    def assert_saved(self, store, outcome, status):
        self.assertEqual(outcome.plan.state, "ready")
        self.assertEqual(outcome.run_result.status, status)
        self.assertTrue(self.path.read_bytes().startswith(self.before))
        loaded = store.load()
        self.assertEqual(loaded.history, outcome.run_result.messages)
        new_rows = [row for row in loaded.records if row["run_id"] == "new_run"]
        self.assertEqual(new_rows[0]["type"], "run_start")
        self.assertEqual([row["data"]["status"] for row in new_rows if row["type"] == "run_end"], [status])
        users = [row for row in new_rows if row["type"] == "message" and row["data"]["role"] == "user"]
        self.assertEqual([row["data"]["content"] for row in users], ["本次继续。"])

    async def test_old_model_responses_do_not_consume_new_turn_budget(self):
        store = self.seed()
        provider = MockProvider([
            Message("assistant", "读取。", [ToolCall("new_read", "read_file", {"path": "sample.txt"})]),
            Message("assistant", "不应请求第二次。"),
        ])
        with patch.object(self.reader, "execute", wraps=self.reader.execute) as execute:
            outcome = await self.resume(store, provider, max_model_turns=1)
        self.assert_saved(store, outcome, "budget_exhausted")
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(execute.await_count, 1)
        self.assertEqual(provider.requests[0], self.old + [Message("user", "本次继续。")])
        results = [item for item in outcome.run_result.messages if isinstance(item, ToolResult)]
        self.assertEqual(results, [ToolResult("new_read", "read_file", "真实文件内容")])

    async def test_final_answer_on_last_allowed_turn_finishes(self):
        store = self.seed()
        provider = MockProvider([Message("assistant", "本次完成。")])
        outcome = await self.resume(store, provider, max_model_turns=1, total_timeout_seconds=1)
        self.assert_saved(store, outcome, "finished")
        self.assertEqual(len(provider.requests), 1)

    async def test_restored_run_waiting_model_obeys_timeout(self):
        store = self.seed()
        provider = WaitingModel()
        outcome = await self.resume(store, provider, total_timeout_seconds=0.05)
        self.assert_saved(store, outcome, "timeout")
        self.assertTrue(provider.cleaned)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(outcome.run_result.messages, self.old + [Message("user", "本次继续。")])

    async def test_model_and_tools_share_deadline_and_preserve_completed_result(self):
        store = self.seed()
        calls = [ToolCall(f"read_{i}", "read_file", {"path": "sample.txt"}) for i in range(3)]
        provider = MockProvider([Message("assistant", "读取三次。", calls)])
        actual_calls = []
        deadlines = []
        cleaned = []
        native_execute = self.reader.execute

        async def execute(call):
            actual_calls.append(call.id)
            if len(actual_calls) == 1:
                return await native_execute(call)
            try:
                await asyncio.Future()
            finally:
                cleaned.append(call.id)

        async def observe_wait(operation, deadline):
            deadlines.append(deadline)
            return await await_before_deadline(operation, deadline)

        with patch.object(self.reader, "execute", side_effect=execute), patch(
            "mini_pi.loop.await_before_deadline", side_effect=observe_wait,
        ):
            outcome = await self.resume(store, provider, total_timeout_seconds=0.1)
        self.assert_saved(store, outcome, "timeout")
        self.assertEqual(actual_calls, ["read_0", "read_1"])
        self.assertEqual(cleaned, ["read_1"])
        self.assertEqual(len(provider.requests), 1)
        results = [item for item in outcome.run_result.messages if isinstance(item, ToolResult)]
        self.assertEqual([item.tool_call_id for item in results], ["read_0"])
        self.assertEqual(len(deadlines), 3)
        self.assertIsNotNone(deadlines[0])
        self.assertTrue(all(value == deadlines[0] for value in deadlines))

    async def test_blocked_recovery_still_has_no_execution_or_new_records(self):
        for tool_name, expected in (("read_file", "read_interrupted"), ("edit_file", "needs_review")):
            with self.subTest(tool=tool_name):
                self.path = self.root / f"{tool_name}.jsonl"
                store = self.seed([
                    Message("user", "旧请求。"),
                    Message("assistant", "缺少结果。", [ToolCall("pending", tool_name, {})]),
                ])
                provider = MockProvider([Message("assistant", "不应请求。")])
                with patch.object(self.reader, "execute", wraps=self.reader.execute) as execute:
                    outcome = await self.resume(store, provider, max_model_turns=1, total_timeout_seconds=1)
                self.assertEqual(outcome.plan.state, expected)
                self.assertIsNone(outcome.run_result)
                self.assertEqual(provider.requests, [])
                execute.assert_not_called()
                self.assertEqual(self.path.read_bytes(), self.before)

    async def test_invalid_config_leaves_ready_session_unchanged(self):
        store = self.seed()
        for config in ({"max_model_turns": 0}, {"total_timeout_seconds": -1}):
            with self.subTest(config=config):
                provider = MockProvider([Message("assistant", "不应请求。")])
                with patch.object(self.reader, "execute", wraps=self.reader.execute) as execute:
                    with self.assertRaises(ValueError):
                        await self.resume(store, provider, **config)
                self.assertEqual(provider.requests, [])
                execute.assert_not_called()
                self.assertEqual(self.path.read_bytes(), self.before)


if __name__ == "__main__":
    unittest.main()
