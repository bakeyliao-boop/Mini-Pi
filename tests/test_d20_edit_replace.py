"""D20：文件编辑原例的输入保留、真实修改及独立判定反例。"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from evals.pi_edit_replace import judge_edit_replace, load_case, rebuild_patch, run_edit_replace
from mini_pi.models import ToolResult
from mini_pi.tools.edit_diff import render_edit_diff


class EditReplaceJudgeTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="d20-edit-judge-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.case = load_case()

    def result(self, after=None):
        case = self.case
        output = render_edit_diff(case["filename"], case["initial_content"],
                                  after if after is not None else case["expected_content"])
        return ToolResult(case["tool_call_id"], "edit_file", output)

    def test_source_input_and_mapping_remain_explicit(self):
        original = (Path(__file__).resolve().parents[1] / "evals/upstream/pi/edit-replace.excerpt.ts").read_text(encoding="utf-8")
        self.assertIn('const originalContent = "Hello, world!"', original)
        self.assertIn('oldText: "world", newText: "testing"', original)
        self.assertEqual(self.case["initial_content"], "Hello, world!")
        self.assertEqual(self.case["expected_content"], "Hello, testing!")
        self.assertEqual(self.case["kind"], "tool_unit_port")
        self.assertFalse(self.case["adaptation"]["native_pi_assertions_executed"])

    def test_real_returned_patch_recreates_text_without_adding_newline(self):
        result = self.result()
        rebuilt = rebuild_patch(self.case["initial_content"], result.output, self.root / "oracle")
        self.assertEqual(rebuilt["status"], "passed")
        self.assertEqual(rebuilt["output"], "Hello, testing!")
        self.assertEqual([item["exit_code"] for item in rebuilt["attempts"]], [0, 0])
        self.assertEqual(judge_edit_replace(result, self.case["expected_content"], rebuilt)["case_verdict"], "passed")

    def test_success_text_alone_cannot_pass(self):
        result = ToolResult("test-call-5", "edit_file", "Successfully replaced")
        rebuilt = rebuild_patch(self.case["initial_content"], result.output, self.root / "oracle")
        verdict = judge_edit_replace(result, self.case["initial_content"], rebuilt)
        self.assertEqual(verdict["case_verdict"], "failed")
        self.assertEqual(verdict["checks"]["patch_recreates_expected"]["status"], "failed")

    def test_valid_patch_does_not_hide_unchanged_actual_disk_file(self):
        result = self.result()
        rebuilt = rebuild_patch(self.case["initial_content"], result.output, self.root / "oracle")
        verdict = judge_edit_replace(result, self.case["initial_content"], rebuilt)
        self.assertEqual(verdict["checks"]["patch_recreates_expected"]["status"], "passed")
        self.assertEqual(verdict["checks"]["disk_file_contains_expected"]["status"], "failed")
        self.assertEqual(verdict["case_verdict"], "failed")

    def test_patch_rebuilding_wrong_content_fails_even_if_actual_file_is_correct(self):
        result = self.result("Hello, wrong!")
        rebuilt = rebuild_patch(self.case["initial_content"], result.output, self.root / "oracle")
        self.assertEqual(rebuilt["status"], "passed")
        self.assertEqual(rebuilt["output"], "Hello, wrong!")
        verdict = judge_edit_replace(result, self.case["expected_content"], rebuilt)
        self.assertEqual(verdict["checks"]["patch_recreates_expected"]["status"], "failed")
        self.assertEqual(verdict["case_verdict"], "failed")

    def test_unexpected_patch_target_never_reaches_git(self):
        output = self.result().output.replace("a/edit-test.txt", "a/other.txt")
        with patch("evals.pi_edit_replace.subprocess.run") as git:
            result = rebuild_patch(self.case["initial_content"], output, self.root / "oracle")
        git.assert_not_called()
        self.assertEqual(result["status"], "failed")
        self.assertFalse((self.root / "oracle").exists())

    def test_missing_patch_checker_is_unverified_not_a_pass(self):
        result = self.result()
        with patch("evals.pi_edit_replace.subprocess.run", side_effect=FileNotFoundError("git unavailable")):
            rebuilt = rebuild_patch(self.case["initial_content"], result.output, self.root / "oracle")
        verdict = judge_edit_replace(result, self.case["expected_content"], rebuilt)
        self.assertEqual(verdict["case_verdict"], "unverified")


class EditReplaceLogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="d20-edit-logs-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.directory = self.root / "run"

    async def test_real_edit_and_independent_validation_are_both_logged(self):
        result = await run_edit_replace(self.directory)
        self.assertEqual(result["case_verdict"], "passed")
        self.assertEqual(result["after"], "Hello, testing!")
        self.assertEqual(result["reconstructed_from_patch"], "Hello, testing!")
        self.assertEqual(result["model_requests"], 0)
        self.assertEqual(result["tool_calls"], 1)
        self.assertFalse(result["native_pi_evaluation"])
        self.assertFalse((self.directory / "session.jsonl").exists())
        saved = json.loads((self.directory / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, result)
        self.assertEqual((self.directory / "workspace/edit-test.txt").read_bytes(), b"Hello, testing!")
        self.assertEqual((self.directory / "before.txt").read_bytes(), b"Hello, world!")
        self.assertEqual((self.directory / "after.txt").read_bytes(), b"Hello, testing!")

    async def test_existing_output_is_not_overwritten(self):
        self.directory.mkdir()
        marker = self.directory / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            await run_edit_replace(self.directory)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    async def test_tool_error_is_preserved_in_logs(self):
        error = ToolResult("test-call-5", "edit_file", "", error="test tool error")
        with patch("evals.pi_edit_replace.EditFileExecutor.execute", new_callable=AsyncMock,
                   return_value=error) as execute:
            result = await run_edit_replace(self.directory)
        execute.assert_awaited_once()
        self.assertEqual(result["case_verdict"], "failed")
        self.assertIn("test tool error", result["errors"])
        self.assertEqual(result["after"], "Hello, world!")
        self.assertTrue((self.directory / "tool_result.json").exists())


if __name__ == "__main__":
    unittest.main()
