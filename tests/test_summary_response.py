"""D17：摘要候选结果的离线门禁。"""

import unittest

from mini_pi.compaction import SummaryAborted, SummaryError, check_summary_response
from mini_pi.models import Message, ToolCall


class SummaryResponseTests(unittest.TestCase):
    def test_normal_response_keeps_original_text(self):
        text = "  目标：修复登录；测试失败，待排查。\n"
        self.assertEqual(check_summary_response(Message("assistant", text, stop_reason="stop")), text)

    def test_error_length_unknown_empty_and_tool_calls_are_rejected(self):
        cases = [
            None,
            Message("assistant", "部分摘要", stop_reason="length"),
            Message("assistant", "错误", stop_reason="error"),
            Message("assistant", "未知", stop_reason=None),
            Message("assistant", "未知", stop_reason="unexpected"),
            Message("assistant", " \n ", stop_reason="stop"),
            Message("user", "不是助手", stop_reason="stop"),
            Message("assistant", "调用", [ToolCall("a", "read", {})], stop_reason="stop"),
        ]
        for response in cases:
            with self.subTest(response=response), self.assertRaises(SummaryError):
                check_summary_response(response)

    def test_aborted_is_distinct_from_invalid_response(self):
        with self.assertRaises(SummaryAborted):
            check_summary_response(Message("assistant", "部分内容", stop_reason="aborted"))


if __name__ == "__main__":
    unittest.main()
