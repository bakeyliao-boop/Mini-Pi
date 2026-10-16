"""D12 验收反例：结束前已请求的取消不能落盘为正常结束或预算耗尽。

模拟模型/真实读取完成后，精确安排当前运行任务的取消请求。
不修改 run_loop 或统一等待入口；分别观察调用方与 JSONL 状态。
"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore
from mini_pi.tools.read_file import ReadFileExecutor


class CancelFinishTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_cancel_finish_", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "sample.txt").write_bytes(b"completed read\n")
        self.reader = ReadFileExecutor(self.root)
        self.store = SessionStore(self.root / "session.jsonl", "current_run")
        self.initial = [Message("user", "本次结束前取消。")]
        self.observation = {}
        self.cancel_accepted = []

    async def run_and_observe(self, provider, *, budget=None):
        task = asyncio.create_task(run_loop(
            provider, self.reader, self.initial, [self.reader.definition], self.store,
            max_model_turns=budget,
        ))
        result = None
        try:
            async with asyncio.timeout(2):
                result = await task
            caller_status = result.status
        except asyncio.CancelledError:
            caller_status = "uncaught_cancelled_error"
        loaded = self.store.load()
        end_statuses = [row["data"]["status"] for row in loaded.records if row["type"] == "run_end"]
        self.observation = {
            "cancel_request_accepted": self.cancel_accepted,
            "expected_run_end_statuses": ["cancelled"],
            "actual_run_end_statuses": end_statuses,
            "expected_caller_status": "cancelled",
            "actual_caller_status": caller_status,
            "task_marked_cancelled": task.cancelled(),
            "model_requests": len(provider.requests),
            "saved_tool_results": [item.tool_call_id for item in loaded.history if isinstance(item, ToolResult)],
        }
        self.assertEqual(self.cancel_accepted, [True])
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(end_statuses, ["cancelled"], "结束前已请求取消，记录不能先写其他终态")
        self.assertIsNotNone(result, "run_loop 应按已有契约返回 cancelled 的 RunResult")
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(loaded.history, result.messages)
        return loaded

    async def test_cancel_before_final_answer_return_is_recorded_as_cancelled(self):
        def final_answer_then_cancel(history, tools):
            answer = Message("assistant", "回答已生成，尚未退出本次运行。")
            self.cancel_accepted.append(asyncio.current_task().cancel())
            return answer

        provider = MockProvider([final_answer_then_cancel])
        loaded = await self.run_and_observe(provider)
        self.assertEqual(len(loaded.history), 2)

    async def test_cancel_after_last_tool_is_not_overwritten_by_budget_status(self):
        provider = MockProvider([
            Message("assistant", "读取后取消。", [
                ToolCall("read_last", "read_file", {"path": "sample.txt"}),
            ]),
            Message("assistant", "不应请求。"),
        ])
        native_execute = self.reader.execute

        async def read_then_cancel(call):
            result = await native_execute(call)
            self.cancel_accepted.append(asyncio.current_task().cancel())
            return result

        with patch.object(self.reader, "execute", side_effect=read_then_cancel):
            loaded = await self.run_and_observe(provider, budget=1)
        results = [item for item in loaded.history if isinstance(item, ToolResult)]
        self.assertEqual(results, [ToolResult("read_last", "read_file", "completed read\n")])


if __name__ == "__main__":
    unittest.main()
