"""助手准备：评测程序的离线门禁，不证明真实模型语义质量。"""

from contextlib import redirect_stdout
import copy
from io import StringIO
import json
import math
import unittest
from unittest.mock import AsyncMock, patch

from examples import memory_embedding_eval as evaluation
from mini_pi.memory.dashscope_embedding import DashScopeEmbedder
from mini_pi.memory.errors import MemoryEmbeddingError


class MemoryEmbeddingEvalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manifest = evaluation.load_manifest()

    def network(self, *, calibration_failure=False, heldout_failure=False):
        calls = []

        async def reply(url, key, payload, timeout):
            case = self.manifest["cases"][len(calls) // 2]
            expected_mode = "query" if len(calls) % 2 == 0 else "document"
            self.assertEqual(set(payload), {"model", "input", "parameters"})
            self.assertEqual(set(payload["parameters"]), {"text_type", "dimension", "output_type"})
            self.assertEqual(payload["parameters"]["text_type"], expected_mode)
            self.assertEqual(set(payload["input"]), {"texts"})
            texts = payload["input"]["texts"]
            if expected_mode == "query":
                self.assertEqual(texts, [case["query"]], "标准答案与分组不能拼入问题")
                vectors = [[1.0, 0.0] + [0.0] * 1022]
            else:
                by_text = {item["text"]: item["id"] for item in case["memories"]}
                self.assertCountEqual(texts, by_text.keys(), "只发送记忆原文")
                vectors = []
                for text in texts:
                    identifier = by_text[text]
                    score = 0.9 if identifier in case["expected_ids"] else 0.2
                    if calibration_failure and case["id"] == "C1":
                        score = 0.2 if identifier in case["expected_ids"] else 0.95
                    if heldout_failure and case["id"] == "H1" and identifier not in case["expected_ids"]:
                        score = 0.95
                    vectors.append([score, math.sqrt(1 - score * score)] + [0.0] * 1022)
            calls.append(copy.deepcopy(payload))
            return {
                "request_id": "synthetic-eval-" + str(len(calls)),
                "usage": {"total_tokens": len(texts)},
                "output": {"embeddings": [
                    {"text_index": index, "embedding": vector}
                    for index, vector in reversed(list(enumerate(vectors)))
                ]},
            }

        return AsyncMock(side_effect=reply), calls

    def test_default_preview_does_not_load_credentials_or_start_evaluation(self):
        stream = StringIO()
        run = AsyncMock(side_effect=AssertionError("默认预览不能运行评测"))
        with (
            patch.object(evaluation._EvalEmbedder, "from_env", side_effect=AssertionError("不能读取密钥")) as loader,
            patch.object(evaluation, "run_eval", run),
            patch("mini_pi.memory.dashscope_embedding.post_json_async", side_effect=AssertionError("不能联网")) as network,
            redirect_stdout(stream),
        ):
            self.assertEqual(evaluation.main([]), 0)
        plan = json.loads(stream.getvalue())
        self.assertEqual(plan["max_http_requests"], 12)
        loader.assert_not_called()
        run.assert_not_called()
        network.assert_not_called()

    async def test_full_offline_pipeline_locks_threshold_before_heldout_and_has_no_gold_in_payload(self):
        network, calls = self.network()
        embedder = evaluation._EvalEmbedder("synthetic-eval-key")
        with patch("mini_pi.memory.dashscope_embedding.post_json_async", network):
            result = await evaluation.run_eval(embedder, self.manifest)
        self.assertEqual(result["status"], "passed")
        self.assertIs(result["semantic_acceptance"], True)
        self.assertIs(result["pilot_only"], True)
        self.assertGreater(result["threshold"], 0.2)
        self.assertLessEqual(result["threshold"], 0.9)
        self.assertEqual(len(result["calibration"]), 3)
        self.assertEqual(len(result["heldout"]), 3)
        self.assertEqual(len(calls), 12)
        self.assertEqual(len(result["requests"]), 12)

    async def test_calibration_failure_stops_before_any_heldout_request(self):
        network, calls = self.network(calibration_failure=True)
        embedder = evaluation._EvalEmbedder("synthetic-eval-key")
        with patch("mini_pi.memory.dashscope_embedding.post_json_async", network):
            result = await evaluation.run_eval(embedder, self.manifest)
        self.assertEqual(result["status"], "calibration_failed")
        self.assertIs(result["semantic_acceptance"], False)
        self.assertIsNone(result["threshold"])
        self.assertEqual(result["heldout"], [])
        self.assertEqual(len(calls), 6)
        self.assertEqual(len(result["requests"]), 6)

    async def test_heldout_failure_does_not_recalibrate_or_repeat_requests(self):
        normal_network, _ = self.network()
        with patch("mini_pi.memory.dashscope_embedding.post_json_async", normal_network):
            baseline = await evaluation.run_eval(evaluation._EvalEmbedder("synthetic-eval-key"), self.manifest)
        network, calls = self.network(heldout_failure=True)
        with patch("mini_pi.memory.dashscope_embedding.post_json_async", network):
            result = await evaluation.run_eval(evaluation._EvalEmbedder("synthetic-eval-key"), self.manifest)
        self.assertEqual(result["status"], "heldout_failed")
        self.assertIs(result["semantic_acceptance"], False)
        self.assertEqual(result["threshold"], baseline["threshold"], "独立验收分数不能反向影响阈值")
        self.assertEqual(len(calls), 12)
        self.assertEqual(len(result["heldout"]), 3)

    async def test_budget_stops_before_creating_the_thirteenth_request(self):
        embedder = evaluation._EvalEmbedder("synthetic-eval-key")
        vector = (1.0,) + (0.0,) * 1023
        send = AsyncMock(return_value=(vector,))
        with patch.object(DashScopeEmbedder, "_send_batch", send):
            for index in range(12):
                self.assertEqual(await embedder.embed_query("合成问题" + str(index)), vector)
            with self.assertRaises(MemoryEmbeddingError):
                await embedder.embed_query("第十三次不得发送")
        self.assertEqual(send.await_count, 12)
        self.assertEqual(embedder.request_records, [])

    async def test_http_error_stops_as_technical_failure_instead_of_unknown_or_semantic_success(self):
        query_response = {
            "request_id": "synthetic-eval-query", "usage": {"total_tokens": 1},
            "output": {"embeddings": [
                {"text_index": 0, "embedding": [1.0] + [0.0] * 1023},
            ]},
        }
        send = AsyncMock(side_effect=[query_response, RuntimeError("模型请求失败：HTTP 503")])
        with patch("mini_pi.memory.dashscope_embedding.post_json_async", send):
            result = await evaluation.run_eval(evaluation._EvalEmbedder("synthetic-eval-key"), self.manifest)
        self.assertEqual(result["status"], "technical_error")
        self.assertEqual(result["http_status"], 503)
        self.assertIs(result["semantic_acceptance"], False)
        self.assertEqual(result["calibration"], [])
        self.assertEqual(result["heldout"], [])
        self.assertEqual(send.await_count, 2)
        self.assertEqual([item["status"] for item in result["requests"]], ["validated", "error"])


if __name__ == "__main__":
    unittest.main()
