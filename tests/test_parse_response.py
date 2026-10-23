"""D13-A 统一响应转换入口：错误分类、原文保留与内部异常边界。"""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from mini_pi.qwen_provider import ModelResponseError, parse_response


class ParseResponseTests(unittest.TestCase):
    def response(self, reason="stop", arguments=None):
        message = {"role": "assistant", "content": "回复"}
        if arguments is not None:
            message["tool_calls"] = [{"id": "edit_001", "type": "function", "function": {
                "name": "edit_file", "arguments": arguments,
            }}]
        return {"choices": [{"finish_reason": reason, "message": message}]}

    def test_normal_message_and_input_preserved(self):
        raw = self.response()
        before = deepcopy(raw)
        message = parse_response(raw)
        self.assertEqual((message.content, message.stop_reason), ("回复", "stop"))
        self.assertEqual(raw, before)

    def test_outer_and_message_errors_are_classified(self):
        for raw in ({}, {"choices": []}, {"choices": [{"finish_reason": "stop"}]}):
            with self.subTest(raw=raw):
                with self.assertRaises(ModelResponseError):
                    parse_response(raw)

    def test_finish_reason_must_be_nonempty_text(self):
        for reason in (None, "", "  ", 0, [], {}):
            with self.subTest(reason=reason):
                with self.assertRaises(ModelResponseError):
                    parse_response(self.response(reason))
        raw = self.response()
        del raw["choices"][0]["finish_reason"]
        with self.assertRaises(ModelResponseError):
            parse_response(raw)

    def test_service_error_reason_returns_error_message(self):
        message = parse_response(self.response("content_filter", '{"path":'))
        self.assertEqual(message.stop_reason, "error")
        self.assertIn("content_filter", message.error_message)
        self.assertEqual(message.tool_calls[0].id, "edit_001")
        self.assertIsNone(message.tool_calls[0].arguments)

    def test_normal_invalid_json_is_classified_with_cause(self):
        with self.assertRaises(ModelResponseError) as caught:
            parse_response(self.response("tool_calls", '{"path":'))
        self.assertIsInstance(caught.exception.__cause__, json.JSONDecodeError)

    def test_normal_non_object_arguments_are_classified(self):
        for text in ("[]", "null", "123"):
            with self.subTest(text=text):
                with self.assertRaises(ModelResponseError):
                    parse_response(self.response("tool_calls", text))

    def test_length_preserves_id_and_exact_incomplete_arguments(self):
        message = parse_response(self.response("length", '{ "path":'))
        self.assertEqual(message.stop_reason, "length")
        self.assertEqual(message.tool_calls[0].id, "edit_001")
        self.assertEqual(message.tool_calls[0].raw_arguments, '{ "path":')
        self.assertIsNone(message.tool_calls[0].arguments)

    def test_internal_assertion_remains_visible(self):
        marker = AssertionError("internal test marker")
        with patch("mini_pi.qwen_provider.parse_assistant_message", side_effect=marker):
            with self.assertRaises(AssertionError) as caught:
                parse_response(self.response())
        self.assertIs(caught.exception, marker)


if __name__ == "__main__":
    unittest.main()
