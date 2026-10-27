"""助手准备：撤回辅助测试与完整行为反例；占位阶段如实报红。"""

from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from mini_pi.memory.codec import make_entry
from mini_pi.memory.errors import MemoryConflict, MemoryPolicyError
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.operation_codec import (
    dump_receipt, load_receipt, make_retract_receipt, retraction_fingerprint,
    validate_retraction_shape,
)
from mini_pi.memory.sqlite_backend import SQLiteMemoryBackend
from mini_pi.memory.store import MemoryStore
from tests.test_memory_replace import FailAfterRealReceiptInsert, ReceiptInsertFailure


class RetractionHelperTests(unittest.TestCase):
    def setUp(self):
        self.scope = MemoryScope("A", "Pi")
        self.source = MemorySource("withdraw", self.scope, "user", "不要再记住学习时间。",
                                   "2026-10-19T18:00:00+08:00")

    def fingerprint(self, **changes):
        args = dict(scope=self.scope, source=self.source, key="study_time",
                    conditions=(("day", "weekday"), ("tz", "Asia/Shanghai")), expected_version=2)
        args.update(changes)
        return retraction_fingerprint(**args)

    def test_equivalent_times_and_conditions_have_same_fingerprint(self):
        self.assertEqual(self.fingerprint(), self.fingerprint(
            source=replace(self.source, recorded_at="2026-10-19T10:00:00Z"),
            conditions=(("tz", "Asia/Shanghai"), ("day", "weekday"))))

    def test_fingerprint_covers_full_request(self):
        changes = [dict(key="other"), dict(conditions=()), dict(expected_version=1)]
        for field, value in [("source_id", "other"), ("text", "不要记住其他内容。"),
                             ("recorded_at", "2026-10-19T18:01:00+08:00"), ("role", "tool")]:
            changes.append(dict(source=replace(self.source, **{field: value})))
        other = MemoryScope("B", "Pi")
        changes.append(dict(scope=other, source=replace(self.source, scope=other)))
        for change in changes:
            with self.subTest(change=change):
                self.assertNotEqual(self.fingerprint(), self.fingerprint(**change))

    def test_bad_shapes_rejected(self):
        for key, conditions, expected, op in [
            ("", (), 1, "op"), ("key", [], 1, "op"),
            ("key", (("day", "a"), ("day", "b")), 1, "op"),
            ("key", (), True, "op"), ("key", (), 0, "op"), ("key", (), 1, " "),
        ]:
            with self.subTest(key=key, conditions=conditions, expected=expected, op=op):
                with self.assertRaises(MemoryPolicyError):
                    validate_retraction_shape(self.scope, self.source, key, conditions, expected, op)
        with self.assertRaises(MemoryPolicyError):
            validate_retraction_shape(self.scope, replace(self.source, text=" "), "key", (), 1, "op")

    def test_shape_helper_does_not_hide_role_or_scope_admission(self):
        # 来源准入属于学习者的核心决策；格式辅助不能替代它。
        validate_retraction_shape(self.scope, replace(self.source, role="tool"), "key", (), 1, "op")
        validate_retraction_shape(self.scope, replace(self.source, scope=MemoryScope("B", "Pi")),
                                  "key", (), 1, "op")

    def test_receipt_keeps_control_source_separate_and_does_not_mutate_entry(self):
        fact = replace(self.source, source_id="fact", text="早上学习。")
        entry = make_entry(self.scope, fact, MemoryDraft("study_time", 0, len(fact.text),
                           fact.recorded_at), version=2)
        receipt = make_retract_receipt("op", self.fingerprint(), 2, self.source, entry)
        self.assertEqual(load_receipt(dump_receipt(receipt)), receipt)
        self.assertEqual((receipt.action, receipt.result_version, receipt.source.text),
                         ("retract", 2, self.source.text))
        self.assertEqual((entry.state, entry.source.text), ("active", fact.text))


class MemoryRetractTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_memory_retract_")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "db" / "memory.sqlite3"
        self.scope = MemoryScope("A", "Pi")
        self.store = MemoryStore(self.path)
        self.source = MemorySource("one", self.scope, "user", "晚上学习。", "2026-10-19T09:00:00+08:00")
        self.draft = MemoryDraft("study_time", 0, len(self.source.text), self.source.recorded_at)
        self.control = replace(self.source, source_id="withdraw", text="不要再记住学习时间。",
                               recorded_at="2026-10-19T18:00:00+08:00")
        self.backend = SQLiteMemoryBackend(self.path)

    def seed(self):
        first = self.store.remember(self.scope, self.source, self.draft)
        source2 = replace(self.source, source_id="two", text="明天起早上学习。")
        draft2 = replace(self.draft, end=len(source2.text), valid_from="2026-10-20T00:00:00+08:00")
        second = self.store.replace(self.scope, source2, draft2, expected_version=1, operation_id="update")
        return first, second

    def withdraw(self, **changes):
        args = dict(scope=self.scope, source=self.control, key="study_time", conditions=(),
                    expected_version=2, operation_id="withdraw_op")
        args.update(changes)
        return self.store.retract(**args)

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.path.parent.glob("*") if p.is_file()}

    def test_all_versions_retracted_without_new_fact_or_interval_changes(self):
        first, second = self.seed()
        old_first = self.store.get(self.scope, first.memory_id)
        result = self.withdraw()
        self.assertEqual(result, replace(second, state="retracted"))
        self.assertEqual(self.backend.read_entries(self.scope),
                         [replace(old_first, state="retracted"), result])
        receipt = self.backend.read_receipt(self.scope, "withdraw_op")
        self.assertEqual((receipt.action, receipt.result_version, receipt.source.text),
                         ("retract", 2, self.control.text))
        self.assertEqual(result.source, second.source)
        self.assertIsNone(result.valid_to)  # 未来版本也撤回，不构造负时间区间。

    def test_same_operation_replay_does_not_write_again(self):
        self.seed()
        result = self.withdraw()
        before = self.snapshot()
        self.assertEqual(self.withdraw(), result)
        self.assertEqual(self.snapshot(), before)

    def test_same_operation_cannot_change_request_or_reuse_replace_id(self):
        self.seed()
        self.withdraw()
        before = self.snapshot()
        for change in [dict(key="other"), dict(expected_version=1),
                       dict(source=replace(self.control, text="另一条撤回指令。")),
                       dict(conditions=(("day", "weekend"),)), dict(operation_id="update")]:
            with self.subTest(change=change), self.assertRaises(MemoryConflict):
                self.withdraw(**change)
        self.assertEqual(self.snapshot(), before)

    def test_stale_version_missing_series_and_new_operation_after_retract_conflict(self):
        self.seed()
        before = self.snapshot()
        for change in [dict(expected_version=1), dict(key="missing"),
                       dict(conditions=(("day", "missing"),))]:
            with self.subTest(change=change), self.assertRaises(MemoryConflict):
                self.withdraw(**change)
        self.assertEqual(self.snapshot(), before)
        self.withdraw()
        before = self.snapshot()
        with self.assertRaises(MemoryConflict):
            self.withdraw(operation_id="new_op")
        self.assertEqual(self.snapshot(), before)

    def test_invalid_input_rejected_before_database_creation(self):
        for change in [dict(source=replace(self.control, role="tool")),
                       dict(source=replace(self.control, role="assistant")),
                       dict(source=replace(self.control, scope=MemoryScope("B", "Pi"))),
                       dict(key=""), dict(expected_version=True), dict(operation_id=" ")]:
            with self.subTest(change=change), self.assertRaises(MemoryPolicyError):
                self.withdraw(**change)
            self.assertFalse(self.path.parent.exists())

    def test_other_conditions_users_and_projects_unchanged(self):
        self.seed()
        untouched = []
        for scope, conditions in [(self.scope, (("day", "weekend"),)),
                                   (MemoryScope("B", "Pi"), ()), (MemoryScope("A", "Other"), ())]:
            untouched.append(self.store.remember(scope, replace(self.source, scope=scope),
                                               replace(self.draft, conditions=conditions)))
        self.withdraw()
        for entry in untouched:
            self.assertEqual(self.store.get(entry.scope, entry.memory_id), entry)

    def test_existing_source_cannot_be_rewritten_and_identical_source_can_be_reused(self):
        self.seed()
        with self.backend.transaction() as conn:
            self.backend.insert_source(conn, replace(self.control, recorded_at="2026-10-19T10:00:00Z"))
        before = self.snapshot()
        with self.assertRaises(MemoryConflict):
            self.withdraw(source=replace(self.control, text="同编号改写。"))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.withdraw().state, "retracted")

    def test_failure_after_receipt_insert_rolls_back_entire_series_and_control_source(self):
        self.seed()
        before = self.snapshot()
        backend = FailAfterRealReceiptInsert(self.path)
        self.store._backend = backend
        with self.assertRaises(ReceiptInsertFailure):
            self.withdraw()
        self.assertEqual([e.state for e in backend.series_at_failure], ["retracted", "retracted"])
        self.assertEqual(backend.inserted_receipt.action, "retract")
        self.assertEqual(backend.new_source_at_failure.text, self.control.text)
        for conn in backend.connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")
        with closing(sqlite3.connect(self.path, isolation_level=None, timeout=0)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(self.backend.read_receipt(self.scope, "withdraw_op"))
        with self.backend.transaction() as conn:
            self.assertIsNone(self.backend.get_source(conn, self.scope, self.control.source_id))

    def test_remember_and_replace_cannot_resurrect_withdrawn_series(self):
        first, second = self.seed()
        self.withdraw()
        self.assertEqual(self.store.remember(self.scope, self.source, self.draft).state, "retracted")
        with self.assertRaises(MemoryConflict):
            self.store.remember(self.scope, replace(self.source, source_id="new"), self.draft)
        with self.assertRaises(MemoryConflict):
            self.store.replace(self.scope, replace(self.control, source_id="new"),
                               replace(self.draft, end=len(self.control.text),
                                       valid_from="2026-10-21T00:00:00+08:00"),
                               expected_version=2, operation_id="restore")
        replay = self.store.replace(self.scope, second.source, second.draft,
                                    expected_version=1, operation_id="update")
        self.assertEqual(replay.state, "retracted")

    def test_new_process_reads_retracted_result_and_operation_receipt(self):
        self.seed()
        result = self.withdraw()
        script = '''
import json, sys
from mini_pi.memory.models import MemoryScope
from mini_pi.memory.store import MemoryStore
from mini_pi.memory.sqlite_backend import SQLiteMemoryBackend
scope = MemoryScope("A", "Pi")
entry = MemoryStore(sys.argv[1]).get(scope, sys.argv[2])
receipt = SQLiteMemoryBackend(sys.argv[1]).read_receipt(scope, "withdraw_op")
print(json.dumps([entry.state, entry.version, receipt.action, receipt.source.text]))
'''
        proc = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", script,
                               str(self.path), result.memory_id], cwd=Path(__file__).resolve().parents[1],
                              capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), ["retracted", 2, "retract", self.control.text])


if __name__ == "__main__":
    unittest.main()
