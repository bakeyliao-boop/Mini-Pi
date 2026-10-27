"""固定提取试点评测辅助的离线门禁：全合成凭据，禁止真实网络和数据库。"""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from examples import memory_extraction_eval as evaluation
from mini_pi.memory.models import MemoryScope, MemorySource


SYNTHETIC_KEY = "synthetic-eval-secret-never-use-live"


def response(*, finish="stop", content="[]", usage=True):
    result = {"model": evaluation.MODEL, "choices": [{
        "finish_reason": finish, "message": {"role": "assistant", "content": content},
    }]}
    if usage:
        result["usage"] = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    return result


class ExtractionEvaluationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.data = evaluation.load_dataset()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.post = self.enterContext(patch(
            "mini_pi.qwen_client.post_json_async", new_callable=AsyncMock, return_value=response(),
        ))
        self.database = self.enterContext(patch(
            "sqlite3.connect", side_effect=AssertionError("评测提取不得开库"),
        ))
        self.configuration = self.enterContext(patch(
            "examples.memory_extraction_eval.read_live_configuration",
            side_effect=AssertionError("离线专项不得读取配置凭据"),
        ))

    def extractor(self, path):
        return evaluation.RecordedExtractor(
            api_key=SYNTHETIC_KEY, model=evaluation.MODEL, base_url=evaluation.BASE_URL,
            max_requests=evaluation.MAX_REQUESTS, max_completion_tokens=evaluation.OUTPUT_TOKENS,
            timeout=30.0, evidence_dir=path,
        )

    def test_default_main_only_previews_without_credentials_network_or_database(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(evaluation.main([]), 0)
        preview = json.loads(output.getvalue())
        self.assertEqual((preview["mode"], preview["real_model_calls"]), ("preview", 0))
        self.assertEqual(len(preview["requests"]), 6)
        self.assertIsNone(preview["semantic_acceptance"])
        self.configuration.assert_not_called()
        self.post.assert_not_called()
        self.database.assert_not_called()

    def test_load_dataset_rejects_changed_authorized_plan(self):
        for field, invalid in (("model", "other-model"), ("max_requests", 7),
                               ("max_completion_tokens", 1537), ("automatic_retries", 1),
                               ("extra_judge_api_calls", 1), ("serial", False),
                               ("enable_thinking", True)):
            with self.subTest(field=field):
                changed = deepcopy(self.data)
                changed["run_config"][field] = invalid
                path = self.root / "changed.json"
                path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(ValueError):
                    evaluation.load_dataset(path)
        self.post.assert_not_called()

    async def test_six_serial_responses_keep_raw_evidence_exclude_gold_and_do_not_grade_semantics(self):
        data = deepcopy(self.data)
        data["cases"][0]["required_units"][0]["meaning"] = "SYNTHETIC-GOLD-NEVER-ON-WIRE"
        path = self.root / "six-cases"
        extractor = self.extractor(path)
        report = await evaluation.run_cases(data, extractor, path)
        self.assertEqual((self.post.await_count, extractor.request_count), (6, 6))
        self.assertEqual((report["status"], report["technical_pass_count"]), ("technical_complete", 6))
        self.assertEqual(report["not_executed"], [])
        self.assertIsNone(report["semantic_acceptance"])
        self.assertEqual(report["semantic_review"], "pending_review")
        self.assertTrue(all(case["semantic_review"] is None for case in report["cases"]))
        self.assertEqual(report["memory_database_writes"], 0)
        for index, call in enumerate(self.post.await_args_list):
            endpoint, key, payload, timeout = call.args
            self.assertEqual(endpoint, evaluation.BASE_URL + "/chat/completions")
            self.assertEqual((key, timeout), (SYNTHETIC_KEY, 30.0))
            self.assertEqual(payload["max_completion_tokens"], 1536)
            self.assertFalse(payload["enable_thinking"])
            self.assertFalse(payload["stream"])
            wire = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("SYNTHETIC-GOLD-NEVER-ON-WIRE", wire)
            self.assertNotIn("required_units", wire)
            self.assertNotIn("forbidden_inferences", wire)
            material = json.loads(payload["messages"][1]["content"])
            source = data["cases"][index]["source"]
            self.assertEqual(material, {field: source[field] for field in ("role", "recorded_at", "text")})
            event = json.loads((path / f"request-{index + 1:02d}.json").read_text(encoding="utf-8"))
            self.assertEqual(event["raw_response"], response())
        self.assertEqual(report["usage"]["total_tokens"], 90)
        self.assertAlmostEqual(report["usage"]["estimated_standard_price_cny"], 0.000129)
        scope = MemoryScope(**data["scope"])
        source = MemorySource(scope=scope, **data["cases"][0]["source"])
        with self.assertRaises(RuntimeError):
            await extractor.extract(scope, source)
        self.assertEqual((self.post.await_count, extractor.request_count, len(extractor.events)), (6, 6, 6))
        self.database.assert_not_called()

    async def test_first_truncated_or_invalid_json_response_stops_and_keeps_usage(self):
        for label, raw in (("truncated", response(finish="length")),
                           ("bad-json", response(content="[unfinished"))):
            with self.subTest(label=label):
                self.post.reset_mock()
                self.post.return_value = raw
                path = self.root / label
                extractor = self.extractor(path)
                report = await evaluation.run_cases(self.data, extractor, path)
                self.assertEqual(self.post.await_count, 1)
                self.assertEqual(report["model_requests"], 1)
                self.assertEqual(report["status"], "technical_stopped")
                self.assertEqual(report["technical_pass_count"], 0)
                self.assertEqual(report["cases"][0]["status"], "technical_error")
                self.assertEqual(report["not_executed"], [f"S{i}" for i in range(2, 7)])
                self.assertEqual(report["usage"]["total_tokens"], 15)
                self.assertIsNone(report["semantic_acceptance"])
                event = json.loads((path / "request-01.json").read_text(encoding="utf-8"))
                self.assertEqual(event["raw_response"], raw)

    async def test_all_saved_json_and_returned_report_redact_even_echoed_synthetic_secret(self):
        raw = response()
        raw["server_debug"] = {"echo": SYNTHETIC_KEY, SYNTHETIC_KEY: [SYNTHETIC_KEY]}
        self.post.return_value = raw
        path = self.root / "redacted"
        report = await evaluation.run_cases(self.data, self.extractor(path), path,
                                            config_summary={"debug": SYNTHETIC_KEY})
        self.assertNotIn(SYNTHETIC_KEY, json.dumps(report))
        for saved in path.iterdir():
            with self.subTest(file=saved.name):
                self.assertNotIn(SYNTHETIC_KEY, saved.read_text(encoding="utf-8"))
        event = json.loads((path / "request-01.json").read_text(encoding="utf-8"))
        self.assertEqual(event["raw_response"]["server_debug"]["echo"], "<redacted>")
        self.assertEqual(self.post.await_count, 6)

    async def test_existing_directory_rejects_before_network_and_missing_usage_stays_unknown(self):
        occupied = self.root / "already-exists"
        occupied.mkdir()
        with self.assertRaises(FileExistsError):
            await evaluation.run_cases(self.data, self.extractor(occupied), occupied)
        self.post.assert_not_called()
        self.post.return_value = response(usage=False)
        path = self.root / "usage-unknown"
        report = await evaluation.run_cases(self.data, self.extractor(path), path)
        self.assertEqual(self.post.await_count, 6)
        for field in ("prompt_tokens", "completion_tokens", "total_tokens",
                      "estimated_standard_price_cny", "billed_cost_cny"):
            self.assertIsNone(report["usage"][field])
        self.assertFalse(report["usage"]["usage_complete"])
        self.assertTrue(all(record["usage"] is None for record in report["requests"]))
        mixed = evaluation.usage_summary([{"usage": response()["usage"]}, {"usage": None}])
        self.assertIsNone(mixed["total_tokens"])
        self.assertIsNone(mixed["estimated_standard_price_cny"])


if __name__ == "__main__":
    unittest.main()
