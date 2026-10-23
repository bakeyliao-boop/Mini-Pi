"""D13-A：有条件保留未解析调用，严格模式保持原有拒绝行为。"""

from copy import deepcopy
import json
import unittest

from mini_pi.qwen_provider import parse_assistant_message, parse_tool_call


class TruncatedCallConversionTests(unittest.TestCase):
    def raw(self, arguments):
        return {"id": "edit_001", "type": "function", "function": {
            "name": "edit_file", "arguments": arguments,
        }}

    def test_strict_mode_still_rejects_incomplete_json(self):
        with self.assertRaises(json.JSONDecodeError):
            parse_tool_call(self.raw('{"path":"sample.py","old_text":'))

    def test_preserve_mode_keeps_incomplete_original_and_identity(self):
        for text in ('{"path":"sample.py","old_text":', ''):
            with self.subTest(text=text):
                raw = self.raw(text)
                before = deepcopy(raw)
                call = parse_tool_call(raw, preserve_unparsed=True)
                self.assertEqual((call.id, call.name), ("edit_001", "edit_file"))
                self.assertIsNone(call.arguments)
                self.assertEqual(call.raw_arguments, text)
                self.assertEqual(raw, before)

    def test_preserve_mode_keeps_exact_original_even_when_json_parses(self):
        text = '{ "path" : "sample.py", "count": 2 }'
        call = parse_tool_call(self.raw(text), preserve_unparsed=True)
        self.assertEqual(call.arguments, {"path": "sample.py", "count": 2})
        self.assertIs(type(call.arguments["count"]), int)
        self.assertEqual(call.raw_arguments, text)

    def test_non_object_json_is_unusable_in_preserve_mode_and_rejected_in_strict_mode(self):
        for text in ('[]', 'null', '12'):
            with self.subTest(text=text):
                call = parse_tool_call(self.raw(text), preserve_unparsed=True)
                self.assertIsNone(call.arguments)
                self.assertEqual(call.raw_arguments, text)
                with self.assertRaises(ValueError):
                    parse_tool_call(self.raw(text))

    def test_non_text_arguments_are_not_accepted_as_original(self):
        for value in (None, {}, 12):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_tool_call(self.raw(value), preserve_unparsed=True)


class TruncatedMessageConversionTests(unittest.TestCase):
    def raw(self):
        return {"role": "assistant", "content": "部分文字。", "tool_calls": [
            {"id": "edit_001", "type": "function", "function": {
                "name": "edit_file", "arguments": '{"path":"sample.py","old_text":',
            }},
            {"id": "read_001", "type": "function", "function": {
                "name": "read_file", "arguments": '{ "path": "sample.py" }',
            }},
        ]}

    def test_length_keeps_every_call_and_both_original_texts(self):
        raw = self.raw()
        before = deepcopy(raw)
        message = parse_assistant_message(raw, stop_reason="length")
        self.assertEqual(message.stop_reason, "length")
        self.assertEqual([call.id for call in message.tool_calls], ["edit_001", "read_001"])
        self.assertIsNone(message.tool_calls[0].arguments)
        self.assertEqual(message.tool_calls[1].arguments, {"path": "sample.py"})
        self.assertEqual([call.raw_arguments for call in message.tool_calls], [
            call["function"]["arguments"] for call in raw["tool_calls"]
        ])
        self.assertEqual(raw, before)

    def test_error_and_aborted_messages_can_preserve_unparsed_call(self):
        for reason in ("error", "aborted"):
            with self.subTest(reason=reason):
                message = parse_assistant_message(
                    self.raw(), stop_reason=reason, error_message="受控停止说明",
                )
                self.assertEqual(message.stop_reason, reason)
                self.assertEqual(message.error_message, "受控停止说明")
                self.assertIsNone(message.tool_calls[0].arguments)
                self.assertEqual(message.tool_calls[0].id, "edit_001")
                self.assertTrue(message.tool_calls[0].raw_arguments)

    def test_normal_and_legacy_messages_keep_strict_json_parsing(self):
        for reason in (None, "stop", "tool_calls"):
            with self.subTest(reason=reason):
                with self.assertRaises(json.JSONDecodeError):
                    parse_assistant_message(self.raw(), stop_reason=reason)


if __name__ == "__main__":
    unittest.main()
