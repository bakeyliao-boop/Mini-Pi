"""D21独立验收：实际文件与完整补丁链都必须正确，不能用模型声称成功替代。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from evals.d21_acceptance import ROOT, judge_workspace, rebuild_patch_chain
from mini_pi.models import ToolResult
from mini_pi.tools.edit_diff import render_edit_diff


class D21AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="d21-acceptance-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.case = json.loads((ROOT / "evals/cases/d21_edit_history.json").read_text(encoding="utf-8"))
        self.workspace = self.root / "workspace"
        shutil.copytree(ROOT / self.case["initial_directory"], self.workspace)

    def edit(self, before, after, call_id="edit", path="edit-test.txt"):
        return ToolResult(call_id, "edit_file", render_edit_diff(path, before, after))

    def write_target(self, text):
        (self.workspace / self.case["target_file"]).write_bytes(text.encode("utf-8"))

    def judge(self, results):
        return judge_workspace(self.workspace, self.case, results, self.root / "verification")

    def test_equivalent_whole_file_edit_passes(self):
        self.write_target("Hello, testing!")
        self.assertEqual(self.judge([self.edit("Hello, world!", "Hello, testing!")])["case_verdict"], "passed")

    def test_lf_patch_reconstruction_ignores_user_autocrlf_setting(self):
        before = "first\nsecond\nthird\n"
        after = "first\nREPLACED\nthird\n"
        config = self.root / "gitconfig"
        config.write_text("[core]\n\tautocrlf = true\n", encoding="utf-8")
        verification = self.root / "lf-verification"
        result = self.edit(before, after, path="edit-test.txt")
        with patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(config), "GIT_CONFIG_NOSYSTEM": "1"}):
            report = rebuild_patch_chain(before.encode("utf-8"), "edit-test.txt", [result], verification)
        self.assertEqual(report["status"], "passed", report)
        self.assertEqual(report["output"], after)
        self.assertEqual((verification / "edit-test.txt").read_bytes(), after.encode("utf-8"))

    def test_all_successful_edits_are_applied_in_order(self):
        self.write_target("Hello, testing!")
        results = [self.edit("Hello, world!", "Hello, interim!", "one"),
                   ToolResult("retry", "edit_file", "", error="temporary rejection"),
                   self.edit("Hello, interim!", "Hello, testing!", "two")]
        report = self.judge(results)
        self.assertEqual(report["case_verdict"], "passed")
        self.assertEqual([row["tool_call_id"] for row in report["patch_chain"]["attempts"]], ["one"] * 3 + ["two"] * 3)

    def test_correct_disk_cannot_hide_incorrect_patch(self):
        self.write_target("Hello, testing!")
        self.assertEqual(self.judge([self.edit("Hello, world!", "Hello, wrong!")])["case_verdict"], "failed")

    def test_success_claim_and_unchanged_file_do_not_pass(self):
        self.assertEqual(self.judge([ToolResult("edit", "edit_file", "Successfully replaced")])["case_verdict"], "failed")

    def test_no_successful_edit_does_not_pass_even_if_target_is_correct(self):
        self.write_target("Hello, testing!")
        self.assertEqual(self.judge([])["case_verdict"], "failed")

    def test_added_newline_is_rejected_even_with_a_valid_matching_patch(self):
        self.write_target("Hello, testing!\n")
        report = self.judge([self.edit("Hello, world!", "Hello, testing!\n")])
        self.assertEqual(report["case_verdict"], "failed")
        self.assertEqual(report["checks"]["disk_target_matches_expected"]["status"], "failed")

    def test_modified_background_or_added_file_cannot_hide_behind_correct_target(self):
        self.write_target("Hello, testing!")
        (self.workspace / "process-notes.txt").write_bytes(b"changed")
        (self.workspace / "extra.txt").write_bytes(b"extra")
        report = self.judge([self.edit("Hello, world!", "Hello, testing!")])
        self.assertEqual(report["checks"]["file_set_unchanged"]["status"], "failed")
        self.assertEqual(report["checks"]["other_initial_files_unchanged"]["status"], "failed")
        self.assertEqual(report["case_verdict"], "failed")

    def test_missing_git_or_timeout_remains_unverified(self):
        self.write_target("Hello, testing!")
        result = self.edit("Hello, world!", "Hello, testing!")
        for error in (FileNotFoundError("git unavailable"), subprocess.TimeoutExpired("git", 5)):
            with self.subTest(error=type(error).__name__), TemporaryDirectory(prefix="d21-oracle-") as directory:
                with patch("evals.d21_acceptance.subprocess.run", side_effect=error):
                    report = judge_workspace(self.workspace, self.case, [result], Path(directory) / "check")
                self.assertEqual(report["case_verdict"], "unverified")

    def test_known_disk_failure_takes_precedence_over_missing_git(self):
        with patch("evals.d21_acceptance.subprocess.run", side_effect=FileNotFoundError("git unavailable")):
            report = self.judge([self.edit("Hello, world!", "Hello, testing!")])
        self.assertEqual(report["case_verdict"], "failed")

    def test_wrong_target_header_is_rejected_before_git(self):
        self.write_target("Hello, testing!")
        with patch("evals.d21_acceptance.subprocess.run") as git:
            report = self.judge([self.edit("Hello, world!", "Hello, testing!", path="other.txt")])
        git.assert_not_called()
        self.assertEqual(report["case_verdict"], "failed")

    def test_dot_relative_headers_use_native_git_path_stripping_without_changing_patch(self):
        self.write_target("Hello, testing!")
        for dots in (1, 2):
            result = self.edit("Hello, world!", "Hello, testing!", path="./" * dots + "edit-test.txt")
            with self.subTest(dots=dots), patch("evals.d21_acceptance.subprocess.run", wraps=subprocess.run) as git:
                report = judge_workspace(self.workspace, self.case, [result], self.root / f"verify-dot-{dots}")
            self.assertEqual(report["case_verdict"], "passed", report)
            self.assertEqual(report["patch_chain"]["output"], "Hello, testing!")
            self.assertEqual(git.call_count, 3)
            for call in git.call_args_list:
                self.assertEqual(call.kwargs["input"], result.output.encode("utf-8"))
                self.assertIn(f"-p{dots + 1}", call.args[0])
                self.assertNotIn("--unsafe-paths", call.args[0])

    def test_different_dot_prefix_depths_are_rejected_before_git(self):
        self.write_target("Hello, testing!")
        result = self.edit("Hello, world!", "Hello, testing!", path="./edit-test.txt")
        result.output = result.output.replace("+++ b/./edit-test.txt", "+++ b/edit-test.txt")
        with patch("evals.d21_acceptance.subprocess.run") as git:
            report = self.judge([result])
        git.assert_not_called()
        self.assertEqual(report["case_verdict"], "failed")

    def test_git_rejection_is_respected_without_changing_patch(self):
        self.write_target("Hello, testing!")
        result = self.edit("Hello, world!", "Hello, testing!")
        replies = [subprocess.CompletedProcess([], 0, b"1\t1\tedit-test.txt\n", b""),
                   subprocess.CompletedProcess([], 128, b"", b"patch cannot apply")]
        with patch("evals.d21_acceptance.subprocess.run", side_effect=replies) as git:
            report = self.judge([result])
        self.assertEqual(report["case_verdict"], "failed")
        self.assertEqual(git.call_count, 2)
        self.assertEqual(git.call_args.kwargs["input"], result.output.encode("utf-8"))
        self.assertNotIn("--unsafe-paths", git.call_args.args[0])
        self.assertEqual(report["patch_chain"]["reason"], "返回的补丁链不能依次应用")


if __name__ == "__main__":
    unittest.main()
