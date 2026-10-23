"""助手准备：smoke默认预览、真实SQLite闭环和请求上限；不调用真实API。"""

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from examples import memory_embedding_smoke as smoke
from mini_pi.memory.dashscope_embedding import DashScopeEmbedder
from mini_pi.memory.errors import MemoryEmbeddingError
from mini_pi.memory.store import MemoryStore


SYNTHETIC_KEY = "synthetic-smoke-test-token"
DIMENSIONS = 1024


def unit_at(index):
    values = [0.0] * DIMENSIONS
    values[index] = 1.0
    return tuple(values)


def native_response(payload, plan, request_number):
    mode = payload["parameters"]["text_type"]
    texts = payload["input"]["texts"]
    by_text = {item["text"]: index for index, item in enumerate(plan["documents"])}
    vectors = [unit_at(0)] if mode == "query" else [unit_at(by_text[text]) for text in texts]
    return {
        "request_id": f"synthetic-smoke-request-{request_number}",
        "usage": {"total_tokens": len(texts)},
        "output": {"embeddings": [
            {"text_index": index, "embedding": values}
            for index, values in reversed(list(enumerate(vectors)))
        ]},
    }


class MemoryEmbeddingSmokeTests(unittest.IsolatedAsyncioTestCase):
    def test_default_cli_only_prints_preview_without_config_or_network(self):
        printed = StringIO()
        previous_environment = dict(os.environ)
        run = AsyncMock(side_effect=AssertionError("默认入口不能运行smoke"))
        network = AsyncMock(side_effect=AssertionError("默认入口不能联网"))
        with (
            patch.object(DashScopeEmbedder, "from_env", side_effect=AssertionError("不能加载配置")) as loader,
            patch.object(Path, "read_text", side_effect=AssertionError("不能读取配置文件")) as read,
            patch.object(smoke, "run_smoke", run),
            patch("mini_pi.memory.dashscope_embedding.post_json_async", network),
            redirect_stdout(printed),
        ):
            result = smoke.main([])
        self.assertEqual(result, 0)
        plan = json.loads(printed.getvalue())
        self.assertEqual(plan["mode"], "preview")
        self.assertEqual(plan["max_http_requests"], 2)
        self.assertEqual(plan["model"], "text-embedding-v4")
        self.assertEqual(plan["dimensions"], DIMENSIONS)
        self.assertEqual(plan["top_k"], 2)
        self.assertEqual(plan["min_score"], -1.0)
        self.assertIs(plan["semantic_acceptance"], False)
        self.assertIsInstance(plan["query"], str)
        self.assertTrue(plan["query"].strip())
        self.assertEqual(len(plan["documents"]), 2)
        self.assertTrue(all(item["key"] and item["text"] for item in plan["documents"]))
        loader.assert_not_called()
        read.assert_not_called()
        run.assert_not_called()
        network.assert_not_called()
        self.assertEqual(dict(os.environ), previous_environment)

    async def test_smoke_uses_real_sqlite_and_search_and_returns_complete_evidence(self):
        plan = smoke.preview_plan()
        embedder = DashScopeEmbedder(SYNTHETIC_KEY)
        remembered = []
        searches = []
        db_paths = []
        real_remember = MemoryStore.remember
        real_search = MemoryStore.search
        case = self

        def remember(store, scope, source, draft):
            case.assertEqual(draft.start, 0)
            case.assertEqual(draft.end, len(source.text))
            entry = real_remember(store, scope, source, draft)
            remembered.append(entry)
            return entry

        async def search(store, scope, query, **kwargs):
            case.assertEqual(len(remembered), 2)
            case.assertTrue(store._backend.path.is_file())
            db_paths.append(store._backend.path)
            for entry in remembered:
                case.assertEqual(store.get(scope, entry.memory_id), entry)
            case.assertEqual(query, plan["query"])
            case.assertIs(kwargs["embedder"], embedder)
            case.assertEqual(kwargs["top_k"], 2)
            case.assertEqual(kwargs["min_score"], -1.0)
            hits = await real_search(store, scope, query, **kwargs)
            searches.append(hits)
            return hits

        calls = []

        async def answer(url, key, payload, timeout):
            calls.append(payload)
            return native_response(payload, plan, len(calls))

        network = AsyncMock(side_effect=answer)
        with (
            patch.object(MemoryStore, "remember", remember),
            patch.object(MemoryStore, "search", search),
            patch("mini_pi.memory.dashscope_embedding.post_json_async", network),
        ):
            result = await smoke.run_smoke(embedder)
        self.assertEqual(network.await_count, 2)
        self.assertEqual([item["parameters"]["text_type"] for item in calls], ["query", "document"])
        self.assertEqual(calls[0]["input"], {"texts": [plan["query"]]})
        self.assertCountEqual(calls[1]["input"]["texts"], [item["text"] for item in plan["documents"]])
        self.assertEqual(len(searches), 1)
        self.assertEqual(len(searches[0]), 2)
        self.assertEqual(result["status"], "passed")
        self.assertIs(result["semantic_acceptance"], False)
        self.assertEqual(result["hits"], [
            {"key": hit.entry.draft.key, "text": hit.entry.text, "score": hit.score,
             "version": hit.entry.version, "source_id": hit.entry.source.source_id}
            for hit in searches[0]
        ])
        self.assertEqual([hit["score"] for hit in result["hits"]], [1.0, 0.0])
        self.assertCountEqual([hit["text"] for hit in result["hits"]],
                              [item["text"] for item in plan["documents"]])
        self.assertEqual(result["requests"], embedder.request_records)
        self.assertEqual([item["status"] for item in result["requests"]], ["validated"] * 2)
        self.assertIsInstance(result["elapsed_seconds"], float)
        self.assertGreaterEqual(result["elapsed_seconds"], 0)
        self.assertTrue(db_paths)
        self.assertTrue(all(not path.exists() for path in db_paths), "临时SQLite应在本次smoke后清理")
        self.assertNotIn(SYNTHETIC_KEY, json.dumps(result, ensure_ascii=False))

    async def test_second_request_failure_propagates_without_retry_or_partial_success(self):
        plan = smoke.preview_plan()
        embedder = DashScopeEmbedder(SYNTHETIC_KEY)
        failure = RuntimeError("受控smoke第二次HTTP失败")
        calls = []

        async def answer(url, key, payload, timeout):
            calls.append(payload)
            if len(calls) == 2:
                raise failure
            return native_response(payload, plan, len(calls))

        network = AsyncMock(side_effect=answer)
        with patch("mini_pi.memory.dashscope_embedding.post_json_async", network):
            with self.assertRaises(RuntimeError) as caught:
                await smoke.run_smoke(embedder)
        self.assertIs(caught.exception, failure)
        self.assertEqual(network.await_count, 2)
        self.assertEqual([item["parameters"]["text_type"] for item in calls], ["query", "document"])
        self.assertEqual([item["status"] for item in embedder.request_records], ["validated", "error"])
        self.assertEqual(embedder.request_records[0]["total_tokens"], 1)
        self.assertIsNone(embedder.request_records[1]["total_tokens"])

    async def test_live_adapter_cap_blocks_third_request_independently_of_records(self):
        embedder = smoke._SmokeEmbedder(SYNTHETIC_KEY)
        send = AsyncMock(return_value=(unit_at(0),))
        with patch.object(DashScopeEmbedder, "_send_batch", send):
            self.assertEqual(await embedder.embed_query("合成请求一"), unit_at(0))
            self.assertEqual(await embedder.embed_query("合成请求二"), unit_at(0))
            with self.assertRaises(MemoryEmbeddingError):
                await embedder.embed_query("合成请求三，不得发送")
        self.assertEqual(send.await_count, 2)
        self.assertEqual(embedder.request_records, [], "请求上限不能依赖已完成记录计数")


if __name__ == "__main__":
    unittest.main()
