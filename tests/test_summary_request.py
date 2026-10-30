"""D17：待摘要记录的来源、状态和工具配对。"""

from copy import deepcopy
import json
import unittest

from mini_pi.compaction import build_summary_request
from mini_pi.memory.errors import MemoryContextError
from mini_pi.models import Message, ToolCall, ToolResult


class SummaryRequestTests(unittest.TestCase):
    def test_request_retains_user_tool_observation_and_status_without_mutation(self):
        history = [Message("user", "修复登录"),
                   Message("assistant", "运行测试", [ToolCall("t", "run_tests", {"path": "a"})],
                           stop_reason="tool_calls"),
                   ToolResult("t", "run_tests", "失败", error="测试未通过")]
        original = deepcopy(history)
        request = build_summary_request(history)
        self.assertEqual([item.role for item in request], ["system", "user"])
        records = json.loads(request[1].content)
        self.assertEqual([item["type"] for item in records], ["message", "message", "tool_result"])
        self.assertEqual(records[0]["data"]["role"], "user")
        self.assertEqual(records[1]["data"]["stop_reason"], "tool_calls")
        self.assertEqual(records[1]["data"]["tool_calls"][0]["arguments"], {"path": "a"})
        self.assertEqual(records[2]["data"]["error"], "测试未通过")
        self.assertEqual(history, original)

    def test_empty_system_and_incomplete_history_are_rejected(self):
        for history in ([], [Message("system", "规则"), Message("user", "任务")]):
            with self.subTest(history=history), self.assertRaises(ValueError):
                build_summary_request(history)
        incomplete = [Message("user", "读取"), Message("assistant", "", [ToolCall("a", "read", {})])]
        with self.assertRaises(MemoryContextError):
            build_summary_request(incomplete)


if __name__ == "__main__":
    unittest.main()
