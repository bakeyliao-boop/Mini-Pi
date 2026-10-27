"""提取请求和异步适配器：合成响应与真实本地HTTPS，不访问外部模型。

父_send的received仅代表收到响应，request_body仍在实例内存保留原文。
本组不评估真实提取语义，不读取环境凭据，也不访问业务数据库。
"""

import asyncio
from contextlib import ExitStack, contextmanager, suppress
from copy import deepcopy
from dataclasses import asdict, replace
import json
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.extraction_client import MemoryExtractor, build_extraction_request
from mini_pi.memory.models import MemoryScope, MemorySource
from tests.http_test_server import LocalHttpsServer


SYNTHETIC_KEY = "synthetic-extraction-test-token"
MODEL = "synthetic-extraction-model"
MAX_TOKENS = 300


def inputs():
    scope = MemoryScope("extract-client-user", "mini-pi")
    source = MemorySource(
        "extract-client-source", scope, "user",
        '以后讲解请尽量用 Python 举例。\n今天只解释。原文标记："SOURCE-TEST-MARKER"。',
        "2026-10-23T10:00:00+08:00",
    )
    return scope, source


def response():
    items = [{"content": "用户希望后续讲解尽量使用 Python 示例。", "proposed_route": "long_term", "reason": "固定建议。"},
             {"content": "今天只解释。", "proposed_route": "task_constraint", "reason": "本次限制。"}]
    return {"model": MODEL, "usage": {"prompt_tokens": 9, "completion_tokens": 5, "total_tokens": 14},
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(items, ensure_ascii=False),
            }}]}


@contextmanager
def no_memory_calls():
    with ExitStack() as stack:
        calls = [stack.enter_context(patch("sqlite3.connect", side_effect=AssertionError("提取不得开库")))]
        calls.extend(stack.enter_context(patch(
            "mini_pi.memory.store.MemoryStore." + name, side_effect=AssertionError("提取不得调用Store"),
        )) for name in ("get", "latest", "remember", "replace", "retract"))
        yield
        for call in calls:
            call.assert_not_called()


class ExtractionRequestTests(unittest.TestCase):
    def test_request_preserves_complete_source_json_and_separates_system_from_user_data(self):
        scope, source = inputs()
        before = (asdict(scope), asdict(source))
        with no_memory_calls():
            for role in ("user", "tool"):
                with self.subTest(role=role):
                    current = replace(source, role=role)
                    request = build_extraction_request(MODEL, scope, current)
                    self.assertEqual((request["model"], request["stream"]), (MODEL, False))
                    self.assertNotIn("tools", request)
                    self.assertEqual([item["role"] for item in request["messages"]], ["system", "user"])
                    instruction = request["messages"][0]["content"]
                    self.assertIsInstance(instruction, str)
                    self.assertNotIn(current.text, instruction)
                    for field in ("content", "proposed_route", "reason"):
                        self.assertIn(field, instruction)
                    self.assertEqual(json.loads(request["messages"][1]["content"]), {
                        "role": role, "recorded_at": current.recorded_at, "text": current.text,
                    })
        self.assertEqual((asdict(scope), asdict(source)), before)


class MemoryExtractorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.scope, self.source = inputs()
        self.received = response()
        self.enterContext(no_memory_calls())

    def extractor(self, *, base_url="https://synthetic.invalid/v1", timeout=5.0, max_requests=2):
        return MemoryExtractor(api_key=SYNTHETIC_KEY, model=MODEL, base_url=base_url,
                               timeout=timeout, max_requests=max_requests, max_completion_tokens=MAX_TOKENS)

    async def server(self, *, mode="normal"):
        server = await LocalHttpsServer(mode=mode, body=json.dumps(self.received, ensure_ascii=False).encode()).start()

        async def close():
            await server.close()
            self.assertEqual(server.errors, [])

        self.addAsyncCleanup(close)
        return server

    async def settle(self, task, release=None):
        if release is not None:
            release.set()
        if not task.done():
            task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        self.assertIn(task, done, "测试清理后仍有在途提取")
        with suppress(asyncio.CancelledError, Exception):
            task.result()

    def assert_closed(self, server, *, response_expected=True):
        self.assertEqual(len(server.requests), 1, "不得自动重试")
        self.assertTrue(server.clients)
        self.assertTrue(all(client.is_closed for client in server.clients))
        if response_expected:
            self.assertTrue(server.responses)
        else:
            self.assertEqual(server.responses, [])
        self.assertTrue(all(item.is_closed for item in server.responses))

    async def test_bad_source_scope_role_format_and_model_fail_before_http_or_request_count(self):
        cases = [(None, self.source), (self.scope, None),
                 (self.scope, replace(self.source, scope=MemoryScope("other-user", self.scope.project_id))),
                 (self.scope, replace(self.source, role="assistant")),
                 (self.scope, replace(self.source, text=" \n")),
                 (self.scope, replace(self.source, recorded_at="2026-10-23T10:00:00"))]
        post = AsyncMock(return_value=self.received)
        with patch("mini_pi.qwen_client.post_json_async", post):
            for scope, source in cases:
                with self.subTest(scope=scope, source=source):
                    client = self.extractor()
                    with self.assertRaises(MemoryPolicyError):
                        await client.extract(scope, source)
                    self.assertEqual((client.request_count, client.request_records), (0, []))
            for model in ("", " \n", None, 42):
                with self.subTest(model=model):
                    with self.assertRaises(MemoryPolicyError):
                        build_extraction_request(model, self.scope, self.source)
            post.assert_not_called()

    async def test_parent_send_mock_response_reaches_bound_candidates_and_records_received_only(self):
        client = self.extractor()
        original = deepcopy(self.received)
        with patch("mini_pi.qwen_client.post_json_async", AsyncMock(return_value=self.received)) as post:
            parsed = await client.extract(self.scope, self.source)
            post.assert_awaited_once()
        self.assertEqual([item.proposed_route for item in parsed], ["long_term", "task_constraint"])
        self.assertTrue(all(item.source is self.source for item in parsed))
        self.assertEqual(self.received, original)
        self.assertEqual(client.request_count, 1)
        self.assertEqual(len(client.request_records), 1)
        record = client.request_records[0]
        self.assertEqual((record["status"], record["finish_reason"], record["usage"]),
                         ("received", "stop", self.received["usage"]))
        payload = post.await_args.args[2]
        self.assertEqual(record["request_body"], payload)
        self.assertEqual((payload["max_completion_tokens"], payload["enable_thinking"]), (MAX_TOKENS, False))
        self.assertEqual(json.loads(payload["messages"][1]["content"])["text"], self.source.text)
        self.assertNotIn(SYNTHETIC_KEY, json.dumps(client.request_records, ensure_ascii=False))

    async def test_send_exception_identity_and_bad_responses_propagate_without_retry(self):
        length = deepcopy(self.received)
        length["choices"][0]["finish_reason"] = "length"
        bad_json = deepcopy(self.received)
        bad_json["choices"][0]["message"]["content"] = "{"
        failure = RuntimeError("controlled synthetic send failure")
        for label, value in (("send_error", failure), ("length", length), ("bad_json", bad_json)):
            with self.subTest(case=label):
                client = self.extractor()
                post = AsyncMock(side_effect=value) if isinstance(value, Exception) else AsyncMock(return_value=value)
                with patch("mini_pi.qwen_client.post_json_async", post):
                    with self.assertRaises(RuntimeError if label == "send_error" else MemoryPolicyError) as caught:
                        await client.extract(self.scope, self.source)
                    post.assert_awaited_once()
                if label == "send_error":
                    self.assertIs(caught.exception, failure)
                self.assertEqual(client.request_count, 1)
                self.assertEqual(len(client.request_records), 1)
                self.assertEqual(client.request_records[0]["status"],
                                 "request_error" if label == "send_error" else "received")

    async def test_instance_request_budget_blocks_second_call_before_http(self):
        client = self.extractor(max_requests=1)
        with patch("mini_pi.qwen_client.post_json_async", AsyncMock(return_value=self.received)) as post:
            await client.extract(self.scope, self.source)
            with self.assertRaises(RuntimeError):
                await client.extract(self.scope, self.source)
            post.assert_awaited_once()
        self.assertEqual((client.request_count, len(client.request_records)), (1, 1))

    async def test_already_requested_cancel_prevents_parent_send_and_http(self):
        client = self.extractor()

        async def cancel_then_extract():
            asyncio.current_task().cancel()
            return await client.extract(self.scope, self.source)

        with patch("mini_pi.qwen_client.post_json_async", AsyncMock(return_value=self.received)) as post:
            task = asyncio.create_task(cancel_then_extract())
            self.addAsyncCleanup(self.settle, task)
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)
            post.assert_not_called()
        self.assertEqual((client.request_count, client.request_records), (0, []))

    async def test_real_local_https_success_captures_payload_and_closes_resources(self):
        server = await self.server()
        client = self.extractor(base_url=server.url.removesuffix("/chat/completions"), max_requests=1)
        with patch("mini_pi.async_http_transport._make_client", side_effect=server.make_client):
            parsed = await client.extract(self.scope, self.source)
        self.assertTrue(all(item.source is self.source for item in parsed))
        self.assertEqual(len(parsed), 2)
        self.assert_closed(server)
        request = server.requests[0]
        self.assertEqual(request["start"], "POST /v1/chat/completions HTTP/1.1")
        payload = json.loads(request["body"])
        self.assertEqual((payload["model"], payload["stream"], payload["max_completion_tokens"]),
                         (MODEL, False, MAX_TOKENS))
        self.assertNotIn("tools", payload)
        self.assertEqual(json.loads(payload["messages"][1]["content"]), {
            "role": self.source.role, "recorded_at": self.source.recorded_at, "text": self.source.text,
        })
        self.assertEqual((client.request_count, client.request_records[0]["status"]), (1, "received"))

    async def test_real_body_cancel_waits_for_close_even_when_cancelled_again(self):
        server = await self.server(mode="hang_body")
        client = self.extractor(base_url=server.url.removesuffix("/chat/completions"))
        close_started, close_release, close_finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

        def held_close(timeout):
            resource = server.make_client(timeout)
            real_close = resource.aclose

            async def close():
                close_started.set()
                await close_release.wait()
                await real_close()
                close_finished.set()

            resource.aclose = close
            return resource

        with patch("mini_pi.async_http_transport._make_client", side_effect=held_close):
            task = asyncio.create_task(client.extract(self.scope, self.source))
            self.addAsyncCleanup(self.settle, task, close_release)
            await asyncio.wait_for(server.response_seen.wait(), 2)
            task.cancel()
            await asyncio.wait_for(close_started.wait(), 1)
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=0.02)
            self.assertFalse(done, "客户端仍在收尾时不能报告提取取消完成")
            self.assertFalse(close_finished.is_set())
            close_release.set()
            done, _ = await asyncio.wait({task}, timeout=2)
            self.assertIn(task, done)
            with self.assertRaises(asyncio.CancelledError):
                await task
        await asyncio.wait_for(server.disconnected.wait(), 1)
        self.assertTrue(close_finished.is_set())
        self.assert_closed(server)
        self.assertEqual((client.request_count, len(client.request_records)), (1, 1))
        self.assertEqual(client.request_records[0]["status"], "cancelled")

    async def test_real_header_timeout_disconnects_closes_client_and_does_not_retry(self):
        server = await self.server(mode="hang_headers")
        client = self.extractor(base_url=server.url.removesuffix("/chat/completions"), timeout=0.3)
        with (patch("mini_pi.async_http_transport._make_client", side_effect=server.make_client),
              patch("mini_pi.memory.extraction_client.parse_extraction_response",
                    side_effect=AssertionError("发送失败不得解析为候选")) as parse):
            with self.assertRaisesRegex(RuntimeError, "连接失败或超时"):
                await client.extract(self.scope, self.source)
            parse.assert_not_called()
        await asyncio.wait_for(server.disconnected.wait(), 1)
        self.assert_closed(server, response_expected=False)
        self.assertEqual((client.request_count, len(client.request_records)), (1, 1))
        self.assertEqual(client.request_records[0]["status"], "request_error")


if __name__ == "__main__":
    unittest.main()
