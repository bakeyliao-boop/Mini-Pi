"""最新系列只读入口与首次新增计划；不验证模型提取的语义真实性。

MemoryLatestReadTests 可先验辅助层；RememberPlanningTests 待用户完成核心。
已有系列在本段一律暂停；不替换 MemoryStore.remember 自身的重试幂等行为。
"""

from contextlib import closing
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from mini_pi.memory.errors import MemoryConflict, MemoryDataError, MemoryPolicyError
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.planning import RememberPlan, plan_remember
from mini_pi.memory.sqlite_backend import SQLiteMemoryBackend
from mini_pi.memory.store import MemoryStore


class _PlanningFixture:
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_memory_planning_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "memory" / "state.sqlite3"
        self.scope = MemoryScope("planning-user", "mini-pi")
        self.source = MemorySource(
            "planning-source-1", self.scope, "user",
            "以后学习时用 Python 举例。今天这题只解释，不改文件。",
            "2026-10-22T10:00:00+08:00",
        )
        self.draft = MemoryDraft(
            "example_language", 0, len(self.source.text), self.source.recorded_at,
            content="用户希望后续学习使用 Python 示例。",
        )
        self.store = MemoryStore(self.path)
        self.backend = SQLiteMemoryBackend(self.path)

    def seed(self, source_id, *, scope=None, key="example_language", conditions=()):
        scope = self.scope if scope is None else scope
        source = replace(self.source, source_id=source_id, scope=scope)
        return self.store.remember(scope, source, replace(self.draft, key=key, conditions=conditions))

    def future_version(self, store=None):
        store = self.store if store is None else store
        source = replace(self.source, source_id="planning-source-2", text="从十一月起用 TypeScript 举例。")
        draft = replace(self.draft, end=len(source.text), valid_from="2026-11-01T00:00:00+08:00",
                        content="用户要求十一月起使用 TypeScript 示例。")
        return store.replace(self.scope, source, draft, expected_version=1, operation_id="future-v2")


class MemoryLatestReadTests(_PlanningFixture, unittest.TestCase):
    def test_missing_database_returns_none_without_creating_directory_or_file(self):
        for read in (self.backend.read_latest, self.store.latest):
            with self.subTest(reader=read.__qualname__):
                self.assertIsNone(read(self.scope, self.draft.key))
                self.assertFalse(self.path.exists())
                self.assertFalse(self.path.parent.exists())

    def test_scope_key_and_exact_normalized_conditions_select_distinct_series(self):
        base = self.seed("base")
        conditions = (("period", "weekend"), ("timezone", "Asia/Shanghai"))
        weekend = self.seed("weekend", conditions=conditions)
        other_key = self.seed("study", key="study_time")
        other_user = self.seed("other-user", scope=MemoryScope("other-user", self.scope.project_id))
        other_project = self.seed("other-project", scope=MemoryScope(self.scope.user_id, "other-project"))
        before = self.path.read_bytes()
        for read in (self.backend.read_latest, self.store.latest):
            with self.subTest(reader=read.__qualname__):
                self.assertEqual(read(self.scope, self.draft.key), base)
                self.assertEqual(read(self.scope, self.draft.key, conditions=tuple(reversed(conditions))), weekend)
                self.assertEqual(read(self.scope, "study_time"), other_key)
                self.assertEqual(read(other_user.scope, self.draft.key), other_user)
                self.assertEqual(read(other_project.scope, self.draft.key), other_project)
                self.assertIsNone(read(self.scope, "missing-key"))
                self.assertIsNone(read(self.scope, self.draft.key, conditions=(("period", "weekend"),)))
                self.assertIsNone(read(MemoryScope("missing-user", self.scope.project_id), self.draft.key))
        self.assertEqual(self.path.read_bytes(), before)

    def test_highest_committed_version_is_returned_even_when_future_or_retracted(self):
        self.seed("planning-source-1")
        future = self.future_version()
        for read in (self.backend.read_latest, self.store.latest):
            self.assertEqual(read(self.scope, self.draft.key), future)
        control = replace(self.source, source_id="planning-withdrawal", text="撤回学习示例语言偏好。")
        withdrawn = self.store.retract(self.scope, control, self.draft.key,
                                      expected_version=2, operation_id="withdraw-future")
        for read in (self.backend.read_latest, self.store.latest):
            latest = read(self.scope, self.draft.key)
            self.assertEqual((latest.memory_id, latest.version, latest.state),
                             (withdrawn.memory_id, 2, "retracted"))

    def test_frozen_legacy_database_can_supply_active_and_retracted_heads(self):
        fixture_dir = Path(__file__).parent / "fixtures"
        frozen = json.loads((fixture_dir / "memory_legacy_content_v1.json").read_text(encoding="utf-8"))
        self.path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executescript((fixture_dir / "memory_legacy_content_v1.sql").read_text(encoding="utf-8"))
        scope = MemoryScope(**frozen["scope"])
        before = self.path.read_bytes()
        for read in (self.backend.read_latest, self.store.latest):
            active = read(scope, "example_language")
            withdrawn = read(scope, "study_time")
            self.assertEqual((active.memory_id, active.version, active.state),
                             (frozen["replace_request"]["result_memory_id"], 2, "active"))
            self.assertEqual((withdrawn.memory_id, withdrawn.state),
                             (frozen["retract_request"]["result_memory_id"], "retracted"))
            self.assertIsNone(active.draft.content)
        self.assertEqual(self.path.read_bytes(), before)

    def test_open_failure_is_data_error_and_decode_failure_closes_real_connections(self):
        entry = self.seed("base")
        with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("controlled open failure")):
            for read in (self.backend.read_latest, self.store.latest):
                with self.subTest(open_failure=read.__qualname__):
                    with self.assertRaises(MemoryDataError):
                        read(self.scope, self.draft.key)
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("UPDATE entries SET payload = '{}' WHERE memory_id = ?", (entry.memory_id,))
            conn.commit()
        real_connect = sqlite3.connect
        opened = []

        def track_connection(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            opened.append(conn)
            return conn

        with patch("sqlite3.connect", side_effect=track_connection):
            for read in (self.backend.read_latest, self.store.latest):
                with self.subTest(decode_failure=read.__qualname__):
                    with self.assertRaises(MemoryDataError):
                        read(self.scope, self.draft.key)
        self.assertEqual(len(opened), 2)
        for conn in opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")

    def test_rollback_failure_still_closes_the_real_read_connection(self):
        self.seed("base")
        conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, isolation_level=None)
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        controlled = Mock(wraps=conn)
        controlled.rollback.side_effect = sqlite3.OperationalError("controlled cleanup failure")
        with patch("sqlite3.connect", return_value=controlled):
            with self.assertRaises(MemoryDataError):
                self.store.latest(self.scope, self.draft.key)
        controlled.close.assert_called_once()
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


