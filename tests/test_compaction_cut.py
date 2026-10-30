"""D17：安全切点及未配对调用的离线反例。"""

from copy import deepcopy
import unittest

from mini_pi.compaction import choose_cut, find_safe_cut, is_safe_cut, split_for_summary
from mini_pi.context_size import estimate_qwen_item
from mini_pi.memory.errors import MemoryContextError
from mini_pi.models import Message, ToolCall, ToolResult


class SafeCutTests(unittest.TestCase):
    def test_estimator_cannot_modify_source_history_or_nested_arguments(self):
        history = [Message("user", "检查"),
                   Message("assistant", "读取", [ToolCall("a", "read", {"paths": ["a"]})]),
                   ToolResult("a", "read", "A"), Message("user", "继续")]
        before = deepcopy(history)

        def mutating_estimator(item):
            if isinstance(item, Message) and item.tool_calls:
                item.tool_calls[0].arguments["paths"].append("意外修改")
            return 1

        choose_cut(history, 3, mutating_estimator)
        self.assertEqual(history, before)

    def test_split_keeps_system_and_whole_tool_group_without_mutating_source(self):
        history = [Message("system", "规则"), Message("user", "检查"),
                   Message("assistant", "读取", [ToolCall("a", "read", {"paths": ["a"]})]),
                   ToolResult("a", "read", "A"), Message("user", "继续")]
        before = deepcopy(history)
        system, old, recent = split_for_summary(history, 4)
        self.assertEqual(system, before[:1])
        self.assertEqual(old, before[1:4])
        self.assertEqual(recent, before[4:])
        old[1].tool_calls[0].arguments["paths"].append("变化")
        system[0].content = "变化"
        recent[0].content = "变化"
        self.assertEqual(history, before)
        with self.assertRaises(ValueError):
            split_for_summary(history, 3)

    def test_split_without_system_messages(self):
        history = [Message("user", "任务"), Message("assistant", "结果")]
        system, old, recent = split_for_summary(history, 1)
        self.assertEqual(system, [])
        self.assertEqual(old, history[:1])
        self.assertEqual(recent, history[1:])

    def test_real_estimator_keeps_complete_group_when_tool_result_crosses_target(self):
        history = [Message("user", "检查"),
                   Message("assistant", "读取", [ToolCall("a", "read", {}), ToolCall("b", "read", {})]),
                   ToolResult("a", "read", "A"), ToolResult("b", "read", "中文" * 300),
                   Message("user", "继续")]
        original = deepcopy(history)
        target = estimate_qwen_item(history[-1]) + estimate_qwen_item(history[-2])
        self.assertEqual(choose_cut(history, target, estimate_qwen_item), 1)
        self.assertEqual(history, original)

    def test_choose_cut_preserves_tool_group_and_recent_target(self):
        history = [Message("system", "规则"), Message("user", "检查"),
                   Message("assistant", "读取", [ToolCall("a", "read", {}), ToolCall("b", "read", {})]),
                   ToolResult("a", "read", "A"), ToolResult("b", "read", "B"),
                   Message("user", "继续")]
        original = deepcopy(history)
        self.assertEqual(choose_cut(history, 1, lambda item: 1), 5)
        self.assertEqual(choose_cut(history, 2, lambda item: 1), 2)
        self.assertIsNone(choose_cut(history, 5, lambda item: 1))
        self.assertIsNone(choose_cut(history, 100, lambda item: 1))
        self.assertEqual(history, original)

    def test_choose_cut_rejects_invalid_estimate_and_unfinished_calls(self):
        history = [Message("user", "任务"), Message("assistant", "结果")]
        for size in (-1, True, 1.5):
            with self.subTest(size=size), self.assertRaises(ValueError):
                choose_cut(history, 1, lambda item: size)
        for target in (0, -1, True):
            with self.subTest(target=target), self.assertRaises(ValueError):
                choose_cut(history, target, lambda item: 1)
        with self.assertRaises(ValueError):
            choose_cut(history, 1, None)
        incomplete = [Message("user", "任务"), Message("assistant", "", [ToolCall("a", "read", {})])]
        with self.assertRaises(MemoryContextError):
            choose_cut(incomplete, 1, lambda item: 1)

    def test_find_moves_before_whole_tool_group_and_preserves_history(self):
        history = [Message("system", "规则"), Message("user", "检查"),
                   Message("assistant", "读取", [ToolCall("a", "read", {}), ToolCall("b", "read", {})]),
                   ToolResult("a", "read", "A"), ToolResult("b", "read", "B"),
                   Message("user", "继续")]
        before = deepcopy(history)
        self.assertEqual(find_safe_cut(history, 4), 2)
        self.assertEqual(find_safe_cut(history, 5), 5)
        self.assertEqual(history, before)

    def test_find_returns_none_or_rejects_incomplete_history(self):
        history = [Message("system", "规则"), Message("user", "检查")]
        self.assertIsNone(find_safe_cut(history, 1))
        unfinished = [Message("user", "读取"), Message("assistant", "", [ToolCall("a", "read", {})])]
        with self.assertRaises(MemoryContextError):
            find_safe_cut(unfinished, 1)
        for index in (0, len(history), True, 1.0):
            with self.subTest(index=index), self.assertRaises(ValueError):
                find_safe_cut(history, index)

    def test_two_calls_must_remain_with_both_results(self):
        history = [
            Message("system", "规则"), Message("user", "检查文件"),
            Message("assistant", "读取", [ToolCall("a", "read", {"path": "a"}),
                                          ToolCall("b", "read", {"path": "b"})]),
            ToolResult("a", "read", "A"), ToolResult("b", "read", "B"),
            Message("user", "继续"),
        ]
        original = deepcopy(history)
        self.assertFalse(is_safe_cut(history, 1))  # 旧部分只有 system
        self.assertTrue(is_safe_cut(history, 2))  # 整组调用留在近期
        self.assertFalse(is_safe_cut(history, 3))  # 调用与结果分开
        self.assertFalse(is_safe_cut(history, 4))  # A 已完成但 B 尚未配对
        self.assertTrue(is_safe_cut(history, 5))  # 整组调用均在旧部分
        self.assertEqual(history, original)

    def test_unfinished_calls_and_invalid_indices_are_rejected(self):
        history = [Message("user", "读取"), Message("assistant", "", [ToolCall("a", "read", {})])]
        with self.assertRaises(MemoryContextError):
            is_safe_cut(history, 1)
        valid = [Message("user", "任务"), Message("assistant", "结果")]
        for index in (0, 2, -1, True, 1.0):
            with self.subTest(index=index), self.assertRaises(ValueError):
                is_safe_cut(valid, index)


if __name__ == "__main__":
    unittest.main()
