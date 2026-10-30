"""候选摘要请求历史的顺序、配对与隔离。"""

from copy import deepcopy
import unittest

from mini_pi.compaction import build_compacted_history, build_compacted_request
from mini_pi.memory.errors import MemoryContextError
from mini_pi.models import Message, ToolCall, ToolResult


class CompactedHistoryTests(unittest.TestCase):
    def test_final_candidate_orders_references_and_preserves_source_objects(self):
        system = [Message("system", "规则")]
        references = [Message("user", "本轮参考资料")]
        recent = [Message("assistant", "读取", [ToolCall("r", "read", {"files": ["a"]})]),
                  ToolResult("r", "read", "结果"), Message("user", "继续")]
        before = deepcopy((system, references, recent))
        result = build_compacted_request(system, "旧过程摘要", recent, references)
        self.assertEqual(result[0], system[0])
        self.assertEqual(result[1], references[0])
        self.assertIn("旧过程摘要", result[2].content)
        self.assertEqual(result[3:], recent)
        result[1].content = "更改"
        result[3].tool_calls[0].arguments["files"].append("更改")
        self.assertEqual((system, references, recent), before)

    def test_reference_validation_and_empty_reference(self):
        recent = [Message("user", "继续")]
        result = build_compacted_request([], "摘要", recent, [])
        self.assertEqual(len(result), 2)
        for refs in (None, [Message("system", "资料")],
                     [Message("user", "资料", [ToolCall("x", "read", {})])]):
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                build_compacted_request([], "摘要", recent, refs)

    def test_system_summary_recent_order_and_deep_copy(self):
        system = [Message("system", "保留测试")]
        recent = [Message("assistant", "读取", [ToolCall("a", "read", {"paths": ["a"]})]),
                  ToolResult("a", "read", "内容"), Message("user", "继续")]
        before = deepcopy((system, recent))
        messages = build_compacted_history(system, "测试失败，待排查", recent)
        self.assertEqual(messages[0], system[0])
        self.assertEqual(messages[1].role, "user")
        self.assertIn("旧会话摘要", messages[1].content)
        self.assertIn("测试失败，待排查", messages[1].content)
        self.assertEqual(messages[2:], recent)
        messages[0].content = "修改"
        messages[2].tool_calls[0].arguments["paths"].append("修改")
        self.assertEqual((system, recent), before)

    def test_unsafe_and_empty_inputs_are_rejected(self):
        orphan = [ToolResult("a", "read", "内容")]
        with self.assertRaises(MemoryContextError):
            build_compacted_history([], "摘要", orphan)
        for system, summary, recent in (([], " ", [Message("user", "继续")]),
                                        ([], "摘要", []),
                                        ([Message("user", "不是系统")], "摘要", [Message("user", "继续")])):
            with self.subTest(system=system, summary=summary, recent=recent), self.assertRaises(ValueError):
                build_compacted_history(system, summary, recent)


if __name__ == "__main__":
    unittest.main()
