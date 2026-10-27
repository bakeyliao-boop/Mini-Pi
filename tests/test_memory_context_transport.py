"""MEM-04：真实本地 HTTPS embedding 与请求循环的成功／取消闭环。

复用现有服务器及合成证书，只替换客户端工厂以信任该证书。
embedding 向量和回答内容固定；正常例真正经过 QwenProvider 和本地网络，
取消例用 MockProvider 观察零调用。不证明云服务语义或收费结果。
"""

import asyncio
from contextlib import suppress
from functools import partial
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit

from mini_pi.loop import run_loop
from mini_pi.memory.dashscope_embedding import DashScopeEmbedder
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.request_context import prepare_context
from mini_pi.memory.store import MemoryStore
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message
from mini_pi.qwen_client import QwenProvider
from mini_pi.session_store import SessionStore
from tests.http_test_server import LocalHttpsServer


DIMENSIONS = 64
SYNTHETIC_KEY = "synthetic-context-local-https-token"
QUERY = "后续举例使用什么语言？"


def embedding_body():
    return json.dumps({
        "request_id": "synthetic-context-embedding",
        "usage": {"total_tokens": 1},
        "output": {"embeddings": [{
            "text_index": 0, "embedding": [1.0] + [0.0] * (DIMENSIONS - 1),
        }]},
    }).encode("utf-8")


class MemoryContextTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="memory-context-https-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scope = MemoryScope("context-http-user", "mini-pi-demo")
        self.store = MemoryStore(self.root / "memory.sqlite3")
        text = "后续讲解请尽量使用 Python 举例。"
        source = MemorySource("context-http-source", self.scope, "user", text,
                              "2026-01-01T00:00:00+08:00")
        self.entry = self.store.remember(
            self.scope, source, MemoryDraft("example_language", 0, len(text), source.recorded_at),
        )
        self.session = SessionStore(self.root / "session.jsonl", run_id="context-http-run")
        self.initial = [Message("system", "编程助手。"), Message("user", QUERY)]
        self.provider = MockProvider([Message("assistant", "后续尽量用 Python 举例。")])
        self.executor = SimpleNamespace(execute=AsyncMock(side_effect=AssertionError("本例不允许执行工具")))

    async def server(self, mode="normal", body=None):
        server = await LocalHttpsServer(mode=mode, body=embedding_body() if body is None else body).start()

        async def close():
            await server.close()
            self.assertEqual(server.errors, [])

        self.addAsyncCleanup(close)
        return server

    def embedder(self, server):
        parts = urlsplit(server.url)
        return DashScopeEmbedder(SYNTHETIC_KEY, dimensions=DIMENSIONS,
                                 base_url=f"{parts.scheme}://{parts.netloc}/api/v1", timeout=5)

    async def run_case(self, embedder):
        prepare = partial(prepare_context, self.store, self.scope, QUERY, embedder=embedder,
                          at="2026-10-27T10:00:00+08:00", top_k=1, min_score=0.9,
                          max_context_chars=10_000)
        return await run_loop(self.provider, self.executor, self.initial, [],
                              session_store=self.session, prepare_messages=prepare)

    async def settle(self, task, release):
        release.set()
        if not task.done():
            task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        self.assertIn(task, done, "测试清理后仍有在途请求循环")
        with suppress(asyncio.CancelledError, Exception):
            task.result()

    def assert_closed(self, server, request_count):
        self.assertEqual(len(server.requests), request_count, "不得自动重试或额外发请求")
        self.assertEqual(len(server.clients), request_count)
        self.assertEqual(len(server.responses), request_count)
        self.assertTrue(all(client.is_closed for client in server.clients))
        self.assertTrue(all(response.is_closed for response in server.responses))
        self.assertTrue(all(request["start"] ==
                            "POST /api/v1/services/embeddings/text-embedding/text-embedding HTTP/1.1"
                            for request in server.requests))

    async def test_local_https_search_preparation_reaches_provider_with_source_and_clean_session(self):
        server = await self.server()
        embedder = self.embedder(server)
        answer_server = await self.server(body=json.dumps({
            "model": "synthetic-context-answer", "usage": {"total_tokens": 1},
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": "后续尽量用 Python 举例。",
            }}],
        }, ensure_ascii=False).encode("utf-8"))
        self.provider = QwenProvider(
            api_key=SYNTHETIC_KEY, model="synthetic-context-answer",
            base_url=answer_server.url.removesuffix("/chat/completions"),
            timeout=5, max_requests=1,
        )
        client_count = 0

        def client_for_request(timeout):
            nonlocal client_count
            client_count += 1
            self.assertLessEqual(client_count, 3, "不允许计划外请求")
            return (server if client_count <= 2 else answer_server).make_client(timeout)

        with patch("mini_pi.async_http_transport._make_client", side_effect=client_for_request):
            result = await asyncio.wait_for(self.run_case(embedder), timeout=3)

        self.assertEqual(result.status, "finished")
        self.assert_closed(server, 2)  # 一个 query 和一个 document，均真实经过本地 TLS。
        requests = [json.loads(request["body"]) for request in server.requests]
        self.assertEqual([request["parameters"]["text_type"] for request in requests],
                         ["query", "document"])
        self.assertEqual([request["input"]["texts"] for request in requests],
                         [[QUERY], [self.entry.text]])
        self.assertEqual([record["status"] for record in embedder.request_records],
                         ["validated", "validated"])
        self.assertEqual(self.provider.request_count, 1)
        self.assertEqual(len(answer_server.requests), 1)
        self.assertEqual(answer_server.requests[0]["start"], "POST /v1/chat/completions HTTP/1.1")
        self.assertTrue(all(client.is_closed for client in answer_server.clients))
        self.assertTrue(all(response.is_closed for response in answer_server.responses))
        answer_payload = json.loads(answer_server.requests[0]["body"])
        sent = answer_payload["messages"]  # 检查供应商转换及实际网络发送之后的 JSON。
        self.assertEqual([message["role"] for message in sent], ["system", "user", "user"])
        self.assertEqual(sent[0], {"role": "system", "content": self.initial[0].content})
        self.assertEqual(sent[-1], {"role": "user", "content": QUERY})
        evidence = json.loads(sent[1]["content"])["memories"]
        self.assertEqual(len(evidence), 1)
        self.assertEqual((evidence[0]["memory_id"], evidence[0]["content"], evidence[0]["version"]),
                         (self.entry.memory_id, self.entry.text, 1))
        self.assertEqual(evidence[0]["source"], {
            "source_id": self.entry.source.source_id, "role": "user",
            "recorded_at": self.entry.source.recorded_at,
        })
        loaded = self.session.load()
        self.assertEqual(loaded.history, result.messages)
        self.assertEqual(loaded.history[:2], self.initial)
        self.assertEqual(loaded.records[-1]["data"]["status"], "finished")
        self.assertNotIn('"memories"', self.session.path.read_text(encoding="utf-8"))
        self.executor.execute.assert_not_awaited()

    async def test_cancel_during_real_embedding_waits_for_connection_cleanup_before_cancelled_run_end(self):
        server = await self.server(mode="hang_body")
        embedder = self.embedder(server)
        close_started, close_release, close_finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

        def held_client_close(timeout):
            client = server.make_client(timeout)
            real_close = client.aclose

            async def close():
                close_started.set()
                await close_release.wait()  # 显式门闩用于证明收尾未完成时不能结算 run_end。
                await real_close()
                close_finished.set()

            client.aclose = close
            return client

        with patch("mini_pi.async_http_transport._make_client", side_effect=held_client_close):
            task = asyncio.create_task(self.run_case(embedder))
            self.addAsyncCleanup(self.settle, task, close_release)
            try:
                await asyncio.wait_for(server.response_seen.wait(), timeout=2)
                self.assertFalse(task.done(), "取消前应停在实际响应体等待阶段")
                task.cancel()
                await asyncio.wait_for(close_started.wait(), timeout=1)
                self.assertFalse(task.done(), "连接仍在关闭时不能报告整个运行已结束")
                self.assertFalse(close_finished.is_set())
                self.assertFalse(any(record["type"] == "run_end" for record in self.session.load().records))
                self.assertEqual(self.provider.requests, [])
                close_release.set()
                done, _ = await asyncio.wait({task}, timeout=2)
                self.assertIn(task, done, "连接收尾后请求循环应完成取消结算")
                result = await task
                await asyncio.wait_for(server.disconnected.wait(), timeout=1)
            finally:
                close_release.set()  # 断言失败也释放门闩，避免把测试资源留在后台。

        self.assertTrue(close_finished.is_set())
        self.assert_closed(server, 1)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(self.provider.requests, [])
        self.executor.execute.assert_not_awaited()
        loaded = self.session.load()
        self.assertEqual(loaded.history, self.initial)
        self.assertEqual(result.messages, self.initial)
        self.assertEqual([record["type"] for record in loaded.records].count("run_end"), 1)
        self.assertEqual(loaded.records[-1]["data"]["status"], "cancelled")
        request = json.loads(server.requests[0]["body"])
        self.assertEqual(request["parameters"]["text_type"], "query")
        self.assertEqual(request["input"]["texts"], [QUERY])
        self.assertEqual(len(embedder.request_records), 1)
        self.assertEqual(embedder.request_records[0]["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
