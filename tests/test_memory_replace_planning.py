"""显式更新的首次规划；执行和重试复用原计划，不重新读取head生成请求。"""

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.memory.errors import MemoryConflict, MemoryPolicyError
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.planning import ReplacePlan, plan_replace
from mini_pi.memory.store import MemoryStore


class ReplacePlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_memory_replace_planning_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "memory" / "state.sqlite3"
        self.scope = MemoryScope("replace-plan-user", "mini-pi")
        self.source = MemorySource(
            "replace-plan-source-1", self.scope, "user", "以后学习请用 Python 示例。",
            "2026-10-22T10:00:00+08:00",
        )
        self.draft = MemoryDraft(
            "example_language", 0, len(self.source.text), self.source.recorded_at,
            conditions=(("timezone", "Asia/Shanghai"), ("period", "weekend")),
            content="用户希望使用 Python 示例。",
        )
        self.source2 = replace(self.source, source_id="replace-plan-source-2",
                               text="从现在起学习改用 TypeScript 示例。",
                               recorded_at="2026-10-23T10:00:00+08:00")
        self.draft2 = replace(self.draft, end=len(self.source2.text), valid_from=self.source2.recorded_at,
                              content="  用户要求后续使用 TypeScript 示例。\n")
        self.store = MemoryStore(self.path)

    def seed(self):
        return self.store.remember(self.scope, self.source, self.draft)

    def execute(self, plan):
        return self.store.replace(plan.scope, plan.source, plan.draft,
                                  expected_version=plan.expected_version, operation_id=plan.operation_id)

    def test_active_head_produces_complete_normalized_readonly_plan_and_missing_head_rejects(self):
        self.seed()
        before = self.path.read_bytes()
        draft = replace(self.draft2, conditions=tuple(reversed(self.draft2.conditions)))
        with patch.object(self.store._backend, "transaction", side_effect=AssertionError("规划不写库")) as write:
            plan = plan_replace(self.store, self.scope, self.source2, draft, operation_id="replace-plan")
            write.assert_not_called()
        self.assertIsInstance(plan, ReplacePlan)
        self.assertEqual((plan.scope, plan.expected_version, plan.operation_id), (self.scope, 1, "replace-plan"))
        self.assertEqual(plan.source.text, self.source2.text)
        self.assertEqual(plan.source.source_id, self.source2.source_id)
        self.assertEqual(plan.source.recorded_at, "2026-10-23T02:00:00.000000+00:00")
        self.assertEqual(plan.draft.valid_from, "2026-10-23T02:00:00.000000+00:00")
        self.assertEqual(plan.draft.conditions, (("period", "weekend"), ("timezone", "Asia/Shanghai")))
        self.assertEqual(plan.draft.content, self.draft2.content)
        with self.assertRaises(FrozenInstanceError):
            plan.expected_version = 99
        self.assertEqual(self.path.read_bytes(), before)

        missing_path = self.root / "missing" / "state.sqlite3"
        with patch("sqlite3.connect", side_effect=AssertionError("缺库不应创建连接")) as connect:
            with self.assertRaises(MemoryConflict):
                plan_replace(MemoryStore(missing_path), self.scope, self.source2, self.draft2,
                             operation_id="missing-head")
            connect.assert_not_called()
        self.assertFalse(missing_path.parent.exists())

    def test_invalid_source_draft_or_operation_id_is_rejected_before_head_query(self):
        cases = [
            (replace(self.source2, scope=MemoryScope("other-user", self.scope.project_id)), self.draft2, "op"),
            (replace(self.source2, role="assistant"), self.draft2, "op"),
            (self.source2, replace(self.draft2, content=" \n"), "op"),
            (self.source2, replace(self.draft2, end=len(self.source2.text) - 1), "op"),
        ]
        cases.extend((self.source2, self.draft2, operation_id) for operation_id in ("", " \n", None))
        with (
            patch.object(self.store, "latest", side_effect=AssertionError("非法输入不应查询head")) as latest,
            patch.object(self.store._backend, "transaction", side_effect=AssertionError("规划不写库")) as write,
        ):
            for source, draft, operation_id in cases:
                with self.subTest(source=source, draft=draft, operation_id=operation_id):
                    with self.assertRaises(MemoryPolicyError):
                        plan_replace(self.store, self.scope, source, draft, operation_id=operation_id)
            latest.assert_not_called()
            write.assert_not_called()
        self.assertFalse(self.path.parent.exists())

    def test_retracted_head_kind_change_and_nonlater_time_are_rejected(self):
        self.seed()
        before = self.path.read_bytes()
        for draft in (
            replace(self.draft2, kind="episodic"),
            replace(self.draft2, valid_from=self.draft.valid_from),
            replace(self.draft2, valid_from="2026-10-21T10:00:00+08:00"),
        ):
            with self.subTest(draft=draft):
                with self.assertRaises(MemoryConflict):
                    plan_replace(self.store, self.scope, self.source2, draft, operation_id="invalid-transition")
                self.assertEqual(self.path.read_bytes(), before)
        control = replace(self.source, source_id="replace-plan-withdrawal", text="撤回示例语言偏好。")
        self.store.retract(self.scope, control, self.draft.key, conditions=self.draft.conditions,
                           expected_version=1, operation_id="withdraw-before-plan")
        before = self.path.read_bytes()
        with self.assertRaises(MemoryConflict):
            plan_replace(self.store, self.scope, self.source2, self.draft2, operation_id="after-retraction")
        self.assertEqual(self.path.read_bytes(), before)

    def test_future_head_supplies_highest_persisted_version_for_later_effective_update(self):
        self.seed()
        future_draft = replace(self.draft2, valid_from="2026-11-01T00:00:00+08:00")
        future = self.store.replace(self.scope, self.source2, future_draft,
                                    expected_version=1, operation_id="future-head")
        source3 = replace(self.source2, source_id="replace-plan-source-3", text="从十二月起请用 Rust 示例。")
        draft3 = replace(self.draft2, end=len(source3.text), valid_from="2026-12-01T00:00:00+08:00",
                         content="用户要求十二月起使用 Rust 示例。")
        before = self.path.read_bytes()
        plan = plan_replace(self.store, self.scope, source3, draft3, operation_id="after-future")
        self.assertEqual(plan.expected_version, future.version)
        self.assertEqual(plan.expected_version, 2)
        self.assertEqual(plan.draft.valid_from, "2026-11-30T16:00:00.000000+00:00")
        self.assertEqual(self.path.read_bytes(), before)

    def test_intervening_update_causes_execution_cas_conflict_without_overwrite(self):
        self.seed()
        plan = plan_replace(self.store, self.scope, self.source2, self.draft2, operation_id="planned-update")
        competing_source = replace(self.source2, source_id="competing-source", text="以后请用 Java 示例。")
        competing_draft = replace(self.draft2, end=len(competing_source.text), content="用户要求使用 Java 示例。")
        competing = self.store.replace(self.scope, competing_source, competing_draft,
                                       expected_version=1, operation_id="competing-update")
        before = self.path.read_bytes()
        with self.assertRaises(MemoryConflict):
            self.execute(plan)
        self.assertEqual(self.store.latest(self.scope, self.draft.key, conditions=self.draft.conditions), competing)
        self.assertEqual(self.path.read_bytes(), before)

    def test_original_plan_replays_receipt_after_v3_and_retraction_but_changed_request_conflicts(self):
        self.seed()
        plan = plan_replace(self.store, self.scope, self.source2, self.draft2, operation_id="original-update")
        second = self.execute(plan)
        source3 = replace(self.source2, source_id="later-source-3", text="以后学习请改用 Rust 示例。",
                          recorded_at="2026-10-24T10:00:00+08:00")
        draft3 = replace(self.draft2, end=len(source3.text), valid_from=source3.recorded_at,
                         content="用户要求后续学习使用 Rust 示例。")
        self.store.replace(self.scope, source3, draft3, expected_version=2, operation_id="later-update-v3")
        before = self.path.read_bytes()
        replay = self.execute(plan)  # 复用原计划，绝不重新调用plan_replace。
        self.assertEqual((replay.memory_id, replay.version, replay.state), (second.memory_id, 2, "superseded"))
        self.assertEqual(self.path.read_bytes(), before)

        control = replace(self.source, source_id="withdraw-after-v3", text="撤回示例语言整个系列。")
        self.store.retract(self.scope, control, self.draft.key, conditions=self.draft.conditions,
                           expected_version=3, operation_id="withdraw-after-v3")
        before = self.path.read_bytes()
        replay = self.execute(plan)
        self.assertEqual((replay.memory_id, replay.version, replay.state), (second.memory_id, 2, "retracted"))
        changed = replace(plan, draft=replace(plan.draft, content="同一操作编号下被改写的正文。"))
        with self.assertRaises(MemoryConflict):
            self.execute(changed)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
