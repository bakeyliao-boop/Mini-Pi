"""D13-A：未解析参数的记录边界、原文保留与执行器拒绝。

格式校验测试可以先运行；ToolCall 字段测试须待学习者手敲后验收。
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_records import read_session_records
from mini_pi.session_recovery import find_pending_calls
from mini_pi.session_store import SessionStore
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy


class UnparsedRecordValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_raw_args_", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "session.jsonl"
        self.raw = '{"path":"sample.py","old_text":'

    def save(self, call, reason=None):
        data = {"role": "assistant", "content": "", "tool_calls": [call]}
        if reason is not None:
            data["stop_reason"] = reason
        SessionStore(self.path).append_entry("message", data)
        return self.path.read_bytes()

    def test_legacy_dictionary_call_is_still_valid(self):
        before = self.save({"id": "edit_001", "name": "edit_file", "arguments": {"path": "sample.py"}})
        self.assertEqual(len(read_session_records(self.path)), 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_optional_null_raw_field_accepts_normal_call(self):
        self.save({"id": "read_001", "name": "read_file", "arguments": {"path": "sample.py"}, "raw_arguments": None}, "tool_calls")
        self.assertEqual(len(read_session_records(self.path)), 1)

    def test_length_record_keeps_unparsed_original(self):
        self.save({"id": "edit_001", "name": "edit_file", "arguments": None, "raw_arguments": self.raw}, "length")
        row = read_session_records(self.path)[0]
        self.assertEqual(row["data"]["tool_calls"][0]["raw_arguments"], self.raw)
        self.assertIsNone(row["data"]["tool_calls"][0]["arguments"])

    def test_normal_response_cannot_save_unparsed_arguments(self):
        before = self.save({"id": "edit_001", "name": "edit_file", "arguments": None, "raw_arguments": self.raw}, "tool_calls")
        with self.assertRaisesRegex(ValueError, "未解析参数"):
            read_session_records(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_unparsed_arguments_require_original_text(self):
        self.save({"id": "edit_001", "name": "edit_file", "arguments": None}, "length")
        with self.assertRaisesRegex(ValueError, "未解析参数"):
            read_session_records(self.path)

    def test_non_text_original_is_rejected(self):
        self.save({"id": "edit_001", "name": "edit_file", "arguments": None, "raw_arguments": 123}, "length")
        with self.assertRaisesRegex(ValueError, "raw_arguments"):
            read_session_records(self.path)

    def test_unknown_call_field_is_still_rejected(self):
        self.save({"id": "edit_001", "name": "edit_file", "arguments": {}, "extra": True})
        with self.assertRaises(ValueError):
            read_session_records(self.path)


class UnparsedToolCallTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_unparsed_call_", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.raw = '{"path":"sample.py","old_text":'

    async def test_unparsed_call_round_trip_keeps_identity_original_and_pending(self):
        call = ToolCall("edit_001", "edit_file", None, raw_arguments=self.raw)
        store = SessionStore(self.root / "session.jsonl")
        message = Message("assistant", "", [call], stop_reason="length")
        store.append_item(message)
        before = store.path.read_bytes()
        loaded = store.load()
        self.assertEqual(loaded.history, [message])
        self.assertEqual(find_pending_calls(loaded)[0].call, call)
        self.assertEqual(store.path.read_bytes(), before)
        store.append_item(ToolResult("edit_001", "edit_file", "", error="未执行：回复被截断"))
        self.assertEqual(find_pending_calls(store.load()), [])

    async def test_executor_rejects_unparsed_call_before_writing(self):
        target = self.root / "sample.py"
        target.write_bytes(b"value = 1\n")
        editor = EditFileExecutor(EditPolicy(self.root, ["sample.py"]))
        call = ToolCall("edit_001", "edit_file", None, raw_arguments=self.raw)
        result = await editor.execute(call)
        self.assertTrue(result.error)
        self.assertEqual(result.tool_call_id, "edit_001")
        self.assertEqual(target.read_bytes(), b"value = 1\n")


if __name__ == "__main__":
    unittest.main()
