"""D12：真实本地 HTTPS 的响应、错误、取消和资源关闭验证。"""

import asyncio
import json
import unittest
from unittest.mock import patch

from mini_pi.async_http_transport import MAX_RESPONSE_BYTES, post_json_async
from tests.http_test_server import LocalHttpsServer


class AsyncHttpTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = await LocalHttpsServer().start()
        self.addAsyncCleanup(self.server.close)
        client_patch = patch("mini_pi.async_http_transport._make_client", side_effect=self.server.make_client)
        client_patch.start()
        self.addCleanup(client_patch.stop)
        self.previous_handler = asyncio.get_running_loop().get_exception_handler()
        self.background_errors = []
        asyncio.get_running_loop().set_exception_handler(
            lambda loop, context: self.background_errors.append(context)
        )

    async def asyncTearDown(self):
        await asyncio.sleep(0)
        asyncio.get_running_loop().set_exception_handler(self.previous_handler)
        self.assertEqual(self.background_errors, [])
        self.assertEqual(self.server.errors, [])

    def send(self, **kwargs):
        return post_json_async(self.server.url, "synthetic-test-token", {"text": "你好"}, **kwargs)

    async def _settle(self, task, release=None):
        if release is not None:
            release.set()
        if not task.done():
            task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        self.assertIn(task, done, "测试清理后请求任务仍未结束")
        try:
            task.result()
        except (asyncio.CancelledError, Exception):
            pass

    def _start(self, *, release=None):
        task = asyncio.create_task(self.send(timeout=5))
        self.addAsyncCleanup(self._settle, task, release)
        return task

    def assert_clients_closed(self):
        self.assertTrue(self.server.clients)
        self.assertTrue(all(client.is_closed for client in self.server.clients))
        self.assertTrue(all(response.is_closed for response in self.server.responses))

    async def assert_disconnected(self):
        await asyncio.wait_for(self.server.disconnected.wait(), 1)
        self.assert_clients_closed()
        self.assertEqual(len(self.server.requests), 1, "不得自动重试")

    async def test_https_success_returns_json_and_preserves_payload(self):
        payload = {"text": "你好"}
        result = await post_json_async(self.server.url, "synthetic-test-token", payload)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(payload, {"text": "你好"})
        request = self.server.requests[0]
        self.assertEqual(request["start"], "POST /v1/chat/completions HTTP/1.1")
        self.assertEqual(json.loads(request["body"]), payload)
        self.assertEqual(request["headers"]["authorization"], "Bearer synthetic-test-token")
        self.assert_clients_closed()

    async def test_unsafe_urls_fail_before_creating_client(self):
        for url in ("http://127.0.0.1/", "https://user:password@127.0.0.1/", "https:///missing"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    await post_json_async(url, "synthetic-test-token", {})
        self.assertEqual(self.server.clients, [])
        self.assertEqual(self.server.requests, [])

    async def test_http_error_hides_raw_body_and_token_without_retry(self):
        self.server.status = 401
        self.server.body = b"private-server-body synthetic-test-token"
        with self.assertRaisesRegex(RuntimeError, "HTTP 401") as caught:
            await self.send()
        self.assertNotIn("private-server-body", str(caught.exception))
        self.assertNotIn("synthetic-test-token", str(caught.exception))
        self.assertEqual(len(self.server.requests), 1)
        self.assert_clients_closed()

    async def test_redirect_is_rejected_without_following_location(self):
        self.server.status = 302
        with self.assertRaisesRegex(RuntimeError, "HTTP 302"):
            await self.send()
        self.assertEqual(len(self.server.requests), 1)
        self.assert_clients_closed()

    async def test_invalid_utf8_json_and_non_object_are_rejected(self):
        for body, message in ((b"\xff", "UTF-8 JSON"), (b"{broken", "UTF-8 JSON"), (b"[]", "必须是对象")):
            with self.subTest(body=body):
                self.server.body = body
                with self.assertRaisesRegex(RuntimeError, message):
                    await self.send()
                self.assert_clients_closed()

    async def test_response_size_limit_closes_resources(self):
        self.server.body = b"x" * (MAX_RESPONSE_BYTES + 1)
        with self.assertRaisesRegex(RuntimeError, "大小限制"):
            await self.send()
        self.assert_clients_closed()

    async def test_request_own_timeout_closes_connection_without_retry(self):
        self.server.mode = "hang_headers"
        with self.assertRaisesRegex(RuntimeError, "连接失败或超时"):
            await self.send(timeout=0.1)
        await self.assert_disconnected()

    async def test_cancel_before_response_headers_disconnects_without_server_reply(self):
        self.server.mode = "hang_headers"
        task = self._start()
        await asyncio.wait_for(self.server.started.wait(), 2)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=1)
        self.assertIn(task, done, "取消不应继续等待服务端回复")
        with self.assertRaises(asyncio.CancelledError):
            await task
        await self.assert_disconnected()

    async def test_cancel_during_response_body_disconnects_and_closes_response(self):
        self.server.mode = "hang_body"
        task = self._start()
        await asyncio.wait_for(self.server.response_seen.wait(), 2)
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=1)
        self.assertIn(task, done)
        with self.assertRaises(asyncio.CancelledError):
            await task
        await self.assert_disconnected()

    async def test_repeated_cancel_does_not_interrupt_client_cleanup(self):
        self.server.mode = "hang_headers"
        cleanup_started = asyncio.Event()
        cleanup_release = asyncio.Event()
        cleanup_finished = asyncio.Event()
        make_client = self.server.make_client

        def client_with_controlled_close(timeout):
            client = make_client(timeout)
            real_close = client.aclose

            async def close():
                cleanup_started.set()
                await cleanup_release.wait()
                await real_close()
                cleanup_finished.set()

            client.aclose = close
            return client

        with patch("mini_pi.async_http_transport._make_client", side_effect=client_with_controlled_close):
            task = self._start(release=cleanup_release)
            await asyncio.wait_for(self.server.started.wait(), 2)
            task.cancel()
            await asyncio.wait_for(cleanup_started.wait(), 1)
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=0.02)
            self.assertFalse(done, "清理尚未结束时不得提前返回")
            self.assertFalse(cleanup_finished.is_set())
            cleanup_release.set()
            done, _ = await asyncio.wait({task}, timeout=1)
            self.assertIn(task, done)
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(cleanup_finished.is_set())
        await self.assert_disconnected()

    async def test_cleanup_failure_is_reported_without_exposing_details(self):
        make_client = self.server.make_client

        def client_with_failed_close(timeout):
            client = make_client(timeout)
            real_close = client.aclose

            async def close():
                await real_close()
                raise RuntimeError("private-cleanup-detail synthetic-test-token")

            client.aclose = close
            return client

        with patch("mini_pi.async_http_transport._make_client", side_effect=client_with_failed_close):
            with self.assertRaisesRegex(RuntimeError, "清理失败") as caught:
                await self.send()
        self.assertNotIn("private-cleanup-detail", str(caught.exception))
        self.assertNotIn("synthetic-test-token", str(caught.exception))
        self.assert_clients_closed()


if __name__ == "__main__":
    unittest.main()
