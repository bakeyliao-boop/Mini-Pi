"""明确撤回的首次规划；意图由上层确认，计划与回执重试分别验证。

Helper类只验格式，可独立运行；Core类待学习者完成plan_retract后执行。
所有数据均为合成记录和临时SQLite，不调用模型或业务数据库。
"""

from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.memory.errors import MemoryConflict, MemoryPolicyError
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.planning import RetractPlan, normalize_retract_request, plan_retract
from mini_pi.memory.sqlite_backend import SQLiteMemoryBackend
from mini_pi.memory.store import MemoryStore


class RetractRequestShapeTests(unittest.TestCase):
    def setUp(self):
        self.scope = MemoryScope("withdraw-user", "mini-pi")
        self.source = MemorySource(
            "withdraw-control", self.scope, "user", "  撤回学习示例语言偏好。\n",
            "2026-10-23T10:00:00+08:00",
        )
        self.conditions = (("timezone", "Asia/Shanghai"), ("period", "weekend"))

    def test_format_preserves_source_and_defers_scope_and_role_decisions(self):
        source = replace(self.source, scope=MemoryScope("other-user", "other-project"), role="assistant")
        before = asdict(source)
        network = AsyncMock(side_effect=AssertionError("格式检查不得调用模型"))
        with (patch("sqlite3.connect", side_effect=AssertionError("格式检查不得开库")) as connect,
              patch("mini_pi.async_http_transport.post_json_async", network)):
            normalized, conditions = normalize_retract_request(
                self.scope, source, "example_language", self.conditions, "withdraw-op",
            )
            connect.assert_not_called()
            network.assert_not_called()
        self.assertEqual(normalized.scope, source.scope)
        self.assertEqual(normalized.role, "assistant")
        self.assertEqual(normalized.source_id, source.source_id)
        self.assertEqual(normalized.text, source.text)
        self.assertEqual(normalized.recorded_at, "2026-10-23T02:00:00.000000+00:00")
        self.assertEqual(conditions, (("period", "weekend"), ("timezone", "Asia/Shanghai")))
        self.assertEqual(asdict(source), before)

    def test_bad_containers_fields_and_naive_time_fail_without_io(self):
        cases = [(None, self.source), (self.scope, None),
                 (replace(self.scope, user_id=""), self.source)]
        cases.extend((self.scope, replace(self.source, **{field: value}))
                     for field, value in (("source_id", ""), ("role", ""), ("text", " \n"),
                                          ("recorded_at", "2026-10-23T10:00:00"),
                                          ("recorded_at", "not-a-time")))
        network = AsyncMock(side_effect=AssertionError("格式检查不得调用模型"))
        with (patch("sqlite3.connect", side_effect=AssertionError("格式检查不得开库")) as connect,
              patch("mini_pi.async_http_transport.post_json_async", network)):
            for scope, source in cases:
                with self.subTest(scope=scope, source=source):
                    with self.assertRaises(MemoryPolicyError):
                        normalize_retract_request(scope, source, "example_language", self.conditions, "op")
            connect.assert_not_called()
            network.assert_not_called()

    def test_bad_key_conditions_and_operation_id_fail_without_io(self):
        cases = [(key, self.conditions, "op") for key in ("", None)]
        cases.extend(("example_language", conditions, "op") for conditions in (
            [], (("period", ""),), (("period", "one"), ("period", "two")),
        ))
        cases.extend(("example_language", self.conditions, operation_id) for operation_id in (" \n", None))
        network = AsyncMock(side_effect=AssertionError("格式检查不得调用模型"))
        with (patch("sqlite3.connect", side_effect=AssertionError("格式检查不得开库")) as connect,
              patch("mini_pi.async_http_transport.post_json_async", network)):
            for key, conditions, operation_id in cases:
                with self.subTest(key=key, conditions=conditions, operation_id=operation_id):
                    with self.assertRaises(MemoryPolicyError):
                        normalize_retract_request(self.scope, self.source, key, conditions, operation_id)
            connect.assert_not_called()
            network.assert_not_called()


class RetractPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_memory_retract_planning_")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "memory" / "state.sqlite3"
        self.scope = MemoryScope("withdraw-user", "mini-pi")
        self.source = MemorySource(
            "withdraw-fact-1", self.scope, "user", "以后学习请用 Python 示例。",
            "2026-10-22T10:00:00+08:00",
        )
        self.draft = MemoryDraft(
            "example_language", 0, len(self.source.text), self.source.recorded_at,
            conditions=(("timezone", "Asia/Shanghai"), ("period", "weekend")),
            content="用户希望后续学习使用 Python 示例。",
        )
        self.control = replace(self.source, source_id="withdraw-control", text="  撤回示例语言偏好。\n",
                               recorded_at="2026-10-23T10:00:00+08:00")
        self.store = MemoryStore(self.path)
        self.backend = SQLiteMemoryBackend(self.path)

    def seed(self):
        return self.store.remember(self.scope, self.source, self.draft)

    def plan(self, *, operation_id="withdraw-plan"):
        return plan_retract(self.store, self.scope, self.control, self.draft.key,
                            conditions=self.draft.conditions, operation_id=operation_id)

    def execute(self, plan):
        return self.store.retract(plan.scope, plan.source, plan.key, conditions=plan.conditions,
                                  expected_version=plan.expected_version, operation_id=plan.operation_id)

    def add_second_version(self):
        source = replace(self.source, source_id="withdraw-fact-2", text="从十一月起请用 TypeScript 示例。")
        draft = replace(self.draft, end=len(source.text), valid_from="2026-11-01T00:00:00+08:00",
                        content="用户要求十一月起使用 TypeScript 示例。")
        return self.store.replace(self.scope, source, draft, expected_version=1, operation_id="future-v2")

    def test_user_receives_complete_normalized_plan_without_persistent_change(self):
        self.seed()
        before = self.path.read_bytes()
        with patch.object(self.store._backend, "transaction", side_effect=AssertionError("规划不写库")) as write:
            plan = self.plan()
            write.assert_not_called()
        self.assertIsInstance(plan, RetractPlan)
        self.assertEqual((plan.scope, plan.key, plan.expected_version, plan.operation_id),
                         (self.scope, self.draft.key, 1, "withdraw-plan"))
        self.assertEqual(plan.source.text, self.control.text)
        self.assertEqual(plan.source.source_id, self.control.source_id)
        self.assertEqual(plan.source.recorded_at, "2026-10-23T02:00:00.000000+00:00")
        self.assertEqual(plan.conditions, (("period", "weekend"), ("timezone", "Asia/Shanghai")))
        with self.assertRaises(FrozenInstanceError):
            plan.expected_version = 99
        self.assertEqual(self.path.read_bytes(), before)

    def test_foreign_scope_nonuser_and_empty_source_fail_before_head_query(self):
        controls = [None, replace(self.control, text=" \n"),
                    replace(self.control, scope=MemoryScope("other-user", self.scope.project_id)),
                    replace(self.control, scope=MemoryScope(self.scope.user_id, "other-project"))]
        controls.extend(replace(self.control, role=role) for role in ("tool", "assistant", "system"))
        with patch.object(self.store, "latest", side_effect=AssertionError("不合格来源不得查询head")) as latest:
            for control in controls:
                with self.subTest(control=control):
                    with self.assertRaises(MemoryPolicyError):
                        plan_retract(self.store, self.scope, control, self.draft.key,
                                     conditions=self.draft.conditions, operation_id="bad-source")
            latest.assert_not_called()
        self.assertFalse(self.path.parent.exists())

    def test_missing_head_and_retracted_head_reject_new_operation(self):
        with patch("sqlite3.connect", side_effect=AssertionError("缺库不应创建连接")) as connect:
            with self.assertRaises(MemoryConflict):
                self.plan()
            connect.assert_not_called()
        self.assertFalse(self.path.parent.exists())
        self.seed()
        self.execute(self.plan(operation_id="first-withdrawal"))
        before = self.path.read_bytes()
        with self.assertRaises(MemoryConflict):
            self.plan(operation_id="new-withdrawal")
        self.assertEqual(self.path.read_bytes(), before)

    def test_future_head_can_be_withdrawn_without_incrementing_versions_or_rewriting_fact_sources(self):
        self.seed()
        second = self.add_second_version()
        before = self.backend.read_entries(self.scope)
        plan = self.plan()
        self.assertEqual(plan.expected_version, 2)
        withdrawn = self.execute(plan)
        self.assertEqual((withdrawn.memory_id, withdrawn.version, withdrawn.state),
                         (second.memory_id, 2, "retracted"))
        after = self.backend.read_entries(self.scope)
        self.assertEqual(after, [replace(entry, state="retracted") for entry in before])
        self.assertEqual(withdrawn.source, second.source)
        self.assertNotEqual(withdrawn.source, plan.source)
        receipt = self.backend.read_receipt(self.scope, plan.operation_id)
        self.assertEqual(receipt.source, plan.source)

    def test_original_plan_retries_receipt_but_changed_request_with_same_id_conflicts(self):
        self.seed()
        plan = self.plan()
        withdrawn = self.execute(plan)
        before = self.path.read_bytes()
        self.assertEqual(self.execute(plan), withdrawn)  # 不重新规划已撤回head。
        variants = (
            replace(plan, source=replace(plan.source, source_id="different-control-source")),
            replace(plan, key="different_key"),
            replace(plan, conditions=(("period", "weekday"),)),
            replace(plan, expected_version=2),
        )
        for changed in variants:
            with self.subTest(changed=changed):
                self.assertEqual(changed.operation_id, plan.operation_id)
                with self.assertRaises(MemoryConflict):
                    self.execute(changed)
                self.assertEqual(self.path.read_bytes(), before)

    def test_intervening_new_version_makes_original_plan_fail_cas_without_retraction(self):
        self.seed()
        plan = self.plan()
        second = self.add_second_version()
        before_entries = self.backend.read_entries(self.scope)
        before = self.path.read_bytes()
        with self.assertRaises(MemoryConflict):
            self.execute(plan)
        self.assertEqual(self.store.latest(self.scope, self.draft.key, conditions=self.draft.conditions), second)
        self.assertEqual(self.backend.read_entries(self.scope), before_entries)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
