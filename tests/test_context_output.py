"""D16首段：请求读取片段可缩短，原结果与执行状态必须保留。"""

from copy import deepcopy
import json
import unittest

from mini_pi.context_output import shorten_read_result
from mini_pi.models import ToolResult


class ShortenReadResultTests(unittest.TestCase):
    def test_long_read_keeps_prefix_notice_reference_and_original(self):
        original = ToolResult("read-unique-17", "read_file", "def calculate():\n" + "正文" * 1000)
        before = deepcopy(original)
        shortened = shorten_read_result(original, 120)

        self.assertIsNot(shortened, original)
        self.assertEqual(original, before)
        self.assertEqual(len(shortened.output), 120)
        self.assertTrue(shortened.output.startswith("def calculate():\n"))
        self.assertIn("省略", shortened.output)
        self.assertIn("原始会话记录", shortened.output)
        self.assertIn(original.tool_call_id, shortened.output)
        self.assertEqual(shortened.tool_call_id, original.tool_call_id)
        self.assertEqual(shortened.tool_name, original.tool_name)
        self.assertIsNone(shortened.error)
        shortened.output = "仅修改返回对象"
        self.assertEqual(original, before)

    def test_empty_short_and_exact_boundary_are_independent_unchanged_copies(self):
        for content, limit in (("", 1), ("短文", 30), ("边界正文", 4)):
            with self.subTest(content=content, limit=limit):
                original = ToolResult("read-short", "read_file", content)
                copied = shorten_read_result(original, limit)
                self.assertEqual(copied, original)
                self.assertIsNot(copied, original)
                copied.error = "仅修改返回对象"
                self.assertIsNone(original.error)

    def test_unicode_budget_counts_characters_and_keeps_json_serializable(self):
        original = ToolResult("中文调用", "read_file", "汉字🙂\n" * 100)
        shortened = shorten_read_result(original, 80)
        self.assertEqual(len(shortened.output), 80)
        self.assertTrue(shortened.output.startswith("汉字🙂\n"))
        self.assertEqual(json.loads(json.dumps(shortened.output, ensure_ascii=False)), shortened.output)
        self.assertEqual(original.output, "汉字🙂\n" * 100)

    def test_read_errors_including_empty_error_are_never_shortened(self):
        for error in ("读取失败", ""):
            with self.subTest(error=error):
                original = ToolResult("failed-read", "read_file", "诊断" * 100, error)
                before = deepcopy(original)
                copied = shorten_read_result(original, 1)
                self.assertEqual(copied, before)
                self.assertIsNot(copied, original)
                self.assertEqual(original, before)

    def test_other_tools_keep_structured_failure_and_edit_evidence(self):
        failed_tests = json.dumps({"outcome": "failed", "exit_code": 1,
                                  "output": "FAILED\n" * 100}, ensure_ascii=False)
        for name, output in (("run_tests", failed_tests), ("edit_file", "-old\n+new\n" * 100),
                             ("list_files", "file.py\n" * 100), ("unknown_tool", "x" * 100)):
            with self.subTest(tool=name):
                original = ToolResult("other-call", name, output)
                copied = shorten_read_result(original, 1)
                self.assertEqual(copied, original)
                self.assertIsNot(copied, original)

    def test_invalid_limits_fail_without_mutating_input_even_for_other_tools(self):
        for tool in ("read_file", "run_tests"):
            for limit in (0, -1, True, False, 2.5, "100", None):
                with self.subTest(tool=tool, limit=limit):
                    original = ToolResult("invalid-limit", tool, "原始输出")
                    before = deepcopy(original)
                    with self.assertRaises(ValueError):
                        shorten_read_result(original, limit)
                    self.assertEqual(original, before)

    def test_notice_must_fit_and_cannot_silently_drop_provenance(self):
        for call_id, limit in (("read-long", 1), ("x" * 300, 120)):
            with self.subTest(call_id_length=len(call_id), limit=limit):
                original = ToolResult(call_id, "read_file", "原文" * 1000)
                before = deepcopy(original)
                with self.assertRaises(ValueError):
                    shorten_read_result(original, limit)
                self.assertEqual(original, before)


if __name__ == "__main__":
    unittest.main()
