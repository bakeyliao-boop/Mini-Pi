"""D13-A：历史中的残缺调用保留原文及配对反馈，不以 null 替代。

仅验证本地请求构造，不宣称真实模型服务接受任意畸形历史参数。
"""

from copy import deepcopy
import json
import unittest

from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.qwen_provider import build_request, tool_call_to_api


class RawCallHistoryTests(unittest.TestCase):
    def test_unparsed_call_keeps_original_text_and_identity(self):
        raw = '{"path":"sample.py","old_text":'
        call = ToolCall("edit_001", "edit_file", None, raw_arguments=raw)
        before = deepcopy(call)
        encoded = tool_call_to_api(call)
        self.assertEqual(encoded["id"], "edit_001")
        self.assertEqual(encoded["function"]["name"], "edit_file")
        self.assertEqual(encoded["function"]["arguments"], raw)
        self.assertEqual(call, before)

    def test_original_format_is_kept_even_with_parsed_arguments(self):
        raw = '{ "path" : "sample.py", "count": 2 }'
        call = ToolCall("read_001", "read_file", {"path": "sample.py", "count": 2}, raw_arguments=raw)
        self.assertEqual(tool_call_to_api(call)["function"]["arguments"], raw)

    def test_empty_original_is_kept_as_empty_string(self):
        call = ToolCall("edit_001", "edit_file", None, raw_arguments="")
        self.assertEqual(tool_call_to_api(call)["function"]["arguments"], "")

    def test_call_with_neither_object_nor_original_is_rejected(self):
        call = ToolCall("edit_001", "edit_file", None)
        with self.assertRaises(ValueError):
            tool_call_to_api(call)

    def test_next_request_keeps_original_and_matching_not_executed_feedback(self):
        raw = '{"path":"sample.py","old_text":'
        call = ToolCall("edit_001", "edit_file", None, raw_arguments=raw)
        history = [
            Message("user", "修正公式。"),
            Message("assistant", "部分回复。", [call], stop_reason="length"),
            ToolResult("edit_001", "edit_file", "", error="未执行：回复被截断，请重新提供完整参数"),
        ]
        before = deepcopy(history)
        request = build_request("test-model", history, [])
        messages = request["messages"]
        self.assertEqual([item["role"] for item in messages], ["user", "assistant", "tool"])
        saved_call = messages[1]["tool_calls"][0]
        self.assertEqual(saved_call["id"], messages[2]["tool_call_id"])
        self.assertEqual(saved_call["function"]["arguments"], raw)
        self.assertTrue(json.loads(messages[2]["content"])["error"])
        self.assertNotIn("raw_arguments", saved_call)
        self.assertNotIn("stop_reason", messages[1])
        self.assertEqual(history, before)


if __name__ == "__main__":
    unittest.main()
