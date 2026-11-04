"""D20：多处匹配必须报正确次数；拒绝和文件不变不能代替完整原判定。"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evals.pi_edit_replace import judge_multiple_matches, load_case, run_edit_multiple_matches
from mini_pi.models import ToolResult


class MultipleMatchesJudgeTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case("pi_edit_multiple_matches")
        self.message = "旧文本匹配多处（共3处），请提供更多上下文"

    def judge(self, error, *, content="foo foo foo", output=""):
        return judge_multiple_matches(ToolResult(self.case["tool_call_id"], "edit_file", output, error=error), content)

    def test_original_input_and_expected_count_are_preserved(self):
        source = (Path(__file__).resolve().parents[1] / "evals/upstream/pi/edit-multiple-matches.excerpt.ts").read_text(encoding="utf-8")
        self.assertIn('originalContent = "foo foo foo"', source)
        self.assertIn('oldText: "foo", newText: "bar"', source)
        self.assertIn('rejects.toThrow(/Found 3 occurrences/)', source)
        self.assertEqual((self.case["initial_content"], self.case["old_text"], self.case["new_text"]),
                         ("foo foo foo", "foo", "bar"))
        self.assertEqual(self.case["expected_occurrences"], 3)
        self.assertFalse(self.case["adaptation"]["native_pi_assertions_executed"])

    def test_complete_error_with_correct_count_and_unchanged_file_passes(self):
        result = self.judge(self.message)
        self.assertEqual(result["case_verdict"], "passed")
        self.assertEqual(result["checks"]["occurrence_count_matches"]["actual"], 3)

    def test_ambiguous_error_without_count_does_not_pass(self):
        result = self.judge("旧文本匹配多处，请提供更多上下文")
        self.assertEqual(result["checks"]["error_reason_matches"]["status"], "passed")
        self.assertEqual(result["checks"]["occurrence_count_matches"]["status"], "failed")
        self.assertEqual(result["case_verdict"], "failed")

    def test_wrong_count_and_unrelated_error_do_not_pass(self):
        for message in ("旧文本匹配多处（共2处）", "旧文本匹配多处（共13处）", "旧文本未找到（共3处）"):
            with self.subTest(message=message):
                self.assertEqual(self.judge(message)["case_verdict"], "failed")

    def test_correct_error_cannot_hide_replacement_of_one_or_all_matches(self):
        for content in ("bar foo foo", "bar bar bar"):
            with self.subTest(content=content):
                self.assertEqual(self.judge(self.message, content=content)["checks"]["disk_file_unchanged"]["status"], "failed")

    def test_success_output_cannot_substitute_for_a_tool_error(self):
        self.assertEqual(self.judge(None, output=self.message)["case_verdict"], "failed")


class MultipleMatchesToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_tool_reports_three_matches_without_editing(self):
        with TemporaryDirectory(prefix="d20-multiple-matches-") as directory:
            output = Path(directory) / "run"
            report = await run_edit_multiple_matches(output)
            self.assertEqual(report["before"], "foo foo foo")
            self.assertEqual(report["after"], report["before"])
            self.assertEqual(report["tool_outcome"], "error")
            self.assertEqual(report["model_requests"], 0)
            self.assertEqual((output / "workspace/edit-test.txt").read_bytes(), b"foo foo foo")
            self.assertFalse((output / "patch-validation").exists())
            self.assertEqual(json.loads((output / "result.json").read_text(encoding="utf-8")), report)
            self.assertEqual(report["case_verdict"], "passed", report["checks"])


if __name__ == "__main__":
    unittest.main()
