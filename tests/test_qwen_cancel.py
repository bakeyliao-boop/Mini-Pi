"""助手准备：真实 Qwen 适配器 + 真实线程 + 模拟 HTTP；无真实服务请求。"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.executor import ToolExecutor
from mini_pi.loop import run_loop
from mini_pi.models import Message
from mini_pi.qwen_client import QwenProvider
from mini_pi.session_store import SessionStore
from tests.test_thread_worker import BlockingWork, settle_thread_task


class QwenCancelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory(prefix="_qwen_cancel_", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.store = SessionStore(Path(self.temp.name) / "session.jsonl", "run_A")
        self.provider = QwenProvider(api_key="offline-placeholder")
        self.initial = [Message("user", "验证发送期间的取消收尾。")]
        response = {
            "model": "qwen3.8-flash",
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "取消后应丢弃的回答"}}],
            "usage": {"total_tokens": 1},
        }
        self.work = BlockingWork(asyncio.get_running_loop(), result=response)

    def start(self, operation):
        task = asyncio.create_task(operation)
        self.addAsyncCleanup(settle_thread_task, task, self.work)
        return task

    def assert_cancelled_send_record(self):
        self.assertTrue(self.work.finished.is_set())
        self.assertEqual(self.work.calls, 1)
        self.assertEqual(self.provider.request_count, 1)
        self.assertEqual(len(self.provider.request_records), 1)
        record = self.provider.request_records[0]
        self.assertEqual(record["status"], "cancelled")
        self.assertIsNone(record["usage"])
        self.assertIsNone(record["returned_model"])

    async def test_direct_send_cancel_waits_for_thread_without_parsing_response(self):
        with patch("mini_pi.qwen_client.post_json", side_effect=self.work), patch(
            "mini_pi.qwen_client.parse_assistant_message",
        ) as parse:
            task = self.start(self.provider.generate(self.initial, []))
            async with asyncio.timeout(2):
                await self.work.started.wait()
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                self.assertEqual(self.provider.request_records, [])
                self.work.release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            parse.assert_not_called()
        self.assert_cancelled_send_record()

    async def test_loop_cancel_returns_after_http_worker_finished(self):
        executor = AsyncMock(spec=ToolExecutor)
        with patch("mini_pi.qwen_client.post_json", side_effect=self.work):
            task = self.start(run_loop(self.provider, executor, self.initial, [], self.store))
            async with asyncio.timeout(2):
                await self.work.started.wait()
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                self.work.release.set()
                result = await task
        self.assertEqual(result.status, "cancelled")
        self.assertIsNone(result.task_passed)
        self.assertEqual(result.messages, self.initial)
        executor.execute.assert_not_called()
        self.assertEqual(self.store.load().records[-1]["data"]["status"], "cancelled")
        self.assert_cancelled_send_record()

    async def test_total_timeout_waits_for_http_worker_then_returns_timeout(self):
        executor = AsyncMock(spec=ToolExecutor)
        with patch("mini_pi.qwen_client.post_json", side_effect=self.work):
            task = self.start(run_loop(
                self.provider, executor, self.initial, [], self.store,
                total_timeout_seconds=0.1,
            ))
            async with asyncio.timeout(2):
                await self.work.started.wait()
                while task.cancelling() == 0 and not task.done():
                    await asyncio.sleep(0.005)
                self.assertFalse(task.done())
                self.assertFalse(self.work.finished.is_set())
                self.work.release.set()
                result = await task
        self.assertEqual(result.status, "timeout")
        self.assertIsNone(result.task_passed)
        self.assertEqual(result.messages, self.initial)
        executor.execute.assert_not_called()
        self.assertEqual(self.store.load().records[-1]["data"]["status"], "timeout")
        self.assert_cancelled_send_record()


if __name__ == "__main__":
    unittest.main()
