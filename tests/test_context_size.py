"""D16输入投影估算：覆盖工具定义、适配器编码与整理后的实际内容。"""

from copy import deepcopy
import json
import unittest

from mini_pi.context import ReadOutputContext
from mini_pi.context_budget import ContextBudgetError, check_estimated_window
from mini_pi.context_size import estimate_qwen_input, estimate_qwen_item, serialize_qwen_input
from mini_pi.models import Message, ToolCall, ToolDefinition, ToolResult
from mini_pi.qwen_provider import build_request


class InputSizeTests(unittest.TestCase):
    def test_single_item_estimation_covers_text_tool_arguments_and_results(self):
        short = Message("user", "短")
        long = Message("user", "中文🙂" * 300)
        small_call = Message("assistant", "", [ToolCall("id", "read", {"path": "a"})])
        large_call = Message("assistant", "", [ToolCall("id", "read", {"path": "a" * 1000})])
        small_result = ToolResult("id", "read", "短")
        large_result = ToolResult("id", "read", "长" * 1000)
        before = deepcopy([short, long, small_call, large_call, small_result, large_result])
        for small, large in ((short, long), (small_call, large_call), (small_result, large_result)):
            self.assertGreater(estimate_qwen_item(large), estimate_qwen_item(small))
        self.assertEqual([short, long, small_call, large_call, small_result, large_result], before)
        with self.assertRaises(TypeError):
            estimate_qwen_item("非记录")

    def tool(self, description="读取文件", detail="相对路径"):
        return ToolDefinition("read_file", description, {"type": "object", "properties": {
            "path": {"type": "string", "description": detail}}, "required": ["path"]})

    def test_projection_matches_actual_adapter_message_and_tool_encoding(self):
        messages = [Message("user", "读取文件"),
                    Message("assistant", "读取", [ToolCall("r1", "read_file", {"path": "a.py"})]),
                    ToolResult("r1", "read_file", "文件正文", error=None)]
        tools = [self.tool()]
        request = build_request("offline-test-model", messages, tools)
        projection = json.loads(serialize_qwen_input(messages, tools))
        self.assertEqual(projection, {"messages": request["messages"], "tools": request["tools"]})

    def test_tool_description_and_schema_each_increase_estimate(self):
        messages = [Message("user", "读取")]
        basic = estimate_qwen_input(messages, [self.tool()])
        long_description = estimate_qwen_input(messages, [self.tool(description="工具说明" * 500)])
        long_schema = estimate_qwen_input(messages, [self.tool(detail="参数说明" * 500)])
        for expanded in (long_description, long_schema):
            self.assertGreater(expanded.json_chars, basic.json_chars)
            self.assertGreater(expanded.estimated_input_tokens, basic.estimated_input_tokens)

    def test_large_tools_can_exceed_window_when_same_messages_previously_fit(self):
        messages = [Message("user", "很短的问题")]
        small = estimate_qwen_input(messages, [])
        large = estimate_qwen_input(messages, [self.tool(description="工具定义" * 1000)])
        window = small.estimated_input_tokens + 10 + 5
        self.assertIsNone(check_estimated_window(small.estimated_input_tokens, 10, window, 5))
        with self.assertRaises(ContextBudgetError):
            check_estimated_window(large.estimated_input_tokens, 10, window, 5)

    def test_unicode_count_and_explicit_estimation_method(self):
        messages = [Message("user", "中文🙂内容")]
        encoded = serialize_qwen_input(messages, [])
        size = estimate_qwen_input(messages, [])
        self.assertEqual(size.json_chars, len(encoded))
        self.assertGreater(len(encoded.encode("utf-8")), size.json_chars)
        self.assertGreaterEqual(size.estimated_input_tokens * 4, size.json_chars)
        self.assertLess((size.estimated_input_tokens - 1) * 4, size.json_chars)
        self.assertEqual(size.method, "qwen-input-json-chars-div4-v1")
        self.assertNotIn("tools", json.loads(encoded))

    def test_reference_material_counts_without_mutating_messages_or_tools(self):
        messages = [Message("user", "任务")]
        material = Message("user", '{"purpose":"本次参考材料","memories":["' + "参考" * 100 + '"]}')
        prepared = [material, *messages]
        tools = [self.tool()]
        before = deepcopy((messages, prepared, tools))
        baseline = estimate_qwen_input(messages, tools)
        with_material = estimate_qwen_input(prepared, tools)
        self.assertGreater(with_material.estimated_input_tokens, baseline.estimated_input_tokens)
        self.assertEqual((messages, prepared, tools), before)

    def test_truncated_call_raw_arguments_remain_in_projection(self):
        raw_arguments = '{"path":"a.py","new_text":'
        messages = [Message("assistant", "", [ToolCall("cut", "edit_file", None, raw_arguments)],
                            stop_reason="length"),
                    ToolResult("cut", "edit_file", "", error="未执行：回复截断")]
        before = deepcopy(messages)
        projection = json.loads(serialize_qwen_input(messages, []))
        self.assertEqual(projection["messages"][0]["tool_calls"][0]["function"]["arguments"], raw_arguments)
        self.assertGreater(estimate_qwen_input(messages, []).json_chars, 0)
        self.assertEqual(messages, before)

    def test_non_json_numeric_schema_is_rejected_instead_of_silently_counted(self):
        tool = ToolDefinition("bad", "非法数值", {"minimum": float("nan")})
        with self.assertRaises(ValueError):
            estimate_qwen_input([Message("user", "任务")], [tool])


class InputSizeAfterBuildTests(unittest.IsolatedAsyncioTestCase):
    async def test_estimate_uses_shortened_request_and_keeps_original_full_output(self):
        messages = [Message("user", "读文件"),
                    Message("assistant", "", [ToolCall("r1", "read_file", {"path": "a.py"})]),
                    ToolResult("r1", "read_file", "正文" * 2000)]
        before = deepcopy(messages)
        tools = [ToolDefinition("read_file", "读取", {"type": "object"})]
        original_size = estimate_qwen_input(messages, tools)
        built = await ReadOutputContext(120).build(messages)
        request_size = estimate_qwen_input(built, tools)
        self.assertLess(request_size.json_chars, original_size.json_chars)
        self.assertLess(request_size.estimated_input_tokens, original_size.estimated_input_tokens)
        self.assertIn("省略", built[-1].output)
        self.assertEqual(messages, before)


if __name__ == "__main__":
    unittest.main()
