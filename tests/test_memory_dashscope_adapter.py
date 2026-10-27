"""MEM-03适配器入口与分批合同；仅合成响应，不读取凭据或访问外部服务。

从仓库根目录运行 unittest discover；本文件不依赖本机阶段证据。
"""

import asyncio
from contextlib import suppress
from copy import deepcopy
import json
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.memory.dashscope_embedding import DashScopeEmbedder
from mini_pi.memory.errors import MemoryEmbeddingError


SYNTHETIC_KEY = "synthetic-embedding-test-token"
DIMENSIONS = 1024
RECORD_KEYS = {
    "model", "dimensions", "text_type", "text_count", "request_id",
    "total_tokens", "status", "elapsed_seconds",
}



def vector(first, second):
    return [first, second] + [0] * (DIMENSIONS - 2)


def response(items, *, usage=True):
    value = {
        "request_id": "synthetic-request-id",
        "output": {"embeddings": [
            {"text_index": index, "embedding": values}
            for index, values in items
        ]},
    }
    if usage:
        value["usage"] = {"total_tokens": 17}
    return value


def payload(texts, mode):
    return {"model": "text-embedding-v4", "input": {"texts": texts},
            "parameters": {"text_type": mode, "dimension": DIMENSIONS,
                           "output_type": "dense"}}


def original_texts(count):
    return [f"  第{number:02d}条记忆原文。\n" for number in range(count)]


def unit_at(index):
    values = [0.0] * DIMENSIONS
    values[index] = 1.0
    return tuple(values)


def native_reply(payload, originals, request_number):
    """每批text_index从0重算且倒序返回；向量位置标识最初原文的全局顺序。"""
    by_text = {text: index for index, text in enumerate(originals)}
    texts = payload["input"]["texts"]
    return {
        "request_id": f"synthetic-batch-{request_number}",
        "usage": {"total_tokens": len(texts)},
        "output": {"embeddings": [
            {"text_index": local_index, "embedding": list(unit_at(by_text[text]))}
            for local_index, text in reversed(list(enumerate(texts)))
        ]},
    }


class BatchAssertions:

    def make_embedder(self, **kwargs):
        return DashScopeEmbedder(SYNTHETIC_KEY, **kwargs)

    def assert_record(self, embedder, *, mode, count, status,
                      tokens=17, request_id="synthetic-request-id", texts=()):
        self.assertEqual(len(embedder.request_records), 1)
        record = embedder.request_records[0]
        self.assertEqual(set(record), RECORD_KEYS)
        self.assertEqual(record["model"], "text-embedding-v4")
        self.assertEqual(record["dimensions"], DIMENSIONS)
        self.assertEqual(record["text_type"], mode)
        self.assertEqual(record["text_count"], count)
        self.assertEqual(record["status"], status)
        self.assertEqual(record["total_tokens"], tokens)
        self.assertEqual(record["request_id"], request_id)
        self.assertGreaterEqual(record["elapsed_seconds"], 0)
        rendered = json.dumps(record, ensure_ascii=False)
        self.assertNotIn(SYNTHETIC_KEY, rendered)
        for text in texts:
            self.assertNotIn(text, rendered)

    def assert_payload(self, send, embedder, texts, mode):
        send.assert_awaited_once_with(
            embedder.endpoint, SYNTHETIC_KEY,
            payload(texts, mode),
            30.0,
        )
        self.assertTrue(embedder.endpoint.endswith(
            "/api/v1/services/embeddings/text-embedding/text-embedding"))


