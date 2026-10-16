"""D12：真实本地 HTTPS + Qwen 适配器/循环，验证连接取消与终态记录。

旧的等待同步线程自然结束契约已撤换；本组服务不回复、不由测试释放。
"""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.executor import ToolExecutor
from mini_pi.loop import run_loop
from mini_pi.models import Message
from mini_pi.qwen_client import QwenProvider
from mini_pi.session_store import SessionStore
from tests.http_test_server import LocalHttpsServer


class QwenCancelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = await LocalHttpsServer(mode="hang_headers").start()
        self.addAsyncCleanup(self.server.close)
        client_patch = patch("mini_pi.async_http_transport._make_client", side_effect=self.server.make_client)
        client_patch.start()
        self.addCleanup(client_patch.stop)
        # 学习者尚未切换旧入口时，明确失败，绝不访问外部模型服务。
        legacy = patch("mini_pi.qwen_client.post_json", create=True,
                       side_effect=AssertionError("Qwen 尚未切换异步 HTTP 入口"))
        legacy.start()
        self.addCleanup(legacy.stop)
        self.temp = TemporaryDirectory(prefix="_qwen_cancel_", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.store = SessionStore(Path(self.temp.name) / "session.jsonl", "run_A")
        self.provider = QwenProvider(
            api_key="offline-placeholder", timeout=5,
            base_url=self.server.url.removesuffix("/chat/completions"),
        )
        self.initial = [Message("user", "验证真实本地请求的取消。")]

    async def settle(self, task):
        if not task.done():
            task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        self.assertIn(task, done, "测试清理后请求仍未结束")
        try:
            task.result()
        except (asyncio.CancelledError, Exception):
            pass

    def start(self, operation):
        task = asyncio.create_task(operation)
        self.addAsyncCleanup(self.settle, task)
        return task

    async def assert_network_closed_and_recorded(self):
        await asyncio.wait_for(self.server.disconnected.wait(), 1)
        self.assertEqual(self.server.errors, [])
        self.assertEqual(len(self.server.requests), 1)
        self.assertTrue(self.server.clients)
        self.assertTrue(all(client.is_closed for client in self.server.clients))
        self.assertTrue(all(response.is_closed for response in self.server.responses))
        self.assertEqual(self.provider.request_count, 1)
        self.assertEqual(len(self.provider.request_records), 1)
        record = self.provider.request_records[0]
        self.assertEqual(record["status"], "cancelled")
        self.assertIsNone(record["usage"])
        self.assertIsNone(record["returned_model"])
        self.assertNotIn("offline-placeholder", json.dumps(self.provider.request_records))

    async def test_loop_normal_response_returns_finished_and_closes_connection(self):
        self.server.mode = "normal"
        response = {
            "model": self.provider.model,
            "choices": [{
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "本地正常响应。"},
            }],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        }
        self.server.body = json.dumps(response, ensure_ascii=False).encode("utf-8")
        executor = AsyncMock(spec=ToolExecutor)
        task = self.start(run_loop(self.provider, executor, self.initial, [], self.store))
        done, _ = await asyncio.wait({task}, timeout=2)
        self.assertIn(task, done)
        result = task.result()
        self.last_result = result
        self.assertEqual(result.status, "finished")
        self.assertIsNone(result.task_passed)
        self.assertEqual(result.messages, self.initial + [Message("assistant", "本地正常响应。")])
        executor.execute.assert_not_awaited()
        loaded = self.store.load()
        self.assertEqual(loaded.history, result.messages)
        self.assertEqual(loaded.records[-1]["data"]["status"], "finished")
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(len(self.provider.request_records), 1)
        record = self.provider.request_records[0]
        self.assertEqual(record["status"], "received")
        self.assertEqual(record["usage"], response["usage"])
        self.assertTrue(all(client.is_closed for client in self.server.clients))
        self.assertTrue(all(item.is_closed for item in self.server.responses))
        self.assertEqual(self.server.errors, [])

    async def test_direct_send_cancel_closes_request_without_parsing_response(self):
        with patch("mini_pi.qwen_client.parse_assistant_message") as parse:
            task = self.start(self.provider.generate(self.initial, []))
            await asyncio.wait_for(self.server.started.wait(), 2)
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=1)
            self.assertIn(task, done, "服务端不回复时也应完成本地取消")
            with self.assertRaises(asyncio.CancelledError):
                await task
            parse.assert_not_called()
        await self.assert_network_closed_and_recorded()

    async def test_loop_cancel_during_response_body_closes_connection_before_return(self):
        self.server.mode = "hang_body"
        executor = AsyncMock(spec=ToolExecutor)
        task = self.start(run_loop(self.provider, executor, self.initial, [], self.store))
        await asyncio.wait_for(self.server.response_seen.wait(), 2)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=1)
        self.assertIn(task, done)
        result = task.result()
        self.last_result = result
        self.assertEqual(result.status, "cancelled")
        self.assertIsNone(result.task_passed)
        self.assertEqual(result.messages, self.initial)
        executor.execute.assert_not_awaited()
        loaded = self.store.load()
        self.assertEqual(loaded.history, self.initial)
        self.assertEqual(loaded.records[-1]["data"]["status"], "cancelled")
        await self.assert_network_closed_and_recorded()

    async def test_total_timeout_closes_unanswered_request_without_waiting_for_reply(self):
        executor = AsyncMock(spec=ToolExecutor)
        task = self.start(run_loop(
            self.provider, executor, self.initial, [], self.store,
            total_timeout_seconds=1,
        ))
        await asyncio.wait_for(self.server.started.wait(), 2)
        done, _ = await asyncio.wait({task}, timeout=2)
        self.assertIn(task, done, "总时限不应继续等原请求的 5 秒自身超时")
        result = task.result()
        self.last_result = result
        self.assertEqual(result.status, "timeout")
        self.assertIsNone(result.task_passed)
        self.assertEqual(result.messages, self.initial)
        executor.execute.assert_not_awaited()
        loaded = self.store.load()
        self.assertEqual(loaded.history, self.initial)
        self.assertEqual(loaded.records[-1]["data"]["status"], "timeout")
        await self.assert_network_closed_and_recorded()


if __name__ == "__main__":
    unittest.main()
