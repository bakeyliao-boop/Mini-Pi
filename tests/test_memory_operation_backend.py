"""助手准备：MEM-02 操作回执/元数据 I/O；不调用未手敲的 replace/retract。"""

from contextlib import closing
from dataclasses import replace
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from mini_pi.memory.codec import make_entry
from mini_pi.memory.errors import MemoryDataError, MemoryPolicyError
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.operation_codec import (
    dump_receipt, load_receipt, make_replace_receipt, replacement_fingerprint,
)
from mini_pi.memory.sqlite_backend import SQLiteMemoryBackend, _SCHEMA


class MemoryOperationBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "未创建" / "回执 #%.sqlite"
        self.backend = SQLiteMemoryBackend(self.path)
        self.scope = MemoryScope("user-a", "project-a")
        self.first_source = MemorySource(
            "source-1", self.scope, "user", "周末晚上学习", "2026-10-19T08:00:00+08:00",
        )
        self.first_draft = MemoryDraft(
            "学习时段", 0, len(self.first_source.text), "2026-10-19T08:00:00+08:00",
            conditions=(("日期", "周末"), ("时区", "Asia/Shanghai")),
        )
        self.first = make_entry(
            self.scope, self.first_source, self.first_draft,
            written_at="2026-10-19T09:00:00+08:00",
        )
        self.next_source = MemorySource(
            "source-2", self.scope, "user", "周末早上学习", "2026-10-20T08:00:00+08:00",
        )
        self.next_draft = replace(
            self.first_draft, end=len(self.next_source.text), valid_from="2026-11-01T08:00:00+08:00",
        )
        self.next = make_entry(
            self.scope, self.next_source, self.next_draft, version=2,
            written_at="2026-10-20T09:00:00+08:00",
        )
        self.receipt = make_replace_receipt(
            "operation-1", replacement_fingerprint(self.scope, self.next_source, self.next_draft, 1),
            1, self.next, written_at="2026-10-20T09:00:00+08:00",
        )

    def seed_first(self, *, old_schema=False):
        if old_schema:
            self.path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(self.path)) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON")
                for statement in _SCHEMA[:2]:
                    conn.execute(statement)
                self.backend.insert_source(conn, self.first.source)
                self.backend.insert_entry(conn, self.first)
                conn.commit()
        else:
            with self.backend.transaction() as conn:
                self.backend.insert_source(conn, self.first.source)
                self.backend.insert_entry(conn, self.first)

    def write_replacement_io(self, conn):
        self.backend.update_entry(conn, replace(
            self.first, state="superseded", valid_to=self.next.draft.valid_from,
        ))
        self.backend.insert_source(conn, self.next.source)
        self.backend.insert_entry(conn, self.next)
        self.backend.insert_receipt(conn, self.receipt)

    def seed_replacement(self):
        self.seed_first()
        with self.backend.transaction() as conn:
            self.write_replacement_io(conn)

    def tables(self):
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as conn:
            return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    def test_missing_receipt_read_does_not_create_database(self):
        self.assertIsNone(self.backend.read_receipt(self.scope, self.receipt.operation_id))
        self.assertFalse(self.path.parent.exists())

    def test_receipt_roundtrip_and_future_interval_are_persisted(self):
        self.seed_replacement()
        self.assertEqual(self.receipt, self.backend.read_receipt(self.scope, self.receipt.operation_id))
        old = self.backend.read_entry(self.scope, self.first.memory_id)
        self.assertEqual("superseded", old.state)
        self.assertEqual(self.next.draft.valid_from, old.valid_to)
        self.assertEqual(self.next, self.backend.read_entry(self.scope, self.next.memory_id))
        with self.backend.transaction() as conn:
            self.assertEqual(self.receipt, self.backend.get_receipt(conn, self.scope, self.receipt.operation_id))
            versions = self.backend.entries_for_series(
                conn, self.scope, self.first.draft.key, tuple(reversed(self.first.draft.conditions)),
            )
            self.assertEqual([1, 2], [entry.version for entry in versions])

    def test_receipt_can_be_read_from_another_process(self):
        self.seed_replacement()
        script = """import sys
from mini_pi.memory.models import MemoryScope
from mini_pi.memory.operation_codec import dump_receipt
from mini_pi.memory.sqlite_backend import SQLiteMemoryBackend
receipt = SQLiteMemoryBackend(sys.argv[1]).read_receipt(MemoryScope(sys.argv[2], sys.argv[3]), sys.argv[4])
assert receipt is not None
print(dump_receipt(receipt))
"""
        completed = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-c", script, str(self.path),
             self.scope.user_id, self.scope.project_id, self.receipt.operation_id],
            cwd=Path(__file__).resolve().parents[1], capture_output=True,
            text=True, encoding="utf-8", timeout=15, check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(self.receipt, load_receipt(completed.stdout.strip()))

    def test_scope_and_operation_ids_are_parameters(self):
        self.seed_replacement()
        scope = MemoryScope("x' OR 1=1 --", 'p"; DROP TABLE entries; --')
        source = replace(self.next.source, scope=scope)
        entry = make_entry(scope, source, self.next.draft, version=2)
        receipt = make_replace_receipt(
            "op' OR 1=1 --", replacement_fingerprint(scope, source, entry.draft, 1), 1, entry,
        )
        with self.backend.transaction() as conn:
            self.backend.insert_source(conn, source)
            self.backend.insert_entry(conn, entry)
            self.backend.insert_receipt(conn, receipt)
        self.assertEqual(receipt, self.backend.read_receipt(scope, receipt.operation_id))
        self.assertIsNone(self.backend.read_receipt(self.scope, receipt.operation_id))
        self.assertIsNone(self.backend.read_receipt(scope, self.receipt.operation_id))
        self.assertEqual(self.receipt, self.backend.read_receipt(self.scope, self.receipt.operation_id))

    def test_same_operation_id_is_independent_across_both_scope_fields(self):
        self.seed_replacement()
        for scope in (replace(self.scope, user_id="user-b"), replace(self.scope, project_id="project-b")):
            source = replace(self.next.source, scope=scope)
            entry = make_entry(scope, source, self.next.draft, version=2)
            receipt = make_replace_receipt(
                self.receipt.operation_id, replacement_fingerprint(scope, source, entry.draft, 1), 1, entry,
            )
            with self.backend.transaction() as conn:
                self.backend.insert_source(conn, source)
                self.backend.insert_entry(conn, entry)
                self.backend.insert_receipt(conn, receipt)
            self.assertEqual(receipt, self.backend.read_receipt(scope, receipt.operation_id))
        self.assertEqual(self.receipt, self.backend.read_receipt(self.scope, self.receipt.operation_id))

    def test_duplicate_operation_id_is_rejected_without_upsert(self):
        self.seed_replacement()
        with self.assertRaises(sqlite3.IntegrityError):
            with self.backend.transaction() as conn:
                self.backend.insert_receipt(conn, replace(self.receipt, request_hash="f" * 64))
        self.assertEqual(self.receipt, self.backend.read_receipt(self.scope, self.receipt.operation_id))

    def test_receipt_requires_stored_source_and_result(self):
        self.seed_first()
        with self.assertRaises(MemoryDataError):
            with self.backend.transaction() as conn:
                self.backend.insert_receipt(conn, self.receipt)
        with self.backend.transaction() as conn:
            self.backend.insert_source(conn, self.next.source)
        with self.assertRaises(MemoryDataError):
            with self.backend.transaction() as conn:
                self.backend.insert_receipt(conn, self.receipt)
        self.assertIsNone(self.backend.read_receipt(self.scope, self.receipt.operation_id))

    def test_receipt_links_check_series_version_and_replace_source(self):
        self.seed_replacement()
        variants = (
            replace(self.receipt, operation_id="wrong-key", key="其他属性"),
            replace(self.receipt, operation_id="wrong-conditions", conditions=()),
            replace(self.receipt, operation_id="wrong-version", result_version=3),
            replace(self.receipt, operation_id="wrong-id", result_memory_id=self.first.memory_id),
            replace(self.receipt, operation_id="wrong-source", source=self.first.source),
        )
        for receipt in variants:
            with self.subTest(operation_id=receipt.operation_id):
                with self.assertRaises(MemoryDataError):
                    with self.backend.transaction() as conn:
                        self.backend.insert_receipt(conn, receipt)
                self.assertIsNone(self.backend.read_receipt(self.scope, receipt.operation_id))

    def test_retract_receipt_can_reference_separate_stored_operation_source(self):
        self.seed_replacement()
        source = replace(self.first.source, source_id="withdraw-source", text="停止使用这一系列")
        receipt = replace(self.receipt, operation_id="retract-1", action="retract", source=source)
        with self.backend.transaction() as conn:
            self.backend.insert_source(conn, source)
            self.backend.insert_receipt(conn, receipt)
        self.assertEqual(receipt, self.backend.read_receipt(self.scope, receipt.operation_id))
        # 本例只验证回执 I/O，并未自动执行撤回状态迁移。
        self.assertEqual("active", self.backend.read_entry(self.scope, self.next.memory_id).state)

    def test_metadata_update_preserves_receipt_after_result_state_changes(self):
        self.seed_replacement()
        for state, valid_to in (("superseded", "2026-12-01T00:00:00Z"), ("retracted", None)):
            with self.subTest(state=state):
                updated = replace(self.next, state=state, valid_to=valid_to)
                with self.backend.transaction() as conn:
                    self.backend.update_entry(conn, updated)
                self.assertEqual(state, self.backend.read_entry(self.scope, self.next.memory_id).state)
                self.assertEqual(self.receipt, self.backend.read_receipt(self.scope, self.receipt.operation_id))

    def test_metadata_update_rejects_changes_to_immutable_fields(self):
        self.seed_replacement()
        variants = (
            replace(self.next, source=replace(self.next.source, text="甲" * len(self.next.source.text))),
            replace(self.next, draft=replace(self.next.draft, valid_from="2026-11-02T00:00:00Z")),
            replace(self.next, version=3),
            replace(self.next, written_at="2027-01-01T00:00:00Z"),
        )
        for entry in variants:
            with self.subTest(entry=entry):
                with self.assertRaises((MemoryDataError, MemoryPolicyError)):
                    with self.backend.transaction() as conn:
                        self.backend.update_entry(conn, entry)
        self.assertEqual(self.next, self.backend.read_entry(self.scope, self.next.memory_id))

    def test_metadata_update_requires_an_existing_entry_and_matching_scope(self):
        self.seed_replacement()
        source = replace(self.next.source, source_id="not-yet-stored")
        missing = make_entry(self.scope, source, self.next.draft, version=3)
        other_scope = replace(self.scope, user_id="other-user")
        other = make_entry(other_scope, replace(self.next.source, scope=other_scope), self.next.draft, version=2)
        for entry in (missing, other):
            with self.subTest(memory_id=entry.memory_id):
                with self.assertRaises(MemoryDataError):
                    with self.backend.transaction() as conn:
                        self.backend.update_entry(conn, entry)
        self.assertEqual(self.next, self.backend.read_entry(self.scope, self.next.memory_id))

    def test_series_read_has_no_state_or_current_time_filter(self):
        self.seed_replacement()
        with self.backend.transaction() as conn:
            self.backend.update_entry(conn, replace(self.next, state="retracted"))
            separate_source = replace(self.next.source, source_id="different-condition")
            separate = make_entry(self.scope, separate_source, replace(self.next.draft, conditions=()))
            self.backend.insert_source(conn, separate_source)
            self.backend.insert_entry(conn, separate)
            series = self.backend.entries_for_series(conn, self.scope, self.first.draft.key, self.first.draft.conditions)
            self.assertEqual(["superseded", "retracted"], [entry.state for entry in series])
            self.assertEqual([separate], self.backend.entries_for_series(conn, self.scope, self.first.draft.key, ()))
            self.assertEqual([], self.backend.entries_for_series(conn, replace(self.scope, project_id="other"), self.first.draft.key, ()))

    def test_compound_operation_failure_rolls_back_every_row_and_closes(self):
        self.seed_first()
        with self.assertRaisesRegex(RuntimeError, "故意失败"):
            with self.backend.transaction() as conn:
                self.write_replacement_io(conn)
                raise RuntimeError("故意失败")
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")
        self.assertEqual(self.first, self.backend.read_entry(self.scope, self.first.memory_id))
        self.assertIsNone(self.backend.read_entry(self.scope, self.next.memory_id))
        self.assertIsNone(self.backend.read_receipt(self.scope, self.receipt.operation_id))
        with self.backend.transaction() as conn:
            self.assertIsNone(self.backend.get_source(conn, self.scope, self.next.source.source_id))

    def test_old_schema_read_is_readonly_and_does_not_migrate(self):
        self.seed_first(old_schema=True)
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertEqual({"sources", "entries"}, self.tables())
        self.assertIsNone(self.backend.read_receipt(self.scope, self.receipt.operation_id))
        self.assertEqual(self.first, self.backend.read_entry(self.scope, self.first.memory_id))
        self.assertEqual({"sources", "entries"}, self.tables())
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_old_schema_write_migration_and_rows_commit_together(self):
        self.seed_first(old_schema=True)
        with self.backend.transaction() as conn:
            self.write_replacement_io(conn)
        self.assertEqual({"sources", "entries", "operation_receipts"}, self.tables())
        self.assertEqual(self.receipt, self.backend.read_receipt(self.scope, self.receipt.operation_id))

    def test_failed_old_schema_migration_rolls_back_table_and_data(self):
        self.seed_first(old_schema=True)
        with self.assertRaises(RuntimeError):
            with self.backend.transaction() as conn:
                self.write_replacement_io(conn)
                raise RuntimeError("拒绝提交")
        self.assertEqual({"sources", "entries"}, self.tables())
        self.assertEqual([self.first], self.backend.read_entries(self.scope))
        self.assertIsNone(self.backend.read_receipt(self.scope, self.receipt.operation_id))

    def test_corrupt_receipt_json_and_index_columns_fail_explicitly(self):
        self.seed_replacement()
        original_payload = dump_receipt(self.receipt)
        bad_payloads = ("{", '{"scope":{}}', original_payload[:-1] + ',"extra":true}')
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                with self.backend.transaction() as conn:
                    conn.execute(
                        "UPDATE operation_receipts SET payload = ? WHERE user_id = ? AND project_id = ? AND operation_id = ?",
                        (payload, self.scope.user_id, self.scope.project_id, self.receipt.operation_id),
                    )
                with self.assertRaises(MemoryDataError):
                    self.backend.read_receipt(self.scope, self.receipt.operation_id)
        with self.backend.transaction() as conn:
            conn.execute(
                "UPDATE operation_receipts SET payload = ?, request_hash = ? WHERE user_id = ? AND project_id = ? AND operation_id = ?",
                (original_payload, "f" * 64, self.scope.user_id, self.scope.project_id, self.receipt.operation_id),
            )
        with self.assertRaises(MemoryDataError):
            self.backend.read_receipt(self.scope, self.receipt.operation_id)

    def test_corrupt_result_binding_or_source_is_not_trusted(self):
        self.seed_replacement()
        with self.backend.transaction() as conn:
            conn.execute(
                "UPDATE operation_receipts SET result_version = ? WHERE user_id = ? AND project_id = ? AND operation_id = ?",
                (99, self.scope.user_id, self.scope.project_id, self.receipt.operation_id),
            )
        with self.assertRaises(MemoryDataError):
            self.backend.read_receipt(self.scope, self.receipt.operation_id)
        with self.backend.transaction() as conn:
            conn.execute(
                "UPDATE operation_receipts SET result_version = ? WHERE user_id = ? AND project_id = ? AND operation_id = ?",
                (self.receipt.result_version, self.scope.user_id, self.scope.project_id, self.receipt.operation_id),
            )
        self.assertEqual(self.receipt, self.backend.read_receipt(self.scope, self.receipt.operation_id))
        with self.backend.transaction() as conn:
            conn.execute(
                "UPDATE sources SET payload = ? WHERE user_id = ? AND project_id = ? AND source_id = ?",
                ("{}", self.scope.user_id, self.scope.project_id, self.next.source.source_id),
            )
        with self.assertRaises(MemoryDataError):
            self.backend.read_receipt(self.scope, self.receipt.operation_id)

    def test_receipt_payload_scope_cannot_escape_the_scoped_row(self):
        self.seed_replacement()
        other_scope = replace(self.scope, user_id="different-user")
        forged = replace(
            self.receipt, scope=other_scope,
            source=replace(self.receipt.source, scope=other_scope),
        )
        with self.backend.transaction() as conn:
            conn.execute(
                "UPDATE operation_receipts SET payload = ? WHERE user_id = ? AND project_id = ? AND operation_id = ?",
                (dump_receipt(forged), self.scope.user_id, self.scope.project_id, self.receipt.operation_id),
            )
        with self.assertRaises(MemoryDataError):
            self.backend.read_receipt(self.scope, self.receipt.operation_id)
        self.assertIsNone(self.backend.read_receipt(other_scope, self.receipt.operation_id))

    def test_sqlite_foreign_keys_reject_dangling_receipt_even_bypassing_helper(self):
        self.seed_replacement()
        with self.assertRaises(sqlite3.IntegrityError):
            with self.backend.transaction() as conn:
                conn.execute(
                    """INSERT INTO operation_receipts (user_id, project_id, operation_id, action,
                    request_hash, memory_key, conditions, expected_version, result_memory_id,
                    result_version, source_id, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (self.scope.user_id, self.scope.project_id, "bad-fk", "replace", self.receipt.request_hash,
                     self.receipt.key, "[]", 1, "0" * 64, 2, self.receipt.source.source_id, dump_receipt(self.receipt)),
                )
        self.assertIsNone(self.backend.read_receipt(self.scope, "bad-fk"))


if __name__ == "__main__":
    unittest.main()
