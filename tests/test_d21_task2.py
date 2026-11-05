"""D21第二任务：验证关键值实际可见性、真实文件结果及错误摘要反例。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evals.d21_task2 import (
    MISSING_FACT_SUMMARY,
    WRONG_FACT_SUMMARY,
    load_task2,
    run_task2,
)


ROOT = Path(__file__).resolve().parents[1]
INITIAL = b"name=mini-pi\nchannel=preview\nretries=2\n"
EXPECTED = b"name=mini-pi\nchannel=qa-east-7\nretries=2\n"


class D21Task2Tests(unittest.IsolatedAsyncioTestCase):
    def test_approved_value_is_only_in_long_read_tail_not_user_prompts(self):
        case = load_task2()
        initial = ROOT / case["initial_directory"]
        notes = (initial / case["constructed_history"]["background_file"]).read_text(encoding="utf-8")
        self.assertEqual((initial / case["target_file"]).read_bytes(), INITIAL)
        self.assertEqual(case["expected_content"].encode("utf-8"), EXPECTED)
        self.assertEqual(notes.count("approved_channel=qa-east-7"), 1)
        self.assertGreater(notes.index("approved_channel=qa-east-7"), 4096)
        self.assertNotIn("qa-east-7", case["earlier_user_message"])
        self.assertNotIn("qa-east-7", case["continuation_prompt"])

    async def test_actual_inputs_edits_and_clipped_reread_match_preparation_contract(self):
        with TemporaryDirectory(prefix="d21-task2-") as directory:
            output = Path(directory) / "run"
            report = await run_task2(output)
            self.assertTrue(report["preparation_checks_passed"], report["checks"])
            self.assertEqual(report["real_model_requests"], 0)
            self.assertIsNone(report["actual_usage"])
            self.assertFalse(report["effectiveness_verified"])
            self.assertFalse(report["summary_quality_verified"])
            self.assertEqual(set(report["groups"]), {"A", "B", "C"})
            for name, group in report["groups"].items():
                self.assertEqual(group["mode"], "scripted_full_task")
                self.assertEqual(group["run_status"], "finished")
                self.assertLessEqual(group["answer_script_calls"], 4)
                self.assertEqual(group["compaction_records"], 1 if name == "C" else 0)
                for check in (
                    "history_matches_returned_result", "original_history_preserved",
                    "no_historical_call_replay", "new_calls_executed_and_results_paired",
                    "agent_idle",
                ):
                    self.assertTrue(group["pipeline_checks"][check], (name, check))
                actual = (Path(group["workspace"]) / "app.conf").read_bytes()
                self.assertEqual(actual, INITIAL if name == "B" else EXPECTED)
                self.assertEqual(group["case_verdict"], "failed" if name == "B" else "passed")

            a, b, c = (report["groups"][name] for name in ("A", "B", "C"))
            self.assertTrue(a["first_answer_has_approved_value"])
            self.assertFalse(b["first_answer_has_approved_value"])
            self.assertTrue(c["first_answer_has_approved_value"])
            self.assertTrue(c["summary_source_has_full_read"])
            self.assertTrue(c["summary_source_has_approved_value"])
            self.assertTrue(b["reread_still_missing_approved_value"])
            self.assertEqual([item["tool_name"] for item in b["tool_results"]], ["read_file", "read_file"])
            self.assertFalse(any(item["tool_name"] == "edit_file" for item in b["tool_results"]))
            self.assertTrue(all(item["error"] is None for item in b["tool_results"]))
            self.assertEqual(a["patch_chain"]["status"], "passed")
            self.assertEqual(c["patch_chain"]["status"], "passed")

    async def test_summary_missing_approved_value_cannot_pass_by_using_oracle_answer(self):
        with TemporaryDirectory(prefix="d21-task2-summary-missing-") as directory:
            report = await run_task2(Path(directory) / "run", scripted_summary=MISSING_FACT_SUMMARY)
            c = report["groups"]["C"]
            self.assertFalse(report["preparation_checks_passed"])
            self.assertTrue(c["pipeline_checks"]["agent_idle"])
            self.assertFalse(c["first_answer_has_approved_value"])
            self.assertTrue(c["summary_source_has_approved_value"])
            self.assertEqual(c["case_verdict"], "failed")
            self.assertEqual((Path(c["workspace"]) / "app.conf").read_bytes(), INITIAL)
            self.assertFalse(any(item["tool_name"] == "edit_file" for item in c["tool_results"]))
            self.assertEqual(report["real_model_requests"], 0)

    async def test_wrong_summary_value_is_really_written_and_independent_oracle_rejects_it(self):
        with TemporaryDirectory(prefix="d21-task2-summary-wrong-") as directory:
            report = await run_task2(Path(directory) / "run", scripted_summary=WRONG_FACT_SUMMARY)
            c = report["groups"]["C"]
            self.assertFalse(report["preparation_checks_passed"])
            self.assertEqual(c["run_status"], "finished")
            self.assertEqual(c["case_verdict"], "failed")
            self.assertEqual((Path(c["workspace"]) / "app.conf").read_bytes(),
                             b"name=mini-pi\nchannel=qa-west-9\nretries=2\n")
            successful_edits = [item for item in c["tool_results"]
                                if item["tool_name"] == "edit_file" and item["error"] is None]
            self.assertEqual(len(successful_edits), 1)
            self.assertEqual(c["patch_chain"]["status"], "passed")
            self.assertEqual(c["checks"]["disk_target_matches_expected"]["status"], "failed")
            self.assertEqual(c["checks"]["patch_chain_recreates_expected_and_actual"]["status"], "failed")
            self.assertEqual(report["real_model_requests"], 0)


if __name__ == "__main__":
    unittest.main()
