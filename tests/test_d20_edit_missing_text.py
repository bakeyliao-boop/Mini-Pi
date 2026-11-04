"""D20：预期找不到旧文字时，正确报错应通过，错误原因与误改文件不能通过。"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from evals.pi_edit_replace import judge_missing_text, load_case, run_edit_missing_text
from mini_pi.models import ToolResult


class MissingTextJudgeTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case("pi_edit_missing_text")

    def result(self, error, output=""):
        return ToolResult(self.case["tool_call_id"], "edit_file", output, error=error)

    def test_original_missing_text_input_and_error_mapping_are_preserved(self):
        source = (Path(__file__).resolve().parents[1] / "evals/upstream/pi/edit-missing-text.excerpt.ts").read_text(encoding="utf-8")
        self.assertIn('originalContent = "Hello, world!"', source)
        self.assertIn('oldText: "nonexistent", newText: "testing"', source)
        self.assertIn("rejects.toThrow(/Could not find the exact text/)", source)
        self.assertEqual(self.case["old_text"], "nonexistent")
        self.assertEqual(self.case["expected_content"], self.case["initial_content"])
        self.assertFalse(self.case["adaptation"]["native_pi_assertions_executed"])

    def test_expected_error_and_unchanged_file_pass(self):
        result = self.result(self.case["expected_error"])
        judgement = judge_missing_text(result, self.case["initial_content"])
        self.assertEqual(judgement["case_verdict"], "passed")
        self.assertTrue(all(item["status"] == "passed" for item in judgement["checks"].values()))

    def test_unexpected_success_does_not_pass(self):
        judgement = judge_missing_text(self.result(None), self.case["initial_content"])
        self.assertEqual(judgement["checks"]["tool_reports_error"]["status"], "failed")
        self.assertEqual(judgement["case_verdict"], "failed")

    def test_unrelated_error_is_not_accepted(self):
        judgement = judge_missing_text(self.result("文件权限不足"), self.case["initial_content"])
        self.assertEqual(judgement["checks"]["error_reason_matches"]["status"], "failed")
        self.assertEqual(judgement["case_verdict"], "failed")

    def test_correct_error_cannot_hide_changed_disk_content(self):
        judgement = judge_missing_text(self.result(self.case["expected_error"]), "Hello, testing!")
        self.assertEqual(judgement["checks"]["error_reason_matches"]["status"], "passed")
        self.assertEqual(judgement["checks"]["disk_file_unchanged"]["status"], "failed")
        self.assertEqual(judgement["case_verdict"], "failed")

    def test_error_phrase_in_success_output_does_not_count_as_an_error(self):
        judgement = judge_missing_text(self.result(None, self.case["expected_error"]), self.case["initial_content"])
        self.assertEqual(judgement["case_verdict"], "failed")


class MissingTextLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_tool_rejection_is_logged_as_an_expected_pass(self):
        with TemporaryDirectory(prefix="d20-missing-text-") as directory:
            target = Path(directory) / "run"
            with patch("evals.pi_edit_replace.rebuild_patch", side_effect=AssertionError("本题不需要补丁重建")) as rebuild:
                result = await run_edit_missing_text(target)
            rebuild.assert_not_called()
            self.assertEqual(result["run_status"], "finished")
            self.assertEqual(result["tool_outcome"], "error")
            self.assertEqual(result["expected_tool_outcome"], "error")
            self.assertEqual(result["case_verdict"], "passed")
            self.assertEqual(result["errors"], [load_case("pi_edit_missing_text")["expected_error"]])
            self.assertEqual(result["before"], result["after"])
            self.assertEqual(result["model_requests"], 0)
            self.assertEqual(result["tool_calls"], 1)
            self.assertFalse((target / "session.jsonl").exists())
            self.assertFalse((target / "patch-validation").exists())
            self.assertEqual((target / "workspace/edit-test.txt").read_bytes(), b"Hello, world!")
            self.assertEqual(json.loads((target / "result.json").read_text(encoding="utf-8")), result)
            self.assertEqual(json.loads((target / "patch-check.json").read_text(encoding="utf-8"))["status"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