class RememberPlanningTests(_PlanningFixture, unittest.TestCase):
    def test_empty_database_produces_concrete_normalized_plan_without_persistent_write(self):
        conditions = (("timezone", "Asia/Shanghai"), ("period", "weekend"))
        draft = replace(self.draft, conditions=conditions)
        plan = plan_remember(self.store, self.scope, self.source, draft)
        self.assertIsInstance(plan, RememberPlan)
        self.assertEqual(plan.scope, self.scope)
        self.assertEqual(plan.source.text, self.source.text)
        self.assertEqual(plan.source.source_id, self.source.source_id)
        self.assertEqual(plan.source.recorded_at, "2026-10-22T02:00:00.000000+00:00")
        self.assertEqual(plan.draft.valid_from, "2026-10-22T02:00:00.000000+00:00")
        self.assertEqual(plan.draft.conditions, (("period", "weekend"), ("timezone", "Asia/Shanghai")))
        self.assertEqual(plan.draft.content, self.draft.content)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.parent.exists())
        with self.assertRaises(FrozenInstanceError):
            plan.source = self.source

    def test_bad_source_or_draft_is_rejected_before_reading_or_writing_series(self):
        bad = [
            (replace(self.source, scope=MemoryScope("other-user", self.scope.project_id)), self.draft),
            (replace(self.source, role="assistant"), self.draft),
            (replace(self.source, role="tool"), self.draft),
            (self.source, replace(self.draft, content=" \n")),
            (self.source, replace(self.draft, end=len(self.source.text) - 1)),
        ]
        with patch.object(self.store, "latest", side_effect=AssertionError("非法输入不得查询系列")) as latest:
            for source, draft in bad:
                with self.subTest(source=source, draft=draft):
                    with self.assertRaises(MemoryPolicyError):
                        plan_remember(self.store, self.scope, source, draft)
            latest.assert_not_called()
        self.assertFalse(self.path.parent.exists())

    def test_any_existing_head_blocks_this_branch_including_future_and_retracted(self):
        for state in ("active", "future", "retracted"):
            with self.subTest(state=state):
                path = self.root / f"{state}.sqlite3"
                store = MemoryStore(path)
                first = store.remember(self.scope, self.source, self.draft)
                if state != "active":
                    self.future_version(store)
                if state == "retracted":
                    control = replace(self.source, source_id="withdraw-plan", text="撤回学习示例语言偏好。")
                    store.retract(self.scope, control, self.draft.key,
                                  expected_version=2, operation_id="withdraw-plan")
                before = path.read_bytes()
                with self.assertRaises(MemoryConflict):
                    plan_remember(store, self.scope, self.source, self.draft)
                self.assertEqual(path.read_bytes(), before)
                if state == "active":
                    # 规划入口暂停已有系列，不改变底层 remember 的原候选重试契约。
                    self.assertEqual(store.remember(self.scope, self.source, self.draft), first)

    def test_plan_can_execute_once_but_intervening_insert_prevents_overwrite(self):
        plan = plan_remember(self.store, self.scope, self.source, self.draft)
        saved = self.store.remember(plan.scope, plan.source, plan.draft)
        restored = MemoryStore(self.path).get(self.scope, saved.memory_id)
        self.assertEqual((restored.version, restored.source, restored.text),
                         (1, plan.source, self.draft.content))
        self.assertEqual(SQLiteMemoryBackend(self.path).read_entries(self.scope), [saved])

        competing_path = self.root / "interleaved.sqlite3"
        target = MemoryStore(competing_path)
        stale_plan = plan_remember(target, self.scope, self.source, self.draft)
        other_source = replace(self.source, source_id="intervening-source", text="后续示例使用 JavaScript。")
        other_draft = replace(self.draft, end=len(other_source.text), content="用户希望使用 JavaScript 示例。")
        winner = MemoryStore(competing_path).remember(self.scope, other_source, other_draft)
        before = competing_path.read_bytes()
        with self.assertRaises(MemoryConflict):
            target.remember(stale_plan.scope, stale_plan.source, stale_plan.draft)
        self.assertEqual(competing_path.read_bytes(), before)
        self.assertEqual(target.latest(self.scope, self.draft.key), winner)


if __name__ == "__main__":
    unittest.main()
