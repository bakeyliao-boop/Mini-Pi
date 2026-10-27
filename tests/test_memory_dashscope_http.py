"""MEM-03实际适配器的本地HTTPS成功、取消与超时反例。

只替换客户端工厂以信任公开合成证书，正式HTTP发送与清理保持实际执行。
不读取凭据，不访问外部服务，也不依赖本机阶段证据。
"""

import asyncio
from contextlib import suppress
import json
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx

from mini_pi.memory.dashscope_embedding import DashScopeEmbedder
from tests.http_test_server import LocalHttpsServer


SYNTHETIC_KEY = "synthetic-embedding-http-test-token"
DIMENSIONS = 1024



def vector(first, second):
    return [first, second] + [0] * (DIMENSIONS - 2)


def unit_at(index):
    values = [0.0] * DIMENSIONS
    values[index] = 1.0
    return tuple(values)


def batch_body(start, count, number):
    return json.dumps({
        "request_id": f"synthetic-local-batch-{number}",
        "usage": {"total_tokens": count},
        "output": {"embeddings": [
            {"text_index": local_index, "embedding": unit_at(start + local_index)}
            for local_index in reversed(range(count))
        ]},
    }).encode()


class DashScopeBatchHttpTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.server = await LocalHttpsServer().start()
        self.addAsyncCleanup(self._close_server)
        client_patch = patch(
            "mini_pi.async_http_transport._make_client", side_effect=self.server.make_client,
        )
        client_patch.start()
        self.addCleanup(client_patch.stop)

    async def _close_server(self):
        await self.server.close()
        self.assertEqual(self.server.errors, [])

    def embedder(self, timeout=30.0):
        parts = urlsplit(self.server.url)
        return DashScopeEmbedder(
            SYNTHETIC_KEY, base_url=f"{parts.scheme}://{parts.netloc}/api/v1", timeout=timeout,
        )

    def assert_closed(self):
        self.assertEqual(len(self.server.requests), 1, "单批请求不得自动重试")
        self.assertTrue(self.server.clients)
        self.assertTrue(self.server.responses)
        self.assertTrue(all(client.is_closed for client in self.server.clients))
        self.assertTrue(all(response.is_closed for response in self.server.responses))

    def assert_record(self, embedder, status, texts, *, tokens=None, request_id=None):
        self.assertEqual(len(embedder.request_records), 1)
        record = embedder.request_records[0]
        self.assertEqual(set(record), {
            "model", "dimensions", "text_type", "text_count", "request_id",
            "total_tokens", "status", "elapsed_seconds",
        })
        self.assertEqual(record["status"], status)
        self.assertEqual(record["text_count"], len(texts))
        self.assertEqual(record["text_type"], "document")
        self.assertEqual(record["model"], "text-embedding-v4")
        self.assertEqual(record["dimensions"], DIMENSIONS)
        self.assertEqual(record["total_tokens"], tokens)
        self.assertEqual(record["request_id"], request_id)
        self.assertGreaterEqual(record["elapsed_seconds"], 0)
        rendered = json.dumps(record, ensure_ascii=False)
        self.assertNotIn(SYNTHETIC_KEY, rendered)
        for text in texts:
            self.assertNotIn(text, rendered)

    async def _settle(self, task):
        if not task.done():
            task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        self.assertIn(task, done, "测试清理后请求任务仍未退出")
        with suppress(asyncio.CancelledError, Exception):
            await task

    async def test_native_success_payload_order_and_resource_close(self):
        self.server.body = json.dumps({
            "request_id": "synthetic-http-request-id", "usage": {"total_tokens": 17},
            "output": {"embeddings": [
                {"text_index": 1, "embedding": vector(0, -7)},
                {"text_index": 0, "embedding": vector(3, 4)},
            ]},
        }).encode()
        texts = ["  本地HTTPS第一条原文。", "本地HTTPS第二条原文。\n"]
        original = texts.copy()
        embedder = self.embedder()
        result = await embedder._embed_batch(texts, "document")
        self.assertEqual(result, (tuple(vector(0.6, 0.8)), tuple(vector(0.0, -1.0))))
        self.assertEqual(texts, original)
        self.assert_closed()
        request = self.server.requests[0]
        self.assertEqual(request["start"],
                         "POST /api/v1/services/embeddings/text-embedding/text-embedding HTTP/1.1")
        self.assertEqual(request["headers"]["authorization"], "Bearer " + SYNTHETIC_KEY)
        self.assertEqual(json.loads(request["body"]), {
            "model": "text-embedding-v4", "input": {"texts": original},
            "parameters": {"text_type": "document", "dimension": DIMENSIONS,
                           "output_type": "dense"},
        })
        self.assert_record(embedder, "validated", texts, tokens=17,
                           request_id="synthetic-http-request-id")

    async def test_cancel_waiting_for_body_disconnects_and_closes_resources(self):
        self.server.mode = "hang_body"
        texts = ["本地HTTPS取消边界原文"]
        embedder = self.embedder(timeout=5)
        task = asyncio.create_task(embedder._embed_batch(texts, "document"))
        self.addAsyncCleanup(self._settle, task)
        response_waiter = asyncio.create_task(self.server.response_seen.wait())
        self.addAsyncCleanup(self._settle, response_waiter)
        done, _ = await asyncio.wait(
            {task, response_waiter}, timeout=2, return_when=asyncio.FIRST_COMPLETED,
        )
        if task in done:
            await task
            self.fail("尚未取消，请求已意外返回")
        self.assertIn(response_waiter, done, "服务端未进入响应体等待阶段")
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        self.assertIn(task, done, "取消后请求未完成收尾")
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(self.server.disconnected.wait(), 1)
        self.assert_closed()
        self.assert_record(embedder, "cancelled", texts)

    async def _assert_short_body_read_timeout_disconnects(self):
        self.server.mode = "hang_body"
        texts = ["本地HTTPS超时边界原文"]
        embedder = self.embedder(timeout=0.1)

        def body_timeout_client(timeout):
            client = self.server.make_client(timeout)
            # 本用例只测试短响应体读取超时；建连、发送和连接池不共用100ms时限。
            client.timeout = httpx.Timeout(timeout, connect=2.0, write=2.0, pool=2.0)
            return client

        with patch("mini_pi.async_http_transport._make_client", side_effect=body_timeout_client):
            with self.assertRaisesRegex(RuntimeError, "连接失败或超时"):
                await embedder._embed_batch(texts, "document")
        self.assertTrue(self.server.response_seen.is_set(), "尚未收到响应头，不能认定验证了响应体读取超时")
        await asyncio.wait_for(self.server.disconnected.wait(), 1)
        self.assert_closed()
        self.assert_record(embedder, "error", texts)

    async def test_short_read_timeout_disconnects_and_does_not_retry(self):
        await self._assert_short_body_read_timeout_disconnects()

    async def test_short_read_timeout_still_reaches_body_after_slow_tls_handshake(self):
        def slow_handshake(ssl_object, server_name, ssl_context):
            time.sleep(0.2)  # 受控慢握手：超过读取时限，仍小于独立的建连时限。
        self.server.server_context.set_servername_callback(slow_handshake)
        await self._assert_short_body_read_timeout_disconnects()


