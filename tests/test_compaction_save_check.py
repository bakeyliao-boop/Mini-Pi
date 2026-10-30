"""真实临时会话的摘要保存前门禁。"""

from dataclasses import asdict, replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mini_pi.compaction_binding import check_before_compaction_save, make_compaction_binding
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore


class CompactionSaveCheckTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "session.jsonl"
        self.store = SessionStore(self.path, "run-a")
        self.store.append_entry("run_start", {"status": "running"})
        self.store.append_item(Message("system", "规则"))
        self.store.append_item(Message("user", "修复登录"))
        self.store.append_item(Message("assistant", "测试", [ToolCall("t", "test", {})]))
        self.store.append_item(ToolResult("t", "test", "测试失败"))
        self.store.append_item(Message("user", "继续"))
        self.store.append_entry("run_end", {"status": "finished"})
        self.session_id = self.store.ensure_session_id()
        self.binding = make_compaction_binding(self.session_id, self.store.load().history, 4)

    def test_valid_snapshot_passes_without_writing(self):
        before = self.path.read_bytes()
        self.assertIsNone(check_before_compaction_save(self.store.load(), self.binding))
        self.assertEqual(self.path.read_bytes(), before)

    def test_appended_or_modified_history_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "modified.jsonl"
            content = self.path.read_text(encoding="utf-8")
            path.write_text(content.replace("测试失败", "测试通过"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "历史已变化"):
                check_before_compaction_save(SessionStore(path, "run-b").load(), self.binding)
        self.store.append_item(Message("user", "新的要求"))
        with self.assertRaisesRegex(ValueError, "历史已变化"):
            check_before_compaction_save(self.store.load(), self.binding)

    def test_wrong_session_bad_metadata_and_unsafe_cut_rejected(self):
        for changed in (replace(self.binding, session_id="other"),
                        replace(self.binding, history_count=self.binding.history_count + 1),
                        replace(self.binding, history_count=True),
                        replace(self.binding, cut_index=3)):
            with self.subTest(binding=changed), self.assertRaises(ValueError):
                check_before_compaction_save(self.store.load(), changed)

    def test_pending_call_and_existing_summary_rejected(self):
        self.store.append_item(Message("assistant", "操作", [ToolCall("pending", "test", {})]))
        with self.assertRaisesRegex(ValueError, "未完成"):
            check_before_compaction_save(self.store.load(), self.binding)

    def test_existing_summary_rejected_before_repeat_compaction_is_supported(self):
        record = {"type": "compaction", "run_id": "run-a", "timestamp": "2026-10-29T00:00:00+08:00",
                  "data": {**asdict(self.binding), "summary": "测试失败"}}
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
        with self.assertRaisesRegex(ValueError, "已有摘要"):
            check_before_compaction_save(self.store.load(), self.binding)


if __name__ == "__main__":
    unittest.main()
