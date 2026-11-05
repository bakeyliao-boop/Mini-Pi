"""D21：完整离线演练使用真实工具；运行终态、任务判定及脚本来源必须分开。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evals.d21_dry_run import run_dry_run


class D21DryRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_real_edits_and_independent_validation_pass(self):
        with TemporaryDirectory(prefix="d21-full-task-") as directory:
            report = await run_dry_run(Path(directory) / "run")
            self.assertTrue(report["dry_run_checks_passed"], {name: item["error"] for name, item in report["groups"].items()})
            for name, item in report["groups"].items():
                self.assertEqual(item["actual_content"], "Hello, testing!")
                self.assertEqual(item["case_verdict"], "passed")
                self.assertEqual(item["executed_call_ids"], ["d21-read-target", "d21-edit-target"])
                self.assertEqual(item["compaction_records"], 1 if name == "C" else 0)
                self.assertIsNone(item["run_task_passed"])
            self.assertIsNone(report["actual_usage"])
            self.assertFalse(report["effectiveness_verified"])
            self.assertEqual(report["real_model_requests"], 0)
            control = report["claim_only_control"]
            self.assertEqual(control["run_status"], "finished")
            self.assertEqual(control["actual_content"], "Hello, world!")
            self.assertEqual(control["case_verdict"], "failed")

    async def test_budget_stop_is_not_hidden_even_when_file_was_edited(self):
        with TemporaryDirectory(prefix="d21-task-budget-") as directory:
            report = await run_dry_run(Path(directory) / "run", max_answer_turns=2)
            self.assertFalse(report["dry_run_checks_passed"])
            for item in report["groups"].values():
                self.assertEqual(item["run_status"], "budget_exhausted")
                self.assertFalse(item["pipeline_checks"]["run_finished"])
                self.assertEqual(item["actual_content"], "Hello, testing!")
                self.assertEqual(item["case_verdict"], "passed")


if __name__ == "__main__":
    unittest.main()