class DashScopeQueryHttpTests(unittest.IsolatedAsyncioTestCase):

    async def test_local_https_query_cancellation_disconnects_and_closes_resources(self):
        server = await LocalHttpsServer(mode="hang_body").start()
        parts = urlsplit(server.url)
        embedder = DashScopeEmbedder(
            SYNTHETIC_KEY, base_url=f"{parts.scheme}://{parts.netloc}/api/v1", timeout=5,
        )
        text = "本地HTTPS取消query原文"
        task = None
        waiter = None
        try:
            with patch("mini_pi.async_http_transport._make_client", side_effect=server.make_client):
                task = asyncio.create_task(embedder.embed_query(text))
                waiter = asyncio.create_task(server.response_seen.wait())
                done, _ = await asyncio.wait(
                    {task, waiter}, timeout=2, return_when=asyncio.FIRST_COMPLETED,
                )
                if task in done:
                    await task
                    self.fail("query在取消前已意外返回")
                self.assertIn(waiter, done, "本地HTTPS尚未进入响应体等待阶段")
                task.cancel()
                done, _ = await asyncio.wait({task}, timeout=2)
                self.assertIn(task, done, "query取消后未完成收尾")
                with self.assertRaises(asyncio.CancelledError):
                    await task
                await asyncio.wait_for(server.disconnected.wait(), 1)
            self.assertEqual(len(server.requests), 1, "取消期间不得自动重试")
            self.assertTrue(server.clients)
            self.assertTrue(server.responses)
            self.assertTrue(all(client.is_closed for client in server.clients))
            self.assertTrue(all(response.is_closed for response in server.responses))
            request = json.loads(server.requests[0]["body"])
            self.assertEqual(request["input"], {"texts": [text]})
            self.assertEqual(request["parameters"]["text_type"], "query")
            self.assertEqual(len(embedder.request_records), 1)
            record = embedder.request_records[0]
            self.assertEqual(record["status"], "cancelled")
            self.assertEqual(record["text_type"], "query")
            self.assertEqual(record["text_count"], 1)
            self.assertIsNone(record["total_tokens"])
            self.assertNotIn(text, json.dumps(record, ensure_ascii=False))
            self.assertNotIn(SYNTHETIC_KEY, json.dumps(record))
        finally:
            for pending in (waiter, task):
                if pending is not None:
                    if not pending.done():
                        pending.cancel()
                    done, _ = await asyncio.wait({pending}, timeout=2)
                    self.assertIn(pending, done, "测试清理后仍有在途任务")
                    with suppress(asyncio.CancelledError, Exception):
                        await pending
            await server.close()
        self.assertEqual(server.errors, [])


class DashScopeDocumentsHttpTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.server = await LocalHttpsServer().start()
        self.addAsyncCleanup(self._close_server)
        parts = urlsplit(self.server.url)
        self.embedder = DashScopeEmbedder(
            SYNTHETIC_KEY, base_url=f"{parts.scheme}://{parts.netloc}/api/v1", timeout=5,
        )
        self.texts = [f"  本地HTTPS第{number:02d}条正文。\n" for number in range(23)]

    async def _close_server(self):
        await self.server.close()
        self.assertEqual(self.server.errors, [])

    async def _settle(self, task):
        if not task.done():
            task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        self.assertIn(task, done, "测试清理后仍有在途任务")
        with suppress(asyncio.CancelledError, Exception):
            await task

    def assert_requests_and_closed(self, sizes):
        self.assertEqual(len(self.server.requests), len(sizes), "HTTP请求数必须与计划批次一致")
        self.assertEqual(len(self.server.clients), len(sizes))
        self.assertEqual(len(self.server.responses), len(sizes))
        self.assertTrue(all(client.is_closed for client in self.server.clients))
        self.assertTrue(all(response.is_closed for response in self.server.responses))
        start = 0
        for request, size in zip(self.server.requests, sizes, strict=True):
            self.assertEqual(request["start"],
                             "POST /api/v1/services/embeddings/text-embedding/text-embedding HTTP/1.1")
            self.assertEqual(request["headers"]["authorization"], "Bearer " + SYNTHETIC_KEY)
            self.assertEqual(json.loads(request["body"]), {
                "model": "text-embedding-v4", "input": {"texts": self.texts[start:start + size]},
                "parameters": {"text_type": "document", "dimension": DIMENSIONS,
                               "output_type": "dense"},
            })
            start += size

    async def test_23_documents_make_10_10_3_real_requests_and_restore_flat_order(self):
        created = 0

        def client_for_batch(timeout):
            nonlocal created
            created += 1
            self.assertLessEqual(created, 3, "不允许额外请求")
            start = (created - 1) * 10
            count = min(10, len(self.texts) - start)
            self.server.mode = "normal"
            self.server.body = batch_body(start, count, created)
            return self.server.make_client(timeout)

        with patch("mini_pi.async_http_transport._make_client", side_effect=client_for_batch):
            result = await self.embedder.embed_documents(self.texts)
        self.assertEqual(result, tuple(unit_at(index) for index in range(23)))
        self.assertEqual(len(result), 23, "结果必须是平铺的23个向量")
        self.assert_requests_and_closed([10, 10, 3])
        records = self.embedder.request_records
        self.assertEqual([record["status"] for record in records], ["validated"] * 3)
        self.assertEqual([record["text_count"] for record in records], [10, 10, 3])
        self.assertEqual([record["total_tokens"] for record in records], [10, 10, 3])

    async def test_second_batch_body_cancellation_disconnects_without_third_or_partial_result(self):
        created = 0
        second_client_created = asyncio.Event()

        def client_for_batch(timeout):
            nonlocal created
            created += 1
            self.assertLessEqual(created, 2, "取消后不得创建第三批客户端")
            if created == 1:
                self.server.mode = "normal"
                self.server.body = batch_body(0, 10, 1)
            else:
                self.server.mode = "hang_body"
                self.server.body = b'{"controlled-second-batch":true}'
                self.server.response_seen.clear()
                self.server.disconnected.clear()
                second_client_created.set()
            return self.server.make_client(timeout)

        async def second_response_seen():
            await second_client_created.wait()
            await self.server.response_seen.wait()

        with patch("mini_pi.async_http_transport._make_client", side_effect=client_for_batch):
            task = asyncio.create_task(self.embedder.embed_documents(self.texts))
            self.addAsyncCleanup(self._settle, task)
            waiter = asyncio.create_task(second_response_seen())
            self.addAsyncCleanup(self._settle, waiter)
            done, _ = await asyncio.wait(
                {task, waiter}, timeout=3, return_when=asyncio.FIRST_COMPLETED,
            )
            if task in done:
                await task
                self.fail("取消前不得返回前批部分结果")
            self.assertIn(waiter, done, "未进入第二批响应体等待阶段")
            self.assertEqual(len(self.server.requests), 2)
            self.assertEqual(len(self.server.responses), 2)
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=2)
            self.assertIn(task, done, "取消后未完成连接收尾")
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(self.server.disconnected.wait(), 1)
        self.assert_requests_and_closed([10, 10])
        records = self.embedder.request_records
        self.assertEqual([record["status"] for record in records], ["validated", "cancelled"])
        self.assertEqual([record["text_count"] for record in records], [10, 10])
        self.assertEqual(records[0]["total_tokens"], 10)
        self.assertEqual(records[0]["request_id"], "synthetic-local-batch-1")
        self.assertIsNone(records[1]["total_tokens"])
        self.assertIsNone(records[1]["request_id"])


if __name__ == "__main__":
    unittest.main()
