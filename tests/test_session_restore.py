"""D11：核对已保存结果的还原，不重复执行历史工具请求。"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.qwen_provider import history_to_api
from mini_pi.session_store import SessionStore
from mini_pi.tools.read_file import ReadFileExecutor


class SessionRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_restore_", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "session.jsonl"
        self.store = SessionStore(self.path, "run_A")

    def test_saved_success_and_failure_results_are_restored_without_changing_records(self):
        original_results = [
            ToolResult("call_001", "read_file", "第一行\n第二行"),
            ToolResult("call_002", "read_file", "", "文件不存在：missing.py"),
        ]
        for result in original_results:
            self.store.append_item(result)
        before = self.path.read_bytes()
        entries = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        restored = [self.store._restore_item(entry["type"], entry["data"]) for entry in entries]

        self.assertEqual(restored, original_results)
        self.assertTrue(all(isinstance(item, ToolResult) for item in restored))
        self.assertEqual(self.path.read_bytes(), before)

    def test_restored_result_can_be_sent_as_tool_message_by_existing_adapter(self):
        restored = self.store._restore_item("tool_result", {
            "tool_call_id": "call_001", "tool_name": "read_file",
            "output": "文件内容", "error": None,
        })
        messages = history_to_api([restored])
        self.assertEqual(messages[0]["role"], "tool")
        self.assertEqual(messages[0]["tool_call_id"], "call_001")
        self.assertEqual(json.loads(messages[0]["content"]), {"output": "文件内容", "error": None})

    def test_messages_restore_nested_tool_calls_as_objects(self):
        original_messages = [
            Message("user", "读取文件。"),
            Message("assistant", "先读取文件。", [
                ToolCall("call_001", "read_file", {"path": "discount.py"}),
            ]),
        ]
        for message in original_messages:
            self.store.append_item(message)
        entries = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        restored = [self.store._restore_item(entry["type"], entry["data"]) for entry in entries]
        self.assertEqual(restored, original_messages)
        self.assertIsInstance(restored[1].tool_calls[0], ToolCall)
        self.assertEqual(history_to_api(restored)[1]["tool_calls"][0]["id"], "call_001")

    def test_load_keeps_events_separate_and_does_not_reexecute_saved_call(self):
        items = [
            Message("user", "读取文件。"),
            Message("assistant", "先读取文件。", [
                ToolCall("call_001", "read_file", {"path": "discount.py"}),
            ]),
            ToolResult("call_001", "read_file", "以前读到的内容"),
            Message("assistant", "读取完成。"),
        ]
        self.store.append_entry("run_start", {"status": "running"})
        for item in items:
            self.store.append_item(item)
        self.store.append_entry("run_end", {"status": "finished", "task_passed": None, "error": None})
        before = self.path.read_bytes()
        with patch.object(ReadFileExecutor, "execute") as execute:
            loaded = self.store.load()
        execute.assert_not_called()
        self.assertEqual(loaded.history, items)
        self.assertEqual(len(loaded.records), 6)
        self.assertEqual([record["type"] for record in loaded.records], [
            "run_start", "message", "message", "tool_result", "message", "run_end",
        ])
        self.assertEqual(self.path.read_bytes(), before)

    def test_broken_json_line_reports_line_number_without_modifying_file(self):
        self.store.append_entry("run_start", {"status": "running"})
        with self.path.open("a", encoding="utf-8") as file:
            file.write('{"type": "message",\n')
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "第 2 行"):
            self.store.load()
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_call_structure_is_rejected_before_restoring_history(self):
        self.store.append_entry("message", {
            "role": "assistant", "content": "调用参数结构损坏。",
            "tool_calls": [{"id": "call_001", "name": "read_file", "arguments": "不是字典"}],
        })
        with self.assertRaisesRegex(ValueError, "第 1 行.*arguments"):
            self.store.load()


if __name__ == "__main__":
    unittest.main()
