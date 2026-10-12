"""D07：本地转换测试，不发送模型请求或执行工具。"""

import json
from copy import deepcopy
import unittest

from mini_pi.models import Message, ToolCall, ToolDefinition, ToolResult
from mini_pi.qwen_provider import (
    build_request,
    history_to_api,
    message_to_api,
    parse_assistant_message,
    parse_tool_call,
    tool_call_to_api,
    tool_definition_to_api,
    tool_result_to_api,
)


class QwenConversionTests(unittest.TestCase):
    def raw_call(self, arguments):
        return {
            "id": "call_001",
            "type": "function",
            "function": {"name": "read_file", "arguments": arguments},
        }

    def test_parses_parameters_and_preserves_call_identity(self):
        call = parse_tool_call(self.raw_call('{"path":"discount.py"}'))
        self.assertIsInstance(call, ToolCall)
        self.assertEqual(call.id, "call_001")
        self.assertEqual(call.name, "read_file")
        self.assertEqual(call.arguments, {"path": "discount.py"})

    def test_does_not_coerce_a_numeric_tool_parameter(self):
        call = parse_tool_call(self.raw_call('{"path":123}'))
        self.assertIs(type(call.arguments["path"]), int)
        self.assertEqual(call.arguments, {"path": 123})

    def test_valid_json_array_is_rejected_as_non_object_arguments(self):
        with self.assertRaises(ValueError):
            parse_tool_call(self.raw_call('["discount.py"]'))

    def test_malformed_json_is_rejected(self):
        with self.assertRaises(json.JSONDecodeError):
            parse_tool_call(self.raw_call('{"path":"discount.py"'))

    def test_message_preserves_all_calls_and_normalizes_null_content(self):
        first = self.raw_call('{"path":"discount.py"}')
        second = self.raw_call('{"path":"other.py"}')
        second["id"] = "call_002"
        message = parse_assistant_message({
            "role": "assistant",
            "content": None,
            "tool_calls": [first, second],
        })
        self.assertIsInstance(message, Message)
        self.assertEqual(message.role, "assistant")
        self.assertEqual(message.content, "")
        self.assertEqual([call.id for call in message.tool_calls], ["call_001", "call_002"])
        self.assertEqual(
            [call.arguments for call in message.tool_calls],
            [{"path": "discount.py"}, {"path": "other.py"}],
        )

    def test_plain_answer_returns_message_with_empty_call_list(self):
        for raw in (
            {"role": "assistant", "content": "文件已读取。"},
            {"role": "assistant", "content": "文件已读取。", "tool_calls": None},
            {"role": "assistant", "content": "文件已读取。", "tool_calls": []},
        ):
            with self.subTest(raw=raw):
                message = parse_assistant_message(raw)
                self.assertEqual(message, Message(role="assistant", content="文件已读取。"))

    def test_non_assistant_role_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_assistant_message({"role": "user", "content": "不应当作模型响应"})

    def test_tool_result_preserves_identity_and_text_in_api_message(self):
        result = ToolResult("call_001", "read_file", "中文文件内容\n第二行")
        api_message = tool_result_to_api(result)
        self.assertEqual(api_message["role"], "tool")
        self.assertEqual(api_message["tool_call_id"], "call_001")
        self.assertIsInstance(api_message["content"], str)
        self.assertEqual(
            json.loads(api_message["content"]),
            {"output": "中文文件内容\n第二行", "error": None},
        )

    def test_empty_success_and_failure_remain_distinguishable(self):
        success = tool_result_to_api(ToolResult("call_empty", "read_file", ""))
        failure = tool_result_to_api(
            ToolResult("call_missing", "read_file", "", error="文件不存在：missing.txt")
        )
        success_payload = json.loads(success["content"])
        failure_payload = json.loads(failure["content"])
        self.assertEqual(success_payload["output"], failure_payload["output"])
        self.assertIsNone(success_payload["error"])
        self.assertEqual(failure_payload["error"], "文件不存在：missing.txt")
        self.assertEqual(success["tool_call_id"], "call_empty")
        self.assertEqual(failure["tool_call_id"], "call_missing")

    def test_api_call_round_trip_preserves_identity_and_parameter_types(self):
        for arguments in ({"path": "目录/折扣.py"}, {"path": 123}):
            with self.subTest(arguments=arguments):
                call = ToolCall("call_001", "read_file", arguments)
                raw_call = tool_call_to_api(call)
                self.assertEqual(raw_call["id"], call.id)
                self.assertEqual(raw_call["type"], "function")
                self.assertEqual(raw_call["function"]["name"], call.name)
                self.assertIsInstance(raw_call["function"]["arguments"], str)
                self.assertEqual(json.loads(raw_call["function"]["arguments"]), arguments)
                self.assertEqual(parse_tool_call(raw_call), call)

    def test_plain_messages_preserve_role_and_text_without_call_field(self):
        for role in ("user", "assistant"):
            with self.subTest(role=role):
                message = Message(role=role, content="普通文字中提到了 read_file。")
                self.assertEqual(
                    message_to_api(message),
                    {"role": role, "content": message.content},
                )

    def test_assistant_message_round_trip_preserves_all_calls(self):
        message = Message(
            role="assistant",
            content="先读两份文件。",
            tool_calls=[
                ToolCall("call_001", "read_file", {"path": "discount.py"}),
                ToolCall("call_002", "read_file", {"path": "other.py"}),
            ],
        )
        api_message = message_to_api(message)
        self.assertEqual(api_message["role"], "assistant")
        self.assertEqual(api_message["content"], message.content)
        self.assertEqual([call["id"] for call in api_message["tool_calls"]], ["call_001", "call_002"])
        self.assertEqual(parse_assistant_message(api_message), message)

    def test_history_preserves_message_order_pairing_and_error_without_mutation(self):
        history = [
            Message(role="user", content="读取两份文件。"),
            Message(
                role="assistant",
                content="先读取。",
                tool_calls=[
                    ToolCall("call_001", "read_file", {"path": "discount.py"}),
                    ToolCall("call_002", "read_file", {"path": "missing.txt"}),
                ],
            ),
            ToolResult("call_001", "read_file", "代码内容"),
            ToolResult("call_002", "read_file", "", error="文件不存在：missing.txt"),
            Message(role="assistant", content="第二份文件不存在。"),
        ]
        original = deepcopy(history)
        api_messages = history_to_api(history)
        self.assertEqual(
            [message["role"] for message in api_messages],
            ["user", "assistant", "tool", "tool", "assistant"],
        )
        self.assertEqual(api_messages[0]["content"], history[0].content)
        self.assertEqual(api_messages[-1]["content"], history[-1].content)
        request_ids = [call["id"] for call in api_messages[1]["tool_calls"]]
        result_ids = [message["tool_call_id"] for message in api_messages[2:4]]
        self.assertEqual(request_ids, ["call_001", "call_002"])
        self.assertEqual(result_ids, request_ids)
        self.assertEqual(json.loads(api_messages[2]["content"]), {"output": "代码内容", "error": None})
        self.assertEqual(
            json.loads(api_messages[3]["content"]),
            {"output": "", "error": "文件不存在：missing.txt"},
        )
        self.assertEqual(history, original)

    def test_empty_history_returns_empty_message_list(self):
        self.assertEqual(history_to_api([]), [])

    def test_tool_definition_preserves_description_and_parameter_schema(self):
        schema = {
            "type": "object",
            "properties": {"path": {"type": "string", "minLength": 1}},
            "required": ["path"],
            "additionalProperties": False,
        }
        tool = ToolDefinition("read_file", "读取工作目录内的文件。", schema)
        raw = tool_definition_to_api(tool)
        self.assertEqual(raw["type"], "function")
        self.assertEqual(raw["function"]["name"], tool.name)
        self.assertEqual(raw["function"]["description"], tool.description)
        self.assertIsInstance(raw["function"]["parameters"], dict)
        self.assertEqual(raw["function"]["parameters"], schema)
        self.assertEqual(json.loads(json.dumps(raw)), raw)

    def test_request_contains_model_paired_history_and_tool_schema(self):
        tool = ToolDefinition(
            "read_file",
            "读取文件。",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        )
        history = [
            Message(role="user", content="读取 discount.py。"),
            Message(
                role="assistant",
                content="先读取。",
                tool_calls=[ToolCall("call_001", "read_file", {"path": "discount.py"})],
            ),
            ToolResult("call_001", "read_file", "代码内容"),
        ]
        original = deepcopy(history)
        request = build_request("qwen3.8-flash", history, [tool])
        wire_request = json.loads(json.dumps(request))
        self.assertEqual(wire_request["model"], "qwen3.8-flash")
        self.assertIs(wire_request["stream"], False)
        self.assertNotIn("message", wire_request)
        messages = wire_request["messages"]
        self.assertEqual([message["role"] for message in messages], ["user", "assistant", "tool"])
        call = messages[1]["tool_calls"][0]
        self.assertEqual(call["id"], "call_001")
        self.assertEqual(json.loads(call["function"]["arguments"]), {"path": "discount.py"})
        self.assertEqual(messages[2]["tool_call_id"], call["id"])
        self.assertEqual(json.loads(messages[2]["content"]), {"output": "代码内容", "error": None})
        definition = wire_request["tools"][0]
        self.assertEqual(definition["function"]["name"], "read_file")
        self.assertEqual(definition["function"]["description"], "读取文件。")
        self.assertEqual(definition["function"]["parameters"], tool.parameters)
        self.assertEqual(history, original)

    def test_request_without_tools_omits_tool_definitions(self):
        request = build_request("qwen3.8-flash", [Message("user", "你好。")], [])
        self.assertEqual(request["messages"], [{"role": "user", "content": "你好。"}])
        self.assertNotIn("tools", request)


if __name__ == "__main__":
    unittest.main()