class DashScopeBatchTests(BatchAssertions, unittest.IsolatedAsyncioTestCase):

    async def test_query_preserves_original_text_and_native_payload(self):
        texts = ["  请解释依赖下载失败；不要丢掉空白。\n"]
        original = texts.copy()
        embedder = self.make_embedder()
        send = AsyncMock(return_value=response([(0, vector(3, 4))]))
        with patch("mini_pi.memory.dashscope_embedding.post_json_async", send):
            result = await embedder._embed_batch(texts, "query")
        self.assert_payload(send, embedder, original, "query")
        self.assertEqual(texts, original)
        self.assertEqual(result, (tuple(vector(0.6, 0.8)),))
        self.assert_record(embedder, mode="query", count=1, status="validated", texts=texts)

    async def test_documents_restore_response_order_and_keep_input_unchanged(self):
        texts = ["  第一条记忆原文。", "第二条记忆原文。\n"]
        original = texts.copy()
        returned = response([(1, vector(0, -7)), (0, vector(3, 4))])
        original_response = deepcopy(returned)
        embedder = self.make_embedder()
        send = AsyncMock(return_value=returned)
        with patch("mini_pi.memory.dashscope_embedding.post_json_async", send):
            result = await embedder._embed_batch(texts, "document")
        self.assert_payload(send, embedder, original, "document")
        self.assertEqual(texts, original)
        self.assertEqual(returned, original_response)
        self.assertEqual(result, (tuple(vector(0.6, 0.8)), tuple(vector(0.0, -1.0))))
        self.assert_record(embedder, mode="document", count=2, status="validated", texts=texts)

    async def test_http_failure_propagates_without_retry_or_empty_success(self):
        embedder = self.make_embedder()
        failure = RuntimeError("模型请求失败：HTTP 503；本次未自动重试")
        send = AsyncMock(side_effect=failure)
        with patch("mini_pi.memory.dashscope_embedding.post_json_async", send):
            with self.assertRaises(RuntimeError) as caught:
                await embedder._embed_batch(["HTTP失败测试原文"], "query")
        self.assertIs(caught.exception, failure)
        self.assertEqual(send.await_count, 1)
        self.assert_record(embedder, mode="query", count=1, status="error",
                           tokens=None, request_id=None, texts=("HTTP失败测试原文",))

    async def test_service_failure_is_error_without_retry_even_with_usage(self):
        embedder = self.make_embedder()
        returned = {"code": "ControlledFailure", "message": "private-service-message",
                    "request_id": "synthetic-request-id", "usage": {"total_tokens": 17}}
        send = AsyncMock(return_value=returned)
        with patch("mini_pi.memory.dashscope_embedding.post_json_async", send):
            with self.assertRaises(MemoryEmbeddingError) as caught:
                await embedder._embed_batch(["服务失败测试原文"], "document")
        self.assertNotIn("private-service-message", str(caught.exception))
        self.assertEqual(send.await_count, 1)
        self.assert_record(embedder, mode="document", count=1, status="error",
                           texts=("服务失败测试原文",))

    async def test_invalid_batch_or_mode_creates_no_http_request_or_record(self):
        cases = [
            (["第%d条" % number for number in range(11)], "document"),
            (["原文"], "invalid-mode"), (["原文"], None),
            ([" \n\t"], "query"), ([], "document"),
            (["有效原文", "  "], "document"), ("不是文本列表", "query"),
        ]
        for texts, mode in cases:
            with self.subTest(texts=texts, mode=mode):
                embedder = self.make_embedder()
                send = AsyncMock()
                with patch("mini_pi.memory.dashscope_embedding.post_json_async", send):
                    with self.assertRaises(MemoryEmbeddingError):
                        await embedder._embed_batch(texts, mode)
                send.assert_not_called()
                self.assertEqual(embedder.request_records, [])


class DashScopeRecordTests(BatchAssertions, unittest.IsolatedAsyncioTestCase):

    """发送记录只保留可得计量；不记录输入正文、凭据或服务私有字段。"""

    async def test_missing_usage_remains_unknown_instead_of_zero(self):
        embedder = self.make_embedder()
        texts = ["用量缺失测试原文"]
        send = AsyncMock(return_value=response([(0, vector(1, 0))], usage=False))
        with patch("mini_pi.memory.dashscope_embedding.post_json_async", send):
            await embedder._send_batch(payload(texts, "query"), 1, "query")
        self.assertEqual(send.await_count, 1)
        self.assert_record(embedder, mode="query", count=1, status="validated",
                           tokens=None, texts=texts)

    async def test_native_order_and_usage_whitelist(self):
        embedder = self.make_embedder()
        texts = ["辅助层第一条原文", "辅助层第二条原文"]
        returned = response([(1, vector(0, -7)), (0, vector(3, 4))])
        returned["usage"]["private"] = "不能照抄的服务字段"
        send = AsyncMock(return_value=returned)
        with patch("mini_pi.memory.dashscope_embedding.post_json_async", send):
            result = await embedder._send_batch(payload(texts, "document"), 2, "document")
        self.assertEqual(result, (tuple(vector(0.6, 0.8)), tuple(vector(0.0, -1.0))))
        self.assert_payload(send, embedder, texts, "document")
        self.assert_record(embedder, mode="document", count=2, status="validated", texts=texts)
        self.assertNotIn("不能照抄的服务字段", json.dumps(embedder.request_records, ensure_ascii=False))


