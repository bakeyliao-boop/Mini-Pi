"""助手准备：统一结束函数的结果、待生效取消及记录一致性。

函数尚未手敲时测试应明确失败；不将准备状态当作验收通过。
"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi import run_finish
from mini_pi.models import Message, RunResult, ToolResult
from mini_pi.session_store import SessionStore


class RunFinishTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_run_finish_", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "session.jsonl"
        self.store = SessionStore(self.path, "ending_run")
        self.history = [Message("user", "结束本次运行。"), ToolResult("done", "read_file", "已完成结果")]

    def assert_record(self, result):
        records = self.store.load().records
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["type"], "run_end")
        self.assertEqual(records[0]["data"], {
            "status": result.status, "task_passed": result.task_passed, "error": result.error,
        })

    async def test_normal_finish_returns_same_result_and_records_once(self):
        proposed = RunResult("finished", self.history)
        result = await run_finish.finish_run(proposed, self.store)
        self.assertIs(result, proposed)
        self.assert_record(result)

    async def test_pending_cancel_replaces_finished_but_preserves_history(self):
        proposed = RunResult("finished", self.history, task_passed=True)

        async def operation():
            asyncio.current_task().cancel()
            return await run_finish.finish_run(proposed, self.store)

        result = await asyncio.create_task(operation())
        self.assertEqual(result.status, "cancelled")
        self.assertIs(result.messages, self.history)
        self.assertIsNone(result.task_passed)
        self.assert_record(result)

    async def test_pending_cancel_replaces_budget_status(self):
        async def operation():
            asyncio.current_task().cancel()
            return await run_finish.finish_run(RunResult("budget_exhausted", self.history), self.store)

        result = await asyncio.create_task(operation())
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.messages, self.history)
        self.assert_record(result)

    async def test_timeout_without_new_cancel_keeps_error(self):
        proposed = RunResult("timeout", self.history, error="运行总时间已到")
        result = await run_finish.finish_run(proposed, self.store)
        self.assertIs(result, proposed)
        self.assert_record(result)

    async def test_already_handled_cancel_returns_cancelled_result(self):
        async def operation():
            asyncio.current_task().cancel()
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                return await run_finish.finish_run(RunResult("cancelled", self.history), self.store)

        result = await asyncio.create_task(operation())
        self.assertEqual(result.status, "cancelled")
        self.assert_record(result)

    async def test_no_store_still_processes_pending_cancel(self):
        async def operation():
            asyncio.current_task().cancel()
            return await run_finish.finish_run(RunResult("finished", self.history), None)

        result = await asyncio.create_task(operation())
        self.assertEqual(result.status, "cancelled")
        self.assertFalse(self.path.exists())

    async def test_record_write_error_is_not_reported_as_normal_finish(self):
        with patch.object(self.store, "append_entry", side_effect=OSError("受控写入失败")):
            with self.assertRaisesRegex(OSError, "受控写入失败"):
                await run_finish.finish_run(RunResult("finished", self.history), self.store)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
