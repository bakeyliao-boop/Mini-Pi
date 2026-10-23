"""D13-A 正文边界：格式错误在调用解析之前拒绝。"""

import unittest
from unittest.mock import patch

from mini_pi.qwen_provider import ModelResponseError, parse_assistant_message


class ResponseMessageTests(unittest.TestCase):
    def test_invalid_call_container_is_rejected_before_call_parsing(self):
        for calls in ({}, "", 0, False, {"id": "edit_001"}, "call"):
            with self.subTest(calls=calls):
                with patch("mini_pi.qwen_provider.parse_tool_call") as parse_call:
                    with self.assertRaises(ModelResponseError):
                        parse_assistant_message({
                            "role": "assistant", "content": "", "tool_calls": calls,
                        })
                    parse_call.assert_not_called()

    def test_missing_null_and_empty_call_list_mean_no_calls(self):
        for raw in (
            {"role": "assistant", "content": "回答"},
            {"role": "assistant", "content": "回答", "tool_calls": None},
            {"role": "assistant", "content": "回答", "tool_calls": []},
        ):
            with self.subTest(raw=raw):
                self.assertEqual(parse_assistant_message(raw).tool_calls, [])

    def test_non_object_message_is_rejected(self):
        for raw in (None, [], "text", 0, False):
            with self.subTest(raw=raw):
                with self.assertRaises(ModelResponseError):
                    parse_assistant_message(raw)

    def test_invalid_role_uses_response_error(self):
        for role in (None, "user", "tool", 1):
            with self.subTest(role=role):
                with self.assertRaises(ModelResponseError):
                    parse_assistant_message({"role": role, "content": "text"})

    def test_invalid_content_is_rejected_before_call_parsing(self):
        for content in ({"invalid": "object"}, {}, [], 0, False, 1):
            with self.subTest(content=content):
                with patch("mini_pi.qwen_provider.parse_tool_call") as parse_call:
                    with self.assertRaises(ModelResponseError):
                        parse_assistant_message({
                            "role": "assistant", "content": content,
                            "tool_calls": [{"id": "edit_001"}],
                        })
                    parse_call.assert_not_called()

    def test_null_and_missing_content_normalize_but_text_is_preserved(self):
        for raw, expected in (
            ({"role": "assistant"}, ""),
            ({"role": "assistant", "content": None}, ""),
            ({"role": "assistant", "content": ""}, ""),
            ({"role": "assistant", "content": "原文\n"}, "原文\n"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(parse_assistant_message(raw).content, expected)


if __name__ == "__main__":
    unittest.main()