class DashScopeQueryTests(unittest.IsolatedAsyncioTestCase):

    async def test_query_preserves_text_uses_one_native_request_and_returns_one_vector(self):
        text = "  依赖下载失败的原因是什么？\n"
        embedder = DashScopeEmbedder(SYNTHETIC_KEY)
        send = AsyncMock(return_value={
            "request_id": "synthetic-query-request-id", "usage": {"total_tokens": 9},
            "output": {"embeddings": [
                {"text_index": 0, "embedding": [3, 4] + [0] * (DIMENSIONS - 2)},
            ]},
        })
        with patch("mini_pi.memory.dashscope_embedding.post_json_async", send):
            result = await embedder.embed_query(text)
        send.assert_awaited_once_with(
            embedder.endpoint, SYNTHETIC_KEY,
            {"model": "text-embedding-v4", "input": {"texts": [text]},
             "parameters": {"text_type": "query", "dimension": DIMENSIONS,
                            "output_type": "dense"}},
            30.0,
        )
        self.assertEqual(result, tuple([0.6, 0.8] + [0.0] * (DIMENSIONS - 2)))
        self.assertEqual(len(result), DIMENSIONS, "返回一个向量，不能返回单元素批次")
        self.assertEqual(len(embedder.request_records), 1)
        record = embedder.request_records[0]
        self.assertEqual(record["text_type"], "query")
        self.assertEqual(record["text_count"], 1)
        self.assertEqual(record["status"], "validated")
        self.assertEqual(record["total_tokens"], 9)
        self.assertEqual(record["request_id"], "synthetic-query-request-id")
        self.assertNotIn(text, json.dumps(record, ensure_ascii=False))
        self.assertNotIn(SYNTHETIC_KEY, json.dumps(record))

    async def test_invalid_query_is_rejected_before_any_http_request(self):
        for text in (" \n\t", None, ["列表不能作为一个query"]):
            with self.subTest(text=text):
                embedder = DashScopeEmbedder(SYNTHETIC_KEY)
                send = AsyncMock()
                with patch("mini_pi.memory.dashscope_embedding.post_json_async", send):
                    with self.assertRaises(MemoryEmbeddingError):
                        await embedder.embed_query(text)
                send.assert_not_called()
                self.assertEqual(embedder.request_records, [])

    async def test_http_failure_propagates_same_exception_without_retry(self):
        embedder = DashScopeEmbedder(SYNTHETIC_KEY)
        failure = RuntimeError("受控HTTP 503；本次未自动重试")
        send = AsyncMock(side_effect=failure)
        with patch("mini_pi.memory.dashscope_embedding.post_json_async", send):
            with self.assertRaises(RuntimeError) as caught:
                await embedder.embed_query("HTTP失败的query原文")
        self.assertIs(caught.exception, failure)
        self.assertEqual(send.await_count, 1)
        self.assertEqual(len(embedder.request_records), 1)
        self.assertEqual(embedder.request_records[0]["status"], "error")


