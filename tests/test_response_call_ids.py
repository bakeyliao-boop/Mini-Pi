"""D13-A：同一模型消息中的调用 ID 必须唯一，检查不能跨消息泄漏。"""

from copy import deepcopy
import unittest

from mini_pi.qwen_provider import ModelResponseError, parse_assistant_message


class ResponseCallIdTests(unittest.TestCase):
    def raw(self, ids, arguments="{}"):
        return {"role": "assistant", "content": "", "tool_calls": [
            {"id": call_id, "type": "function", "function": {
                "name": "read_file", "arguments": arguments,
            }} for call_id in ids
        ]}

    def test_duplicate_ids_rejected_in_normal_and_preserve_modes(self):
        for reason in (None, "stop", "tool_calls", "length", "error", "aborted"):
            with self.subTest(reason=reason):
                raw = self.raw(["call_001", "call_001"])
                before = deepcopy(raw)
                with self.assertRaises(ModelResponseError):
                    parse_assistant_message(raw, stop_reason=reason)
                self.assertEqual(raw, before)

    def test_duplicate_ids_rejected_even_with_truncated_arguments(self):
        with self.assertRaises(ModelResponseError):
            parse_assistant_message(
                self.raw(["call_001", "call_001"], '{"path":'), stop_reason="length",
            )

    def test_distinct_ids_preserve_order_and_input(self):
        raw = self.raw(["call_001", "call_002"])
        before = deepcopy(raw)
        message = parse_assistant_message(raw, stop_reason="tool_calls")
        self.assertEqual([call.id for call in message.tool_calls], ["call_001", "call_002"])
        self.assertEqual(raw, before)

    def test_id_tracking_is_local_to_each_message(self):
        for _ in range(2):
            message = parse_assistant_message(self.raw(["call_001"]))
            self.assertEqual(message.tool_calls[0].id, "call_001")


if __name__ == "__main__":
    unittest.main()
