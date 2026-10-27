"""MEM-02 replace：助手准备的真实 SQLite 正常场景与反例。

只验证显式替换；未来区间采用手工检查，不宣称检索能力已实现。
retracted 状态由公开 backend 预置，不代表撤回 API 已实现或验收。
"""

from contextlib import closing, contextmanager
from dataclasses import asdict, replace
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from mini_pi.memory.errors import MemoryConflict, MemoryPolicyError
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.sqlite_backend import SQLiteMemoryBackend
from mini_pi.memory.store import MemoryStore


class ReceiptInsertFailure(RuntimeError):
    """受控异常，不能当成真实磁盘或断电故障。"""


class FailAfterRealReceiptInsert(SQLiteMemoryBackend):
    """保留真实事务与插入，在回执实际可读后主动抛异常。"""

    def __init__(self, path):
        super().__init__(path)
        self.connections = []

    @contextmanager
    def transaction(self):
        with super().transaction() as conn:
            self.connections.append(conn)
            yield conn

    def insert_receipt(self, conn, receipt):
        super().insert_receipt(conn, receipt)
        self.inserted_receipt = super().get_receipt(conn, receipt.scope, receipt.operation_id)
        self.series_at_failure = super().entries_for_series(
            conn, receipt.scope, receipt.key, receipt.conditions,
        )
        self.new_source_at_failure = super().get_source(
            conn, receipt.scope, receipt.source.source_id,
        )
        raise ReceiptInsertFailure("controlled failure after real receipt insert")


class MemoryReplaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_memory_replace_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "memory" / "state.sqlite3"
        self.scope = MemoryScope("user_A", "project_A")
        self.source1 = MemorySource(
            "message_001", self.scope, "user", "我更喜欢晚上学习。",
            "2026-10-19T13:00:00+08:00",
        )
        self.draft1 = MemoryDraft(
            "study_time", 0, len(self.source1.text),
            "2026-10-19T13:00:00+08:00",
        )
        self.source2 = replace(
            self.source1, source_id="message_002", text="我更喜欢早上学习。",
            recorded_at="2026-10-20T13:00:00+08:00",
        )
        self.draft2 = replace(
            self.draft1, end=len(self.source2.text),
            valid_from="2026-11-01T13:00:00+08:00",
        )
        self.source3 = replace(
            self.source2, source_id="message_003", text="我更喜欢中午学习。",
            recorded_at="2026-11-02T13:00:00+08:00",
        )
        self.draft3 = replace(
            self.draft2, end=len(self.source3.text),
            valid_from="2026-12-01T13:00:00+08:00",
        )
        self.store = MemoryStore(self.path)

    def backend(self):
        return SQLiteMemoryBackend(self.path)

    def seed_v1(self):
        # MEM-01 已实现；只通过公开 remember 创建首次记忆。
        return self.store.remember(self.scope, self.source1, self.draft1)

    def write_v2(self, operation_id="replace_002"):
        return self.store.replace(
            self.scope, self.source2, self.draft2,
            expected_version=1, operation_id=operation_id,
        )

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def source_in_database(self, source_id, scope=None):
        backend = self.backend()
        with backend.transaction() as conn:
            return backend.get_source(conn, scope or self.scope, source_id)

    def receipt(self, operation_id="replace_002", scope=None):
        return self.backend().read_receipt(scope or self.scope, operation_id)

    def mark_retracted_fixture(self, entry):
        """仅预置数据库状态；没有调用或验收 retract API。"""
        retracted = replace(entry, state="retracted")
        backend = self.backend()
        with backend.transaction() as conn:
            backend.update_entry(conn, retracted)
        return retracted

    def invalid_requests(self):
        cases = []
        for expected in (True, False, 0, -1, "1", 1.0, None):
            cases.append(("expected", self.scope, self.source2, self.draft2, expected, "new_op"))
        for operation_id in ("", " ", None, 12):
            cases.append(("operation_id", self.scope, self.source2, self.draft2, 1, operation_id))
        cases.extend([
            ("wrong trusted user", replace(self.scope, user_id="user_B"), self.source2, self.draft2, 1, "new_op"),
            ("wrong source project", self.scope,
             replace(self.source2, scope=replace(self.scope, project_id="project_B")), self.draft2, 1, "new_op"),
            ("assistant source", self.scope, replace(self.source2, role="assistant"), self.draft2, 1, "new_op"),
            ("tool semantic source", self.scope, replace(self.source2, role="tool"), self.draft2, 1, "new_op"),
            ("naive source time", self.scope,
             replace(self.source2, recorded_at="2026-10-20T13:00:00"), self.draft2, 1, "new_op"),
            ("invalid valid time", self.scope, self.source2,
             replace(self.draft2, valid_from="invalid time"), 1, "new_op"),
            ("unsupported kind", self.scope, self.source2,
             replace(self.draft2, kind="preference"), 1, "new_op"),
        ])
        return cases

    def test_replace_closes_v1_preserves_its_source_and_commits_v2_with_receipt(self):
        v1 = self.seed_v1()
        v2 = self.write_v2()
        historical = self.store.get(self.scope, v1.memory_id)
        self.assertEqual(historical, replace(v1, state="superseded", valid_to=v2.draft.valid_from))
        self.assertEqual(self.source_in_database(self.source1.source_id), v1.source)
        self.assertEqual(self.source_in_database(self.source2.source_id), v2.source)
        self.assertEqual((v2.version, v2.state, v2.valid_to), (2, "active", None))
        self.assertEqual(v2.text, "我更喜欢早上学习。")
        self.assertNotEqual(v2.memory_id, v1.memory_id)
        self.assertEqual(len(self.backend().read_entries(self.scope)), 2)
        receipt = self.receipt()
        self.assertIsNotNone(receipt)
        self.assertEqual((receipt.action, receipt.operation_id, receipt.expected_version),
                         ("replace", "replace_002", 1))
        self.assertEqual((receipt.result_memory_id, receipt.result_version, receipt.source),
                         (v2.memory_id, 2, v2.source))

    def test_future_v2_leaves_v1_applicable_until_the_half_open_boundary(self):
        v1 = self.seed_v1()
        v2 = self.write_v2()
        historical = self.store.get(self.scope, v1.memory_id)

        def manually_inside(entry, instant):
            return (datetime.fromisoformat(entry.draft.valid_from) <= instant
                    and (entry.valid_to is None or instant < datetime.fromisoformat(entry.valid_to)))

        before = datetime.fromisoformat("2026-10-25T13:00:00+08:00")
        boundary = datetime.fromisoformat("2026-11-01T13:00:00+08:00")
        self.assertEqual(historical.state, "superseded")
        self.assertTrue(manually_inside(historical, before))
        self.assertFalse(manually_inside(v2, before))
        self.assertFalse(manually_inside(historical, boundary))
        self.assertTrue(manually_inside(v2, boundary))

    def test_same_operation_replay_precedes_cas_and_writes_nothing(self):
        self.seed_v1()
        v2 = self.write_v2()
        original_receipt = self.receipt()
        before = self.snapshot()
        # expected=1 已不是 head，但相同操作必须先由回执重放。
        replay = MemoryStore(self.path).replace(
            self.scope, self.source2, self.draft2,
            expected_version=1, operation_id="replace_002",
        )
        self.assertEqual(replay, v2)
        self.assertEqual(self.receipt(), original_receipt)
        self.assertEqual(len(self.backend().read_entries(self.scope)), 2)
        self.assertEqual(self.snapshot(), before)

    def test_old_operation_after_v3_returns_its_current_superseded_entry(self):
        self.seed_v1()
        v2 = self.write_v2()
        v3 = self.store.replace(
            self.scope, self.source3, self.draft3,
            expected_version=2, operation_id="replace_003",
        )
        current_v2 = self.store.get(self.scope, v2.memory_id)
        self.assertEqual(current_v2, replace(v2, state="superseded", valid_to=v3.draft.valid_from))
        before = self.snapshot()
        replay = self.write_v2()
        self.assertEqual(replay, current_v2)
        self.assertEqual((replay.state, replay.version, replay.written_at),
                         ("superseded", 2, v2.written_at))
        self.assertEqual(len(self.backend().read_entries(self.scope)), 3)
        self.assertEqual(self.snapshot(), before)

    def test_old_operation_returns_a_preseeded_retracted_entry_without_reactivation(self):
        self.seed_v1()
        v2 = self.write_v2()
        retracted = self.mark_retracted_fixture(v2)
        before = self.snapshot()
        self.assertEqual(self.write_v2(), retracted)
        self.assertEqual(self.store.get(self.scope, v2.memory_id).state, "retracted")
        self.assertEqual(self.snapshot(), before)

    def test_same_operation_id_with_changed_legal_request_conflicts_without_mutation(self):
        self.seed_v1()
        self.write_v2()
        before = self.snapshot()
        cases = [
            ("source id", replace(self.source2, source_id="message_009"), self.draft2, 1),
            ("raw text", replace(self.source2, text="我现在更喜欢其他时间学习。"), self.draft2, 1),
            ("source time", replace(self.source2, recorded_at="2026-10-21T13:00:00+08:00"), self.draft2, 1),
            ("valid_from", self.source2, replace(self.draft2, valid_from="2026-11-02T13:00:00+08:00"), 1),
            ("expected", self.source2, self.draft2, 2),
            ("kind", self.source2, replace(self.draft2, kind="procedural"), 1),
            ("key", self.source2, replace(self.draft2, key="study_method"), 1),
            ("conditions", self.source2, replace(self.draft2, conditions=(("place", "home"),)), 1),
        ]
        for label, source, draft, expected in cases:
            with self.subTest(changed=label):
                with self.assertRaises(MemoryConflict):
                    self.store.replace(
                        self.scope, source, replace(draft, end=len(source.text)),
                        expected_version=expected, operation_id="replace_002",
                    )
                self.assertEqual(self.snapshot(), before)

    def test_bad_inputs_are_rejected_before_creating_any_database(self):
        for label, scope, source, draft, expected, operation_id in self.invalid_requests():
            with self.subTest(case=label, expected=expected, operation_id=operation_id):
                with self.assertRaises(MemoryPolicyError):
                    self.store.replace(scope, source, draft, expected_version=expected, operation_id=operation_id)
                self.assertFalse(self.path.parent.exists())

    def test_bad_inputs_on_existing_database_add_no_sources_entries_or_receipts(self):
        v1 = self.seed_v1()
        before = self.snapshot()
        for label, scope, source, draft, expected, operation_id in self.invalid_requests():
            with self.subTest(case=label, expected=expected, operation_id=operation_id):
                with self.assertRaises(MemoryPolicyError):
                    self.store.replace(scope, source, draft, expected_version=expected, operation_id=operation_id)
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.backend().read_entries(self.scope), [v1])
        self.assertIsNone(self.source_in_database(self.source2.source_id))
        self.assertIsNone(self.receipt("new_op"))

    def test_foreign_user_or_project_cannot_replace_the_original_series(self):
        v1 = self.seed_v1()
        before = self.snapshot()
        for scope in (replace(self.scope, user_id="user_B"), replace(self.scope, project_id="project_B")):
            with self.subTest(scope=scope):
                with self.assertRaises(MemoryPolicyError):
                    self.store.replace(scope, self.source2, self.draft2, expected_version=1, operation_id="foreign_op")
                # 身份匹配新范围仍找不到该范围的系列，不能跨范围借用 v1。
                with self.assertRaises(MemoryConflict):
                    self.store.replace(scope, replace(self.source2, scope=scope), self.draft2,
                                       expected_version=1, operation_id="foreign_op")
                self.assertEqual(self.backend().read_entries(scope), [])
                self.assertIsNone(self.receipt("foreign_op", scope))
                self.assertIsNone(self.source_in_database(self.source2.source_id, scope))
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.store.get(self.scope, v1.memory_id), v1)

    def test_cas_uses_the_latest_persisted_version_even_when_v2_is_future_effective(self):
        v1 = self.seed_v1()
        v2 = self.write_v2()
        self.assertEqual(self.store.get(self.scope, v1.memory_id).valid_to, v2.draft.valid_from)
        before = self.snapshot()
        with self.assertRaises(MemoryConflict):
            self.store.replace(self.scope, self.source3, self.draft3,
                               expected_version=1, operation_id="stale_op")
        self.assertIsNone(self.source_in_database(self.source3.source_id))
        self.assertIsNone(self.receipt("stale_op"))
        self.assertEqual(self.snapshot(), before)

    def test_new_valid_from_must_be_strictly_after_head_and_cannot_insert_history(self):
        self.seed_v1()
        self.write_v2()
        before = self.snapshot()
        for valid_from in ("2026-11-01T13:00:00+08:00", "2026-10-25T13:00:00+08:00",
                           "2026-10-19T13:00:00+08:00", "2026-10-01T13:00:00+08:00"):
            with self.subTest(valid_from=valid_from):
                with self.assertRaises(MemoryConflict):
                    self.store.replace(self.scope, self.source3, replace(self.draft3, valid_from=valid_from),
                                       expected_version=2, operation_id="bad_interval_op")
                self.assertEqual(self.snapshot(), before)

    def test_kind_source_identity_and_old_candidate_cannot_be_reused_as_a_new_version(self):
        self.seed_v1()
        before = self.snapshot()
        cases = (
            ("kind", self.source2, replace(self.draft2, kind="procedural")),
            ("old candidate", self.source1, replace(self.draft1, valid_from=self.draft2.valid_from)),
            ("changed immutable source", replace(self.source1, text="同编号的不同原话。"), self.draft2),
        )
        for label, source, draft in cases:
            with self.subTest(case=label):
                with self.assertRaises(MemoryConflict):
                    self.store.replace(self.scope, source, replace(draft, end=len(source.text)),
                                       expected_version=1, operation_id="invalid_definition_op")
                self.assertEqual(self.snapshot(), before)

    def test_preseeded_retracted_head_rejects_a_new_operation(self):
        v1 = self.mark_retracted_fixture(self.seed_v1())
        before = self.snapshot()
        with self.assertRaises(MemoryConflict):
            self.write_v2(operation_id="new_after_retracted")
        self.assertEqual(self.store.get(self.scope, v1.memory_id), v1)
        self.assertIsNone(self.source_in_database(self.source2.source_id))
        self.assertIsNone(self.receipt("new_after_retracted"))
        self.assertEqual(self.snapshot(), before)

    def test_failure_after_real_receipt_insert_rolls_back_every_write_and_releases_resources(self):
        v1 = self.seed_v1()
        before = self.snapshot()
        failing_backend = FailAfterRealReceiptInsert(self.path)
        self.store._backend = failing_backend
        with self.assertRaisesRegex(ReceiptInsertFailure, "controlled failure after real receipt insert"):
            self.write_v2()
        self.assertEqual(failing_backend.inserted_receipt.result_version, 2)
        self.assertEqual(len(failing_backend.series_at_failure), 2)
        self.assertEqual(failing_backend.new_source_at_failure.text, self.source2.text)
        self.assertEqual(len(failing_backend.connections), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            failing_backend.connections[0].execute("SELECT 1")
        with closing(sqlite3.connect(self.path, isolation_level=None, timeout=0)) as probe:
            try:
                probe.execute("BEGIN IMMEDIATE")
                self.assertTrue(probe.in_transaction)
            finally:
                if probe.in_transaction:
                    probe.rollback()
        self.assertEqual(self.backend().read_entries(self.scope), [v1])
        self.assertEqual(self.backend().read_entry(self.scope, v1.memory_id), v1)
        self.assertIsNone(self.source_in_database(self.source2.source_id))
        self.assertIsNone(self.receipt())
        self.assertEqual(self.snapshot(), before)

    def test_new_instance_and_new_process_read_the_committed_entry_and_receipt(self):
        self.seed_v1()
        v2 = self.write_v2()
        receipt = self.receipt()
        self.assertEqual(MemoryStore(self.path).get(self.scope, v2.memory_id), v2)
        script = """
from dataclasses import asdict
import json
import sys
from mini_pi.memory.models import MemoryScope
from mini_pi.memory.sqlite_backend import SQLiteMemoryBackend
from mini_pi.memory.store import MemoryStore
scope = MemoryScope(sys.argv[2], sys.argv[3])
entry = MemoryStore(sys.argv[1]).get(scope, sys.argv[4])
receipt = SQLiteMemoryBackend(sys.argv[1]).read_receipt(scope, sys.argv[5])
if entry is None or receipt is None:
    raise SystemExit("committed entry or receipt missing")
print(json.dumps({"entry": asdict(entry), "receipt": asdict(receipt)}, ensure_ascii=False))
"""
        result = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-c", script, str(self.path),
             self.scope.user_id, self.scope.project_id, v2.memory_id, "replace_002"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True,
            text=True, encoding="utf-8", timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = json.loads(json.dumps({"entry": asdict(v2), "receipt": asdict(receipt)}))
        self.assertEqual(json.loads(result.stdout), expected)

    def test_operation_ids_are_independent_in_different_user_and_project_scopes(self):
        scopes = (self.scope, replace(self.scope, user_id="user_B"), replace(self.scope, project_id="project_B"))
        results = []
        for scope in scopes:
            with self.subTest(scope=scope):
                self.store.remember(scope, replace(self.source1, scope=scope), self.draft1)
                entry = self.store.replace(scope, replace(self.source2, scope=scope), self.draft2,
                                           expected_version=1, operation_id="shared_op")
                receipt = self.receipt("shared_op", scope)
                self.assertEqual((receipt.scope, receipt.result_memory_id), (scope, entry.memory_id))
                self.assertEqual(entry.version, 2)
                self.assertEqual(len(self.backend().read_entries(scope)), 2)
                results.append(entry)
        self.assertEqual(len({entry.memory_id for entry in results}), 3)
        for entry in results:
            for other_scope in scopes:
                if other_scope != entry.scope:
                    self.assertIsNone(self.store.get(other_scope, entry.memory_id))


if __name__ == "__main__":
    unittest.main()
