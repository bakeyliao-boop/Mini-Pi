"""D20汇总：历史观测须重判、缺证据不冒充通过、取消后不启动后续样例。"""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from examples.d20_checks import recheck_smoke, run_checks


def evidence_fixture():
    # 仅供判定器测试的合成记录；不是实际模型请求或真实用量证据。
    return {"case_id": "pi-smoke-capital", "mode": "live_bailian", "run_id": "synthetic-test-fixture",
            "run_status": "finished", "output": "Paris", "errors": [], "case_verdict": "passed",
            "expected_identity": {"provider": "bailian", "model": "test-model"},
            "observed_identity": {"provider": "bailian", "model": "test-model"}, "usage": {"total_tokens": 1}}


class HistoricalSmokeTests(unittest.TestCase):
    def recheck(self, data):
        with TemporaryDirectory(prefix="d20-smoke-evidence-") as directory:
            path = Path(directory) / "synthetic.json"
            original = json.dumps(data)
            path.write_text(original, encoding="utf-8")
            result = recheck_smoke(path)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            return result

    def test_output_is_rejudged_instead_of_trusting_old_passed_label(self):
        data = evidence_fixture()
        data["output"] = "London"
        self.assertEqual(self.recheck(data)["case_verdict"], "failed")

    def test_missing_usage_remains_unverified(self):
        data = evidence_fixture()
        data["usage"] = None
        self.assertEqual(self.recheck(data)["case_verdict"], "unverified")

    def test_offline_record_is_not_accepted_as_real_model_evidence(self):
        data = evidence_fixture()
        data["mode"] = "offline_scripted"
        self.assertEqual(self.recheck(data)["case_verdict"], "unverified")


class D20SuiteTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_real_evidence_keeps_suite_unverified_with_expected_controls(self):
        with TemporaryDirectory(prefix="d20-suite-") as directory:
            output = Path(directory) / "run"
            result = await run_checks(output)
            self.assertEqual(result["counts"], {"passed": 4, "failed": 0, "unverified": 1})
            self.assertEqual(result["suite_verdict"], "unverified")
            self.assertTrue(result["controls_as_expected"])
            self.assertEqual(result["new_real_model_requests"], 0)
            self.assertEqual(json.loads((output / "result.json").read_text(encoding="utf-8")), result)

    async def test_complete_synthetic_evidence_checks_aggregation_only(self):
        with TemporaryDirectory(prefix="d20-suite-") as directory:
            path = Path(directory) / "synthetic.json"
            path.write_text(json.dumps(evidence_fixture()), encoding="utf-8")
            result = await run_checks(Path(directory) / "run", path)
            self.assertEqual(result["counts"], {"passed": 5, "failed": 0, "unverified": 0})
            self.assertEqual(result["suite_verdict"], "passed")
            self.assertTrue(result["controls_as_expected"])
            self.assertEqual([item["actual_verdict"] for item in result["controls"]], ["unverified", "failed", "failed"])
            self.assertEqual(result["cases"][0]["source_run_id"], "synthetic-test-fixture")

    async def test_cancellation_is_logged_and_no_later_case_starts(self):
        with TemporaryDirectory(prefix="d20-suite-cancel-") as directory:
            output = Path(directory) / "run"
            with patch("examples.d20_checks.run_edit_replace", new=AsyncMock(side_effect=asyncio.CancelledError)), \
                 patch("examples.d20_checks.run_edit_missing_text", new=AsyncMock()) as later:
                result = await run_checks(output)
            later.assert_not_awaited()
            self.assertEqual(result["run_status"], "cancelled")
            self.assertEqual(result["suite_verdict"], "failed")
            self.assertEqual(result["controls"], [])
            self.assertTrue((output / "result.json").exists())


if __name__ == "__main__":
    unittest.main()
