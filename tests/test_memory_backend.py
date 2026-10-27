"""助手准备：只验辅助 SQLite/codec，不调用尚未手敲的写入策略。"""

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.memory.codec import (
    candidate_id, dump_entry, dump_source, load_entry, load_source,
    make_entry, normalize_draft, normalize_source,
)
from mini_pi.memory.errors import MemoryDataError, MemoryPolicyError
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.sqlite_backend import SQLiteMemoryBackend


class MemoryBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "尚未创建" / "记忆 空格#%.sqlite"
        self.backend = SQLiteMemoryBackend(self.path)
        self.scope = MemoryScope("用户 A", "项目一")
        self.source = MemorySource(
            "session-1:record-2", self.scope, "user",
            '我说：“周末晚上学习”；不要改测试。\nSQL: \'; DROP TABLE entries; -- %_?\x00',
            "2026-10-19T10:30:00+08:00",
        )
        self.draft = MemoryDraft(
            key="学习'时段_%?", start=0, end=len(self.source.text),
            valid_from="2026-10-18T08:00:00+08:00",
            conditions=(("时区", "Asia/Shanghai"), ("日期", "周末")),
        )
        self.entry = make_entry(
            self.scope, self.source, self.draft, written_at="2026-10-19T12:00:00+08:00",
        )

    def seed(self, entry=None):
        entry = self.entry if entry is None else entry
        with self.backend.transaction() as conn:
            self.backend.insert_source(conn, entry.source)
            self.backend.insert_entry(conn, entry)
        return entry

    def assert_closed(self, conn):
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_lazy_constructor_and_absent_reads_create_nothing(self):
        self.assertFalse(self.path.parent.exists())
        self.assertIsNone(self.backend.read_entry(self.scope, self.entry.memory_id))
        self.assertEqual([], self.backend.read_entries(self.scope))
        self.assertFalse(self.path.parent.exists())

    def test_normalization_preserves_raw_text_and_normalizes_only_representation(self):
        source = normalize_source(self.source)
        draft = normalize_draft(self.draft)
        self.assertEqual(self.source.text, source.text)
        self.assertEqual("2026-10-19T02:30:00.000000+00:00", source.recorded_at)
        self.assertEqual("2026-10-18T00:00:00.000000+00:00", draft.valid_from)
        self.assertEqual(tuple(sorted(self.draft.conditions)), draft.conditions)
        self.assertEqual(source, load_source(dump_source(self.source)))
        self.assertEqual(self.entry, load_entry(dump_entry(self.entry)))

    def test_candidate_id_is_scoped_and_time_independent(self):
        expected = candidate_id(self.scope, self.source, self.draft)
        changed_time = replace(self.draft, valid_from="2027-01-01T00:00:00Z")
        changed_order = replace(self.draft, conditions=tuple(reversed(self.draft.conditions)))
        self.assertEqual(expected, candidate_id(self.scope, self.source, changed_time))
        self.assertEqual(expected, candidate_id(self.scope, self.source, changed_order))
        other_scope = replace(self.scope, user_id="用户 B")
        other_source = replace(self.source, scope=other_scope)
        self.assertNotEqual(expected, candidate_id(other_scope, other_source, self.draft))
        self.assertNotEqual(expected, candidate_id(self.scope, self.source, replace(self.draft, kind="episodic")))

    def test_true_sqlite_roundtrip_includes_special_characters(self):
        self.seed()
        self.assertEqual(self.entry, self.backend.read_entry(self.scope, self.entry.memory_id))
        self.assertEqual([self.entry], self.backend.read_entries(self.scope))
        with self.backend.transaction() as conn:
            self.assertEqual(self.entry.source, self.backend.get_source(conn, self.scope, self.source.source_id))
            self.assertEqual(self.entry, self.backend.find_candidate(conn, self.scope, self.entry.memory_id))
            self.assertEqual(self.entry, self.backend.latest_entry(
                conn, self.scope, self.draft.key, tuple(reversed(self.draft.conditions)),
            ))

    def test_committed_record_can_be_read_by_a_new_process(self):
        self.seed()
        script = """import sys
from mini_pi.memory.codec import dump_entry
from mini_pi.memory.models import MemoryScope
from mini_pi.memory.sqlite_backend import SQLiteMemoryBackend
entry = SQLiteMemoryBackend(sys.argv[1]).read_entry(MemoryScope(sys.argv[2], sys.argv[3]), sys.argv[4])
assert entry is not None
print(dump_entry(entry))
"""
        completed = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-c", script, str(self.path),
             self.scope.user_id, self.scope.project_id, self.entry.memory_id],
            cwd=Path(__file__).resolve().parents[1], capture_output=True,
            text=True, encoding="utf-8", timeout=15, check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.entry, load_entry(completed.stdout.strip()))

    def test_scope_filters_both_user_and_project(self):
        entries = []
        for scope in (self.scope, replace(self.scope, user_id="用户 B"), replace(self.scope, project_id="项目二")):
            source = replace(self.source, scope=scope)
            entry = make_entry(scope, source, self.draft)
            entries.append(self.seed(entry))
        for entry in entries:
            self.assertEqual([entry], self.backend.read_entries(entry.scope))
            for other in entries:
                if other.scope != entry.scope:
                    self.assertIsNone(self.backend.read_entry(other.scope, entry.memory_id))

    def test_scope_and_key_values_are_sql_parameters(self):
        scope = MemoryScope("x' OR 1=1 --", 'p"; DROP TABLE sources; --')
        source = replace(self.source, scope=scope, source_id="x' OR 1=1 --")
        entry = make_entry(scope, source, self.draft)
        self.seed(entry)
        self.assertEqual([entry], self.backend.read_entries(scope))
        self.assertEqual([], self.backend.read_entries(self.scope))
        with self.backend.transaction() as conn:
            self.assertIsNone(self.backend.find_candidate(conn, self.scope, "' OR 1=1 --"))
            self.assertIsNone(self.backend.get_source(conn, self.scope, "' OR 1=1 --"))

    def test_exception_rolls_back_source_and_entry_and_closes_connection(self):
        self.seed()
        source = replace(self.source, source_id="new-source")
        entry = make_entry(self.scope, source, replace(self.draft, key="另一个键"))
        with self.assertRaisesRegex(RuntimeError, "停止"):
            with self.backend.transaction() as conn:
                self.backend.insert_source(conn, source)
                self.backend.insert_entry(conn, entry)
                raise RuntimeError("停止")
        self.assert_closed(conn)
        with self.backend.transaction() as conn:
            self.assertIsNone(self.backend.get_source(conn, self.scope, source.source_id))
            self.assertIsNone(self.backend.find_candidate(conn, self.scope, entry.memory_id))
        self.assertEqual([self.entry], self.backend.read_entries(self.scope))

    def test_first_transaction_rollback_leaves_zero_partial_rows(self):
        with self.assertRaises(RuntimeError):
            with self.backend.transaction() as conn:
                self.backend.insert_source(conn, self.source)
                self.backend.insert_entry(conn, self.entry)
                raise RuntimeError("回滚")
        self.assert_closed(conn)
        self.assertEqual([], self.backend.read_entries(self.scope))
        self.seed()
        self.assertEqual([self.entry], self.backend.read_entries(self.scope))

    def test_cancel_signal_as_base_exception_rolls_back_and_closes(self):
        self.seed()
        source = replace(self.source, source_id="cancelled-source")
        with self.assertRaises(asyncio.CancelledError):
            with self.backend.transaction() as conn:
                self.backend.insert_source(conn, source)
                raise asyncio.CancelledError()
        self.assert_closed(conn)
        with self.backend.transaction() as conn:
            self.assertIsNone(self.backend.get_source(conn, self.scope, source.source_id))

    def test_duplicate_inserts_do_not_upsert_or_reactivate(self):
        retracted = replace(self.entry, state="retracted")
        self.seed(retracted)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.backend.transaction() as conn:
                self.backend.insert_entry(conn, self.entry)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.backend.transaction() as conn:
                self.backend.insert_source(conn, replace(self.entry.source, text="被覆盖的原文"))
        self.assertEqual(retracted, self.backend.read_entry(self.scope, retracted.memory_id))

    def test_version_collision_rolls_back_new_source(self):
        self.seed()
        other_source = replace(self.source, source_id="conflicting-source")
        other_entry = make_entry(self.scope, other_source, self.draft)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.backend.transaction() as conn:
                self.backend.insert_source(conn, other_source)
                self.backend.insert_entry(conn, other_entry)
        with self.backend.transaction() as conn:
            self.assertIsNone(self.backend.get_source(conn, self.scope, other_source.source_id))
        self.assertEqual([self.entry], self.backend.read_entries(self.scope))

    def test_begin_lock_failure_closes_new_connection(self):
        self.seed()
        real_connect = sqlite3.connect
        connections = []
        def tracked_connect(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            connections.append(conn)
            return conn
        with self.backend.transaction():
            with patch("mini_pi.memory.sqlite_backend.sqlite3.connect", side_effect=tracked_connect):
                with self.assertRaises(sqlite3.OperationalError):
                    with self.backend.transaction():
                        self.fail("已有写锁时不应进入第二个事务")
        self.assertEqual(1, len(connections))
        self.assert_closed(connections[0])
        self.assertEqual([self.entry], self.backend.read_entries(self.scope))

    def test_latest_entry_is_storage_order_not_active_selection(self):
        first = replace(self.entry, state="superseded")
        self.seed(first)
        source = replace(self.source, source_id="v2-source")
        second = make_entry(self.scope, source, self.draft, version=2, state="retracted")
        self.seed(second)
        with self.backend.transaction() as conn:
            self.assertEqual(second, self.backend.latest_entry(conn, self.scope, self.draft.key, self.draft.conditions))

    def test_foreign_source_must_exist_and_match_exactly(self):
        with self.assertRaises(MemoryDataError):
            with self.backend.transaction() as conn:
                self.backend.insert_entry(conn, self.entry)
        self.seed()
        changed = replace(self.entry, source=replace(self.entry.source, text=self.entry.source.text + "改写"))
        with self.assertRaises(MemoryDataError):
            with self.backend.transaction() as conn:
                self.backend.insert_entry(conn, changed)
        self.assertEqual([self.entry], self.backend.read_entries(self.scope))

    def test_malformed_json_and_invalid_shapes_fail_explicitly(self):
        for payload in ('{', '[]', '{"a":1,"a":2}', '{"a":NaN}'):
            with self.subTest(payload=payload):
                with self.assertRaises(MemoryDataError):
                    load_entry(payload)
        for name, value in (("version", True), ("written_at", None), ("state", "unknown"), ("memory_id", "wrong")):
            payload = json.loads(dump_entry(self.entry))
            payload[name] = value
            with self.subTest(name=name):
                with self.assertRaises(MemoryDataError):
                    load_entry(json.dumps(payload))

    def test_corrupt_saved_payload_is_not_silently_skipped(self):
        self.seed()
        with self.backend.transaction() as conn:
            conn.execute(
                "UPDATE entries SET payload = ? WHERE user_id = ? AND project_id = ? AND memory_id = ?",
                ("{损坏", self.scope.user_id, self.scope.project_id, self.entry.memory_id),
            )
        with self.assertRaises(MemoryDataError):
            self.backend.read_entries(self.scope)
        with self.assertRaises(MemoryDataError):
            self.backend.read_entry(self.scope, self.entry.memory_id)

    def test_payload_cannot_escape_scope_or_disagree_with_source(self):
        self.seed()
        with self.backend.transaction() as conn:
            conn.execute(
                "UPDATE entries SET state = ? WHERE user_id = ? AND project_id = ? AND memory_id = ?",
                ("retracted", self.scope.user_id, self.scope.project_id, self.entry.memory_id),
            )
        with self.assertRaises(MemoryDataError):
            self.backend.read_entry(self.scope, self.entry.memory_id)

    def test_reader_and_writer_connections_are_closed_after_return_and_failure(self):
        real_connect = sqlite3.connect
        connections = []
        def tracked_connect(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            connections.append(conn)
            return conn
        with patch("mini_pi.memory.sqlite_backend.sqlite3.connect", side_effect=tracked_connect):
            self.seed()
            self.backend.read_entry(self.scope, self.entry.memory_id)
            self.backend.read_entries(self.scope)
            with self.backend.transaction() as conn:
                conn.execute(
                    "UPDATE sources SET payload = ? WHERE user_id = ? AND project_id = ? AND source_id = ?",
                    ('{}', self.scope.user_id, self.scope.project_id, self.source.source_id),
                )
            with self.assertRaises(MemoryDataError):
                self.backend.read_entry(self.scope, self.entry.memory_id)
        self.assertEqual(5, len(connections))
        for conn in connections:
            self.assert_closed(conn)

    def test_non_sqlite_database_errors_are_explicit(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"not a sqlite database")
        with self.assertRaises(MemoryDataError):
            self.backend.read_entries(self.scope)

    def test_invalid_time_and_condition_representation_rejected_without_io(self):
        with self.assertRaises(MemoryPolicyError):
            normalize_source(replace(self.source, recorded_at="2026-10-19T12:00:00"))
        with self.assertRaises(MemoryPolicyError):
            normalize_draft(replace(self.draft, conditions=(("same", "a"), ("same", "b"))))
        self.assertFalse(self.path.parent.exists())


if __name__ == "__main__":
    unittest.main()
