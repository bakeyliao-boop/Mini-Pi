"""助手准备：真实 Session JSONL → MemorySource 的只读 I/O 验证。"""

import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.models import MemoryScope
from mini_pi.memory.session_source import read_memory_source
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_records import read_session_records
from mini_pi.session_store import SessionStore


class MemorySourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "来源 空格.jsonl"
        self.scope = MemoryScope("user-a", "project-a")
        self.store = SessionStore(self.path, run_id="recorded-run")

    def file_hash(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_reads_actual_user_message_and_record_timestamp_without_writes(self):
        original = '周末晚上学习；不能把“未通过”改成“通过”。\n第二行。'
        self.store.append_item(Message("user", original))
        before = self.file_hash()
        record = read_session_records(self.path)[0]
        source = read_memory_source(self.path, 0, self.scope)
        self.assertEqual(original, source.text)
        self.assertEqual("user", source.role)
        self.assertEqual(record["timestamp"], source.recorded_at)
        self.assertEqual(self.scope, source.scope)
        self.assertEqual(before, self.file_hash())
        self.assertEqual([self.path], list(self.path.parent.iterdir()))

    def test_append_does_not_change_preexisting_source_identity(self):
        self.store.append_item(Message("user", "早上学习"))
        first = read_memory_source(self.path, 0, self.scope)
        SessionStore(self.path, run_id="another-run").append_item(Message("user", "后来又补充一条"))
        before = self.file_hash()
        self.assertEqual(first, read_memory_source(self.path, 0, self.scope))
        self.assertNotEqual(first.source_id, read_memory_source(self.path, 1, self.scope).source_id)
        self.assertEqual(before, self.file_hash())

    def test_same_file_path_aliases_use_same_source_identity(self):
        self.store.append_item(Message("user", "保存原话"))
        absolute = read_memory_source(self.path, 0, self.scope)
        relative = read_memory_source(os.path.relpath(self.path, Path.cwd()), 0, self.scope)
        self.assertEqual(absolute.source_id, relative.source_id)

    def test_content_edit_keeps_id_so_store_can_detect_changed_source(self):
        self.store.append_item(Message("user", "晚上"))
        original = read_memory_source(self.path, 0, self.scope)
        record = read_session_records(self.path)[0]
        record["data"]["content"] = "早上"
        self.path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        before = self.file_hash()
        changed = read_memory_source(self.path, 0, self.scope)
        self.assertEqual(original.source_id, changed.source_id)
        self.assertNotEqual(original.text, changed.text)
        self.assertEqual(before, self.file_hash())

    def test_tool_result_retains_error_name_call_id_and_full_data(self):
        result = ToolResult("call-1", "run_tests", "输出中包括两项失败", error="测试未通过")
        self.store.append_item(result)
        before = self.file_hash()
        source = read_memory_source(self.path, 0, self.scope)
        self.assertEqual("tool", source.role)
        self.assertEqual({
            "tool_call_id": result.tool_call_id, "tool_name": result.tool_name,
            "output": result.output, "error": result.error,
        }, json.loads(source.text))
        self.assertEqual(before, self.file_hash())

    def test_tool_source_keeps_additional_observation_fields(self):
        data = {"tool_call_id": "c", "tool_name": "run_tests", "output": "失败",
                "error": "测试失败", "exit_code": 1, "details": {"passed": False}}
        self.store.append_entry("tool_result", data)
        source = read_memory_source(self.path, 0, self.scope)
        self.assertEqual(data, json.loads(source.text))
        self.assertEqual(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")), source.text)

    def test_assistant_and_system_roles_are_not_laundered_into_user(self):
        self.store.append_item(Message("assistant", "我猜测已经成功", [ToolCall("call", "edit_file", {"path": "x"})]))
        self.store.append_item(Message("system", "程序规则"))
        before = self.file_hash()
        assistant = read_memory_source(self.path, 0, self.scope)
        system = read_memory_source(self.path, 1, self.scope)
        self.assertEqual(("assistant", "我猜测已经成功"), (assistant.role, assistant.text))
        self.assertEqual(("system", "程序规则"), (system.role, system.text))
        self.assertEqual(before, self.file_hash())

    def test_run_events_rejected_without_altering_file(self):
        self.store.append_entry("run_start", {"status": "running"})
        self.store.append_entry("run_end", {"status": "finished", "task_passed": None})
        before = self.file_hash()
        for index in (0, 1):
            with self.subTest(index=index):
                with self.assertRaises(MemoryPolicyError):
                    read_memory_source(self.path, index, self.scope)
        self.assertEqual(before, self.file_hash())

    def test_invalid_record_indexes_are_rejected_without_altering_file(self):
        self.store.append_item(Message("user", "原话"))
        before = self.file_hash()
        for index in (-1, 1, True, False, 0.0, "0", None):
            with self.subTest(index=index):
                with self.assertRaises(MemoryPolicyError):
                    read_memory_source(self.path, index, self.scope)
        self.assertEqual(before, self.file_hash())

    def test_malformed_record_is_explicitly_rejected(self):
        for payload in ('{', '{}', '{"type":"message"}'):
            with self.subTest(payload=payload):
                self.path.write_text(payload + "\n", encoding="utf-8")
                before = self.file_hash()
                with self.assertRaises(MemoryPolicyError):
                    read_memory_source(self.path, 0, self.scope)
                self.assertEqual(before, self.file_hash())

    def test_blank_lines_do_not_count_as_records(self):
        self.store.append_item(Message("user", "原话"))
        original = read_memory_source(self.path, 0, self.scope)
        self.path.write_text("\n" + self.path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.assertEqual(original, read_memory_source(self.path, 0, self.scope))

    def test_missing_file_never_creates_source_or_database(self):
        missing = self.path.parent / "未创建" / "missing.jsonl"
        with self.assertRaises(FileNotFoundError):
            read_memory_source(missing, 0, self.scope)
        self.assertFalse(missing.parent.exists())

    def test_invalid_scope_rejected_before_source_read(self):
        self.store.append_item(Message("user", "原话"))
        before = self.file_hash()
        for scope in (MemoryScope("", "project"), MemoryScope("user", " "), None):
            with self.subTest(scope=scope):
                with self.assertRaises(MemoryPolicyError):
                    read_memory_source(self.path, 0, scope)
        self.assertEqual(before, self.file_hash())


if __name__ == "__main__":
    unittest.main()