class DashScopeDocumentsTests(unittest.IsolatedAsyncioTestCase):

    def assert_requests(self, send, embedder, originals, expected_sizes):
        self.assertEqual(send.await_count, len(expected_sizes))
        start = 0
        for call, size in zip(send.await_args_list, expected_sizes, strict=True):
            self.assertEqual(call.args, (
                embedder.endpoint, SYNTHETIC_KEY,
                {"model": "text-embedding-v4", "input": {"texts": originals[start:start + size]},
                 "parameters": {"text_type": "document", "dimension": DIMENSIONS,
                                "output_type": "dense"}},
                30.0,
            ))
            self.assertEqual(call.kwargs, {})
            start += size

    def mock_success(self, originals):
        calls = []

        async def answer(url, key, payload, timeout):
            calls.append(payload)
            return native_reply(payload, originals, len(calls))

        return AsyncMock(side_effect=answer)

    async def test_empty_and_batch_boundaries(self):
        for count, sizes in ((0, []), (1, [1]), (10, [10]), (11, [10, 1])):
            with self.subTest(count=count):
                originals = original_texts(count)
                embedder = DashScopeEmbedder(SYNTHETIC_KEY)
                send = self.mock_success(originals)
                with patch("mini_pi.memory.dashscope_embedding.post_json_async", send):
                    result = await embedder.embed_documents(originals)
                self.assertEqual(result, tuple(unit_at(index) for index in range(count)))
                self.assert_requests(send, embedder, originals, sizes)
                self.assertEqual(len(embedder.request_records), len(sizes))
                if count == 0:
                    send.assert_not_called()

    async def test_invalid_11th_text_is_rejected_before_first_request(self):
        for invalid in (" \n\t", None, ["不是单条文本"]):
            with self.subTest(invalid=invalid):
                texts = original_texts(11)
                texts[10] = invalid
                embedder = DashScopeEmbedder(SYNTHETIC_KEY)
                send = AsyncMock()
                with patch("mini_pi.memory.dashscope_embedding.post_json_async", send):
                    with self.assertRaises(MemoryEmbeddingError):
                        await embedder.embed_documents(texts)
                send.assert_not_called()
                self.assertEqual(embedder.request_records, [])

    async def test_external_list_edit_during_first_await_does_not_change_later_batches(self):
        texts = original_texts(23)
        originals = texts.copy()
        entered = asyncio.Event()
        release = asyncio.Event()
        seen = []

        async def answer(url, key, payload, timeout):
            seen.append(payload)
            if len(seen) == 1:
                entered.set()
                await release.wait()
            return native_reply(payload, originals, len(seen))

        embedder = DashScopeEmbedder(SYNTHETIC_KEY)
        send = AsyncMock(side_effect=answer)
        with patch("mini_pi.memory.dashscope_embedding.post_json_async", send):
            task = asyncio.create_task(embedder.embed_documents(texts))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                texts[-1] = "外部在第一次HTTP等待期间替换的末尾原文"
                release.set()
                result = await asyncio.wait_for(task, 2)
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
        self.assert_requests(send, embedder, originals, [10, 10, 3])
        self.assertEqual(result, tuple(unit_at(index) for index in range(23)))
        self.assertEqual(texts[-1], "外部在第一次HTTP等待期间替换的末尾原文")

    async def test_second_batch_failure_propagates_without_partial_return_or_third_request(self):
        originals = original_texts(23)
        failure = RuntimeError("受控第二批HTTP 503")
        seen = []

        async def answer(url, key, payload, timeout):
            seen.append(payload)
            if len(seen) == 2:
                raise failure
            return native_reply(payload, originals, len(seen))

        embedder = DashScopeEmbedder(SYNTHETIC_KEY)
        send = AsyncMock(side_effect=answer)
        with patch("mini_pi.memory.dashscope_embedding.post_json_async", send):
            with self.assertRaises(RuntimeError) as caught:
                await embedder.embed_documents(originals)
        self.assertIs(caught.exception, failure)
        self.assert_requests(send, embedder, originals, [10, 10])
        records = embedder.request_records
        self.assertEqual([record["status"] for record in records], ["validated", "error"])
        self.assertEqual([record["text_count"] for record in records], [10, 10])
        self.assertEqual(records[0]["total_tokens"], 10)
        self.assertEqual(records[0]["request_id"], "synthetic-batch-1")
        self.assertIsNone(records[1]["total_tokens"])
        self.assertIsNone(records[1]["request_id"])


if __name__ == "__main__":
    unittest.main()
