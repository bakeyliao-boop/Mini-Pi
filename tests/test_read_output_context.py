"""D16第二段：完整请求副本的整理、隔离与Provider交接。"""

from copy import deepcopy
from dataclasses import replace
from typing import get_type_hints
import unittest
from unittest.mock import patch

from mini_pi.context import ContextProvider, ReadOutputContext
from mini_pi.memory.errors import MemoryContextError
from mini_pi.mock_provider import MockProvider
from mini_pi.models import ConversationItem, Message, ToolCall, ToolDefinition, ToolResult


class ReadOutputContextTests(unittest.IsolatedAsyncioTestCase):
    def history(self):
        return [
            Message("system", "编程助手"),
            Message("user", '{"purpose":"本次请求参考材料","memories":["使用Python"]}'),
            Message("user", "只修改discount.py，不修改测试"),
            Message("assistant", "读取并测试", [
                ToolCall("read-a", "read_file", {"path": "discount.py"}),
                ToolCall("tests-b", "run_tests", {}),
            ]),
            ToolResult("read-a", "read_file", "def calculate():\n" + "正文" * 1000),
            ToolResult("tests-b", "run_tests", '{"outcome":"failed","exit_code":1}'),
        ]

    def test_build_annotations_resolve_to_declared_types(self):
        hints = get_type_hints(ReadOutputContext.build)
        self.assertEqual(hints["return"], list[ConversationItem])

    async def test_preserves_message_order_material_calls_and_test_failure(self):
        original = self.history()
        before = deepcopy(original)
        result = await ReadOutputContext(120).build(original)
        self.assertEqual(len(result), len(original))
        self.assertEqual(result[:4], before[:4])
        self.assertEqual(result[-1], before[-1])
        self.assertEqual(result[4].tool_call_id, "read-a")
        self.assertEqual(result[4].tool_name, "read_file")
        self.assertIsNone(result[4].error)
        self.assertEqual(len(result[4].output), 120)
        self.assertIn("省略", result[4].output)
        self.assertEqual(original, before)

    async def test_returned_items_and_nested_arguments_are_isolated(self):
        original = self.history()
        before = deepcopy(original)
        result = await ReadOutputContext(120).build(tuple(original))
        self.assertIsInstance(result, list)
        for copied, raw in zip(result, original):
            self.assertIsNot(copied, raw)
        result[1].content = "修改返回的参考材料"
        result[3].tool_calls[0].arguments["path"] = "other.py"
        result[4].output = "修改返回的读取结果"
        result.pop()
        self.assertEqual(original, before)

    async def test_short_read_and_read_failure_remain_unchanged(self):
        for error, output in ((None, "短文"), ("读取失败", "诊断" * 100)):
            with self.subTest(error=error):
                original = [
                    Message("assistant", "读取", [ToolCall("read-short", "read_file", {"path": "a.py"})]),
                    ToolResult("read-short", "read_file", output, error),
                ]
                before = deepcopy(original)
                result = await ReadOutputContext(120).build(original)
                self.assertEqual(result, before)
                self.assertEqual(original, before)
                self.assertIsNot(result[0], original[0])
                self.assertIsNot(result[1], original[1])
        self.assertEqual(await ReadOutputContext(120).build([]), [])

    async def test_provider_receives_shortened_snapshot_with_tools(self):
        original = self.history()
        before = deepcopy(original)
        tools = [ToolDefinition("read_file", "读取文件", {"type": "object"})]
        provider = MockProvider([Message("assistant", "完成")])
        wrapped = ContextProvider(provider, ReadOutputContext(120))
        reply = await wrapped.generate(original, tools)
        self.assertEqual(reply.content, "完成")
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(len(provider.requests[0][4].output), 120)
        self.assertEqual(provider.requests[0][-1], before[-1])
        self.assertEqual(provider.tool_requests, [tools])
        self.assertEqual(original, before)

    async def test_invalid_history_blocks_before_reduction_or_model_request(self):
        call_a = ToolCall("a", "read_file", {"path": "a.py"})
        call_b = ToolCall("b", "read_file", {"path": "b.py"})
        result_a = ToolResult("a", "read_file", "a" * 500)
        result_b = ToolResult("b", "read_file", "b" * 500)
        malformed = {
            "orphan": [result_a],
            "missing_result": [Message("assistant", "", [call_a, call_b]), result_a],
            "wrong_name": [Message("assistant", "", [call_a]), replace(result_a, tool_name="run_tests")],
            "duplicate_result": [Message("assistant", "", [call_a]), result_a, result_a],
            "duplicate_call": [Message("assistant", "", [call_a, call_a]), result_a],
            "interrupted_group": [Message("assistant", "", [call_a, call_b]), result_a,
                                  Message("user", "继续"), result_b],
        }
        for label, original in malformed.items():
            with self.subTest(case=label):
                before = deepcopy(original)
                provider = MockProvider([])
                wrapped = ContextProvider(provider, ReadOutputContext(120))
                with patch("mini_pi.context.shorten_read_result") as shortener:
                    with self.assertRaises(MemoryContextError):
                        await wrapped.generate(original, [])
                    shortener.assert_not_called()
                self.assertEqual(provider.requests, [])
                self.assertEqual(original, before)

    async def test_corrupted_reduction_is_rejected_before_model_request(self):
        for field, value in (("tool_call_id", "wrong-id"), ("tool_name", "wrong-tool"), ("output", None)):
            with self.subTest(field=field):
                original = self.history()
                before = deepcopy(original)
                provider = MockProvider([])
                wrapped = ContextProvider(provider, ReadOutputContext(120))
                def corrupt(item, limit):
                    return replace(item, **{field: value}) if item.tool_call_id == "read-a" else item
                with patch("mini_pi.context.shorten_read_result", side_effect=corrupt):
                    with self.assertRaises(MemoryContextError):
                        await wrapped.generate(original, [])
                self.assertEqual(provider.requests, [])
                self.assertEqual(original, before)

    async def test_truncated_call_with_unexecuted_feedback_remains_valid(self):
        original = [
            Message("assistant", "", [ToolCall("cut", "edit_file", None, '{"path":')], stop_reason="length"),
            ToolResult("cut", "edit_file", "", error="未执行，模型回复被截断"),
        ]
        before = deepcopy(original)
        result = await ReadOutputContext(120).build(original)
        self.assertEqual(result, before)
        self.assertEqual(original, before)

    async def test_too_small_limit_does_not_send_or_mutate_original(self):
        original = self.history()
        before = deepcopy(original)
        provider = MockProvider([])
        wrapped = ContextProvider(provider, ReadOutputContext(1))
        with self.assertRaises(ValueError):
            await wrapped.generate(original, [])
        self.assertEqual(provider.requests, [])
        self.assertEqual(original, before)

    async def test_invalid_configuration_and_repeated_builds(self):
        for limit in (0, -1, True, False, "120", None, 1.5):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    ReadOutputContext(limit)
        original = self.history()
        before = deepcopy(original)
        builder = ReadOutputContext(120)
        first = await builder.build(original)
        second = await builder.build(original)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertEqual(first[4].output.count("省略"), 1)
        self.assertEqual(original, before)


if __name__ == "__main__":
    unittest.main()
