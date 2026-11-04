"""D20：错误必须说明哪个文件不存在及 ENOENT；用原契约暴露当前诊断缺项。"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evals.pi_edit_replace import judge_missing_file, load_case, run_edit_missing_file
from mini_pi.models import ToolResult


class MissingFileJudgeTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case("pi_edit_missing_file")
        self.target = Path("missing.txt").resolve()
        self.message = f"目标文件不存在：{self.target}。错误码：ENOENT。"

    def judge(self, error, *, exists=False, output=""):
        return judge_missing_file(ToolResult(self.case["tool_call_id"], "edit_file", output, error=error),
                                  self.target, exists)

    def test_original_absence_precondition_and_diagnostics_are_preserved(self):
        source = (Path(__file__).resolve().parents[1] / "evals/upstream/pi/edit-missing-file.excerpt.ts").read_text(encoding="utf-8")
        self.assertIn('const missingFile = join(testDir, "missing.txt")', source)
        self.assertIn('oldText: "hello", newText: "world"', source)
        self.assertIn('Could not edit file: ${missingFile}. Error code: ENOENT.', source)
        self.assertIsNone(self.case["initial_content"])
        self.assertEqual((self.case["old_text"], self.case["new_text"]), ("hello", "world"))

    def test_complete_error_and_absent_target_pass(self):
        self.assertEqual(self.judge(self.message)["case_verdict"], "passed")

    def test_generic_error_does_not_pass(self):
        result = self.judge("目标文件不存在")
        self.assertEqual(result["checks"]["error_contains_target_path"]["status"], "failed")
        self.assertEqual(result["checks"]["error_code_matches"]["status"], "failed")

    def test_missing_path_or_wrong_code_does_not_pass(self):
        for message in ("目标文件不存在：ENOENT", f"目标文件不存在：{self.target}。错误码：EACCES。"):
            with self.subTest(message=message):
                self.assertEqual(self.judge(message)["case_verdict"], "failed")

    def test_correct_error_cannot_hide_file_creation(self):
        self.assertEqual(self.judge(self.message, exists=True)["checks"]["target_remains_absent"]["status"], "failed")

    def test_success_output_is_not_an_error(self):
        self.assertEqual(self.judge(None, output=self.message)["case_verdict"], "failed")


class MissingFileToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_tool_reports_the_original_diagnostic_requirements(self):
        with TemporaryDirectory(prefix="d20-missing-file-") as directory:
            output = Path(directory) / "run"
            report = await run_edit_missing_file(output)
            self.assertFalse(report["before_exists"])
            self.assertFalse(report["after_exists"])
            self.assertEqual(report["tool_outcome"], "error")
            self.assertEqual(report["model_requests"], 0)
            self.assertFalse((output / "before.txt").exists())
            self.assertFalse((output / "workspace/missing.txt").exists())
            self.assertEqual(json.loads((output / "result.json").read_text(encoding="utf-8")), report)
            self.assertEqual(report["case_verdict"], "passed", report["checks"])


if __name__ == "__main__":
    unittest.main()
