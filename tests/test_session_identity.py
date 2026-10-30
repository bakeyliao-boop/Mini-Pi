"""会话固定编号读取规则。"""

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mini_pi.session_records import find_session_id, read_session_records
from mini_pi.models import Message, ToolCall
from mini_pi.session_store import SessionStore


class SessionIdentityTests(unittest.TestCase):
    def test_ensure_identity_appends_once_and_reuses_across_runs(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            store = SessionStore(path, "run-a")
            store.append_entry("run_start", {"status": "running"})
            store.append_item(Message("user", "修复登录"))
            store.append_entry("run_end", {"status": "finished"})
            before = path.read_bytes()
            session_id = store.ensure_session_id()
            after = path.read_bytes()
            self.assertTrue(after.startswith(before))
            self.assertEqual(SessionStore(path, "run-b").ensure_session_id(), session_id)
            self.assertEqual(path.read_bytes(), after)
            loaded = store.load()
            self.assertEqual(loaded.session_id, session_id)
            self.assertEqual(loaded.history, [Message("user", "修复登录")])
            self.assertEqual(sum(record["type"] == "session_identity" for record in loaded.records), 1)

    def test_ensure_rejects_missing_file_and_pending_tool_without_writing(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            store = SessionStore(path, "run-a")
            with self.assertRaises(FileNotFoundError):
                store.ensure_session_id()
            self.assertFalse(path.exists())
            store.append_entry("run_start", {"status": "running"})
            store.append_item(Message("assistant", "调用", [ToolCall("t", "write", {})]))
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "未完成"):
                store.ensure_session_id()
            self.assertEqual(path.read_bytes(), before)

    def test_interrupted_identity_write_reports_failure_and_does_not_hide_invalid_tail(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            store = SessionStore(path, "run-a")
            store.append_item(Message("user", "任务"))
            before = path.read_bytes()
            def partial_write(event_type, data):
                with path.open("a", encoding="utf-8") as file:
                    file.write('{"type":')
                raise OSError("模拟写入中断")
            with patch.object(store, "append_entry", side_effect=partial_write):
                with self.assertRaises(OSError):
                    store.ensure_session_id()
            self.assertTrue(path.read_bytes().startswith(before))
            with self.assertRaisesRegex(ValueError, "无效"):
                store.load()

    def test_load_returns_stable_id_without_adding_it_to_history(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            store = SessionStore(path, "run-a")
            store.append_entry("run_start", {"status": "running"})
            store.append_item(Message("user", "修复登录"))
            store.append_entry("run_end", {"status": "finished"})
            self.assertIsNone(store.load().session_id)
            identity = {"type": "session_identity", "run_id": "run-a",
                        "timestamp": "2026-10-29T00:00:00+08:00", "data": {"session_id": "session-a"}}
            with path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(identity) + "\n")
            for run_id in ("run-a", "run-b"):
                loaded = SessionStore(path, run_id).load()
                self.assertEqual(loaded.session_id, "session-a")
                self.assertEqual(loaded.history, [Message("user", "修复登录")])

    def test_reader_accepts_identity_and_rejects_invalid_identity(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            base = {"run_id": "run-a", "timestamp": "2026-10-29T00:00:00+08:00"}
            records = [dict(base, type="run_start", data={"status": "running"}),
                       dict(base, type="session_identity", data={"session_id": "session-a"})]
            path.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")
            self.assertEqual(read_session_records(path), records)
            records[1]["data"]["session_id"] = " "
            path.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "第 2 行"):
                read_session_records(path)

    def test_reader_rejects_duplicate_identities_even_when_equal(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            identity = {"type": "session_identity", "run_id": "run-a",
                        "timestamp": "2026-10-29T00:00:00+08:00", "data": {"session_id": "session-a"}}
            path.write_text(json.dumps(identity) + "\n" + json.dumps(identity) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "重复"):
                read_session_records(path)

    def test_old_session_and_single_identity(self):
        old = [{"type": "run_start"}, {"type": "message"}]
        self.assertIsNone(find_session_id(old))
        self.assertEqual(find_session_id(old + [{"type": "session_identity", "data": {"session_id": "abc"}},
                                               {"type": "run_end"}]), "abc")

    def test_duplicate_and_malformed_identity_rejected(self):
        valid = {"type": "session_identity", "data": {"session_id": "abc"}}
        for records in ([valid, valid], [None], [{"type": "session_identity", "data": None}],
                        [{"type": "session_identity", "data": {"session_id": " "}}],
                        [{"type": "session_identity", "data": {"session_id": 1}}]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                find_session_id(records)


if __name__ == "__main__":
    unittest.main()
