"""D20：用模拟结果验证原判定的适配和实际日志落盘。"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from evals.pi_smoke import judge_smoke, load_case, run_live_smoke, run_offline_smoke, verdict_exit_code
from mini_pi.session_store import SessionStore


IDENTITY = {"provider": "bailian", "model": "qwen3.8-flash"}
SYNTHETIC_USAGE = {"total_tokens": 7}


class SmokeJudgeTests(unittest.TestCase):
    def test_case_retains_upstream_prompt_and_all_five_checks(self):
        case = load_case()
        source = Path("evals/upstream/pi/smoke.eval.ts").read_text(encoding="utf-8")
        self.assertIn('await run("' + case["prompt"] + '")', source)
        self.assertEqual(case["expected_output"], "Paris")
        self.assertEqual(case["tools"], [])
        self.assertEqual(len(case["original_checks"]), 5)

    def test_synthetic_complete_observation_can_pass_all_checks(self):
        report = judge_smoke("Paris", [], IDENTITY, IDENTITY, SYNTHETIC_USAGE)
        self.assertEqual(report["case_verdict"], "passed")
        self.assertTrue(all(item["status"] == "passed" for item in report["checks"].values()))
        self.assertEqual(verdict_exit_code(report), 0)

    def test_trim_is_allowed_but_extra_prose_and_wrong_answers_fail(self):
        for text in ("Paris", " Paris\n", "\ufeffParis\u00a0"):
            with self.subTest(output=text):
                self.assertEqual(judge_smoke(text, [], IDENTITY, IDENTITY, SYNTHETIC_USAGE)["case_verdict"], "passed")
        for text in ("London", "The capital is Paris.", "PARIS", "\u0085Paris"):
            with self.subTest(output=text):
                report = judge_smoke(text, [], IDENTITY, IDENTITY, SYNTHETIC_USAGE)
                self.assertEqual(report["checks"]["output_matches"]["status"], "failed")
                self.assertEqual(report["case_verdict"], "failed")

    def test_correct_answer_does_not_hide_errors_or_wrong_metadata(self):
        cases = [
            (["request failed"], IDENTITY, SYNTHETIC_USAGE, "no_errors"),
            ([], {**IDENTITY, "provider": "other"}, SYNTHETIC_USAGE, "provider_matches"),
            ([], {**IDENTITY, "model": "other"}, SYNTHETIC_USAGE, "model_matches"),
            ([], IDENTITY, {"total_tokens": 0}, "usage_positive"),
        ]
        for errors, observed, usage, failed_check in cases:
            with self.subTest(check=failed_check):
                report = judge_smoke("Paris", errors, IDENTITY, observed, usage)
                self.assertEqual(report["checks"][failed_check]["status"], "failed")
                self.assertEqual(report["case_verdict"], "failed")

    def test_missing_real_telemetry_remains_unverified_not_zero(self):
        report = judge_smoke("Paris", [], IDENTITY)
        self.assertEqual(report["case_verdict"], "unverified")
        for name in ("provider_matches", "model_matches", "usage_positive"):
            self.assertEqual(report["checks"][name]["status"], "unverified")
            self.assertIsNone(report["checks"][name]["actual"])
        self.assertEqual(verdict_exit_code(report), 2)


class SmokeLogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="d20-smoke-logs-")
        self.addCleanup(temp.cleanup)
        self.output_dir = Path(temp.name) / "run"

    def read_json(self, name):
        return json.loads((self.output_dir / name).read_text(encoding="utf-8"))

    async def test_scripted_paris_runs_harness_without_tools_and_records_unknown_telemetry(self):
        result = await run_offline_smoke(self.output_dir)
        self.assertEqual(result["run_status"], "finished")
        self.assertEqual(result["case_verdict"], "unverified")
        self.assertEqual(result["mode"], "offline_scripted")
        self.assertFalse(result["native_pi_evaluation"])
        self.assertIsNone(result["observed_identity"])
        self.assertIsNone(result["usage"])
        self.assertEqual(result, self.read_json("result.json"))
        requests = self.read_json("requests.json")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["tools"], [])
        self.assertEqual(requests[0]["history"][0]["content"], load_case()["prompt"])
        protocol = self.read_json("protocol.json")
        self.assertEqual(protocol["run_id"], result["run_id"])
        loaded = SessionStore(self.output_dir / "session.jsonl", result["run_id"]).load()
        self.assertEqual(loaded.history[-1].content, "Paris")
        self.assertEqual(loaded.records[-1]["data"]["status"], "finished")

    async def test_wrong_answer_finishes_but_case_fails_and_is_logged(self):
        result = await run_offline_smoke(self.output_dir, answer="London")
        self.assertEqual(result["run_status"], "finished")
        self.assertEqual(result["case_verdict"], "failed")
        self.assertEqual(self.read_json("result.json")["output"], "London")
        self.assertEqual(verdict_exit_code(result), 1)

    async def test_scripted_request_error_is_preserved_in_result_and_session(self):
        result = await run_offline_smoke(self.output_dir, simulated_error="offline request failed")
        self.assertEqual(result["run_status"], "exception")
        self.assertEqual(result["case_verdict"], "failed")
        self.assertIn("offline request failed", result["errors"])
        self.assertEqual(result["exception"]["type"], "RuntimeError")
        self.assertEqual(self.read_json("result.json"), result)
        loaded = SessionStore(self.output_dir / "session.jsonl", result["run_id"]).load()
        self.assertFalse(result["session_has_run_end"])
        self.assertFalse(any(record["type"] == "run_end" for record in loaded.records))

    async def test_existing_run_directory_is_not_overwritten(self):
        self.output_dir.mkdir()
        marker = self.output_dir / "existing.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            await run_offline_smoke(self.output_dir)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        self.assertEqual(list(self.output_dir.iterdir()), [marker])

    async def test_caller_cancellation_waits_for_cleanup_and_writes_result(self):
        entered, cleaned = asyncio.Event(), asyncio.Event()

        class WaitingProvider:
            def __init__(self, responses):
                self.requests = []
                self.tool_requests = []

            async def generate(self, history, tools):
                self.requests.append(deepcopy(list(history)))
                self.tool_requests.append(deepcopy(list(tools)))
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaned.set()

        with patch("evals.pi_smoke.MockProvider", WaitingProvider):
            task = asyncio.create_task(run_offline_smoke(self.output_dir))
            try:
                async with asyncio.timeout(2):
                    await entered.wait()
                    task.cancel()
                    result = await task
            finally:
                if not task.done():
                    task.cancel()
                    await task
        self.assertTrue(cleaned.is_set())
        self.assertEqual(result["run_status"], "cancelled")
        self.assertEqual(result["case_verdict"], "failed")
        self.assertTrue(result["session_has_run_end"])
        self.assertEqual(self.read_json("result.json"), result)


class SmokeLiveAdapterTests(unittest.IsolatedAsyncioTestCase):
    """这里只模拟 HTTP 返回；真正请求另由显式 CLI 运行并单独记日志。"""

    def setUp(self):
        temp = TemporaryDirectory(prefix="d20-live-adapter-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.output_dir = self.root / "run"

    def response(self, usage=None):
        return {
            "model": "qwen3.8-flash",
            "choices": [{"message": {"role": "assistant", "content": "Paris"}, "finish_reason": "stop"}],
            "usage": usage,
        }

    async def test_bailian_call_is_limited_to_one_and_uses_recorded_usage_without_logging_key(self):
        key = "sk-offline-only-test-key"
        auth_file = self.root / "auth.json"
        auth_file.write_text(json.dumps({"bailian": {"type": "api_key", "key": key}}), encoding="utf-8")
        usage = {"prompt_tokens": 12, "completion_tokens": 1, "total_tokens": 13}
        with patch("mini_pi.qwen_client.post_json_async", new_callable=AsyncMock,
                   return_value=self.response(usage)) as post:
            result = await run_live_smoke(self.output_dir, auth_file=auth_file)
        post.assert_awaited_once()
        self.assertEqual(result["mode"], "live_bailian")
        self.assertEqual(result["run_status"], "finished")
        self.assertEqual(result["case_verdict"], "passed")
        self.assertEqual(result["usage"], usage)
        self.assertEqual(result["observed_identity"], IDENTITY)
        self.assertEqual(result["returned_model"], "qwen3.8-flash")
        self.assertEqual(result["model_requests"], 1)
        calls = json.loads((self.output_dir / "requests.json").read_text(encoding="utf-8"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["request_body"]["model"], "qwen3.8-flash")
        self.assertFalse(calls[0]["request_body"].get("tools"))
        for path in self.output_dir.iterdir():
            self.assertNotIn(key, path.read_text(encoding="utf-8"))

    async def test_missing_service_usage_is_still_unverified(self):
        with patch("mini_pi.qwen_client.post_json_async", new_callable=AsyncMock,
                   return_value=self.response()) as post:
            result = await run_live_smoke(self.output_dir, api_key="offline-test-key")
        post.assert_awaited_once()
        self.assertIsNone(result["usage"])
        self.assertEqual(result["case_verdict"], "unverified")
        self.assertEqual(result["checks"]["usage_positive"]["status"], "unverified")

    async def test_transport_failure_is_logged_without_retry(self):
        with patch("mini_pi.qwen_client.post_json_async", new_callable=AsyncMock,
                   side_effect=OSError("test transport failure")) as post:
            result = await run_live_smoke(self.output_dir, api_key="offline-test-key")
        post.assert_awaited_once()
        self.assertEqual(result["case_verdict"], "failed")
        self.assertEqual(result["model_requests"], 1)
        self.assertIn("test transport failure", result["errors"])
        self.assertIsNone(result["usage"])

    async def test_configuration_error_is_logged_without_request(self):
        with patch("mini_pi.qwen_client.post_json_async", new_callable=AsyncMock) as post:
            result = await run_live_smoke(self.output_dir, api_key="")
        post.assert_not_awaited()
        self.assertEqual(result["exception"]["stage"], "provider_configuration")
        self.assertEqual(result["model_requests"], 0)
        self.assertEqual(result["case_verdict"], "failed")
        self.assertEqual(json.loads((self.output_dir / "requests.json").read_text(encoding="utf-8")), [])

    async def test_auth_file_error_is_logged_before_any_request(self):
        with patch("mini_pi.qwen_client.post_json_async", new_callable=AsyncMock) as post:
            result = await run_live_smoke(self.output_dir, auth_file=self.root / "missing-auth.json")
        post.assert_not_awaited()
        self.assertEqual(result["exception"]["stage"], "provider_configuration")
        self.assertEqual(result["case_verdict"], "failed")
        self.assertTrue((self.output_dir / "result.json").exists())


if __name__ == "__main__":
    unittest.main()
