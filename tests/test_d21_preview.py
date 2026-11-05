"""D21：离线预览必须确实走三组不同输入，未触发或遗漏目标时不能宣称检查通过。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evals.d21_preview import run_preview


class D21PreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_harness_prepares_three_inputs_without_replaying_or_editing(self):
        with TemporaryDirectory(prefix="d21-preview-") as directory:
            result = await run_preview(Path(directory) / "run")
            self.assertTrue(result["preview_checks_passed"], result["checks"])
            self.assertEqual(result["groups"]["C"]["cut_index"], 4)
            self.assertEqual(result["real_model_requests"], 0)
            self.assertIsNone(result["actual_usage"])
            self.assertFalse(result["task_evaluated"])
            self.assertFalse(result["summary_quality_verified"])
            for name in ("A", "B", "C"):
                self.assertEqual((Path(directory) / "run" / name / "workspace/edit-test.txt").read_bytes(), b"Hello, world!")

    async def test_no_summary_trigger_is_reported_as_missing_policy_coverage(self):
        with TemporaryDirectory(prefix="d21-preview-no-summary-") as directory:
            output = Path(directory) / "run"
            result = await run_preview(output, trigger=4000)
            self.assertFalse(result["preview_checks_passed"])
            self.assertFalse(result["checks"]["C_triggered_after_read_shortening"])
            self.assertEqual(result["groups"]["C"]["scripted_summary_calls"], 0)
            self.assertIn("C未生成或保存摘要", (output / "input-review.md").read_text(encoding="utf-8"))

    async def test_scripted_summary_missing_goal_is_not_accepted(self):
        with TemporaryDirectory(prefix="d21-preview-bad-summary-") as directory:
            result = await run_preview(Path(directory) / "run", scripted_summary="读取过过程记录，接着工作。")
            self.assertEqual(result["groups"]["C"]["scripted_summary_calls"], 1)
            self.assertFalse(result["preview_checks_passed"])
            self.assertFalse(result["checks"]["C_scripted_summary_contains_goal"])
            self.assertTrue(result["checks"]["C_source_uses_raw_old_history"])


if __name__ == "__main__":
    unittest.main()
