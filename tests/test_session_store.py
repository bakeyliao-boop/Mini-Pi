"""D10：检查追加记录保留请求/结果配对，且多行文字不破坏 JSONL。"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_session_", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "session.jsonl"

    def test_append_preserves_request_and_multiline_result_as_two_records(self):
        store = SessionStore(self.path, run_id="run_A")
        message = Message("assistant", "读取文件", [ToolCall("call_001", "read_file", {"path": "discount.py"})])
        result = ToolResult("call_001", "read_file", "第一行\n第二行")
        store.append_item(message)
        original = self.path.read_bytes()
        store.append_item(result)

        self.assertTrue(self.path.read_bytes().startswith(original))
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        entries = [json.loads(line) for line in lines]
        self.assertEqual([entry["type"] for entry in entries], ["message", "tool_result"])
        self.assertEqual([entry["run_id"] for entry in entries], ["run_A", "run_A"])
        self.assertEqual(entries[0]["data"]["tool_calls"][0]["id"], entries[1]["data"]["tool_call_id"])
        self.assertEqual(entries[1]["data"]["output"], "第一行\n第二行")
        self.assertTrue(all(entry["timestamp"] for entry in entries))

    def test_new_store_keeps_existing_file_and_appends_new_run(self):
        SessionStore(self.path, "run_A").append_entry("message", {"role": "user", "content": "第一次"})
        SessionStore(self.path, "run_B").append_entry("message", {"role": "user", "content": "第二次"})
        entries = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([entry["run_id"] for entry in entries], ["run_A", "run_B"])
        self.assertEqual(entries[0]["data"]["content"], "第一次")

    def test_invalid_item_is_rejected_without_creating_a_record(self):
        store = SessionStore(self.path, "run_A")
        with self.assertRaises(TypeError):
            store.append_item({"role": "user", "content": "不是统一数据类"})
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
