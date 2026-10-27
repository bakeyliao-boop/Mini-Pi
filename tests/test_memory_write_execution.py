"""写入计划执行入口：先整批预检，再最多调用一次持久变更 API。

辅助类可独立验收；核心类等待用户完成预检和分派后运行。
所有 Source 均为合成记录；MemoryEntry 透传只保留快照，不证明当前有效。
"""

from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.memory.codec import make_entry
from mini_pi.memory.errors import MemoryConflict, MemoryPolicyError
from mini_pi.memory.execution import checked_execution_batch, execute_plans
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.planning import RememberPlan, ReplacePlan, RetractPlan
from mini_pi.memory.sqlite_backend import SQLiteMemoryBackend
from mini_pi.memory.store import MemoryStore


class _ExecutionFixture:
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_memory_write_execution_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "memory" / "state.sqlite3"
        self.scope = MemoryScope("execution-user", "mini-pi")
        self.source = MemorySource(
            "execution-source-1", self.scope, "user", "以后学习用 Python 举例。今天只解释。",
            "2026-10-23T10:00:00+08:00",
        )
        self.draft = MemoryDraft("example_language", 0, len(self.source.text), self.source.recorded_at,
                                 content="用户要求后续学习使用 Python 示例。")
        self.remember = RememberPlan(self.scope, self.source, self.draft)
        self.source2 = replace(self.source, source_id="execution-source-2", text="以后改用 TypeScript 示例。",
                               recorded_at="2026-10-24T10:00:00+08:00")
        self.draft2 = replace(self.draft, end=len(self.source2.text), valid_from=self.source2.recorded_at,
                              content="用户要求改用 TypeScript 示例。")
        self.update = ReplacePlan(self.scope, self.source2, self.draft2, 1, "execution-update")
        self.control = replace(self.source, source_id="execution-control", text="撤回示例语言偏好。")
        self.withdraw = RetractPlan(self.scope, self.control, self.draft.key, (), 1, "execution-withdraw")
        self.entry = make_entry(self.scope, self.source, self.draft, written_at=self.source.recorded_at)
        self.store = MemoryStore(self.path)

    @contextmanager
    def no_store_calls(self):
        with ExitStack() as stack:
            spies = [stack.enter_context(patch.object(
                self.store, name, side_effect=AssertionError("预检拒绝或快照透传不得调用 Store"),
            )) for name in ("get", "latest", "remember", "replace", "retract")]
            spies.append(stack.enter_context(patch(
                "sqlite3.connect", side_effect=AssertionError("此路径不得开库"),
            )))
            network = AsyncMock(side_effect=AssertionError("执行入口不得调用模型"))
            stack.enter_context(patch("mini_pi.async_http_transport.post_json_async", network))
            yield
            for spy in spies:
                spy.assert_not_called()
            network.assert_not_called()

    @contextmanager
    def no_replanning(self, store=None):
        store = self.store if store is None else store
        with (patch.object(store, "latest", side_effect=AssertionError("执行不重新查询 latest")) as latest,
              patch.object(store, "get", side_effect=AssertionError("执行不重新判重")) as get):
            yield
            latest.assert_not_called()
            get.assert_not_called()


class ExecutionBatchShapeTests(_ExecutionFixture, unittest.TestCase):
    def test_list_and_tuple_snapshot_keep_order_members_and_repeats(self):
        for container in (list, tuple):
            with self.subTest(container=container.__name__):
                batch = container((self.entry, self.remember, self.entry))
                checked = checked_execution_batch(self.scope, batch)
                self.assertIsInstance(checked, tuple)
                self.assertEqual(checked, (self.entry, self.remember, self.entry))
                self.assertIs(checked[1], self.remember)
                if isinstance(batch, list):
                    batch.clear()
                    self.assertEqual(checked, (self.entry, self.remember, self.entry))

    def test_helper_defers_member_types_scope_matching_and_plan_count(self):
        foreign = replace(self.remember, scope=MemoryScope("other-user", "other-project"))
        batch = [None, {}, foreign, self.remember, self.remember]
        with self.no_store_calls():
            self.assertEqual(checked_execution_batch(self.scope, batch), tuple(batch))

    def test_empty_batch_is_allowed_but_scope_still_requires_nonempty_identifiers(self):
        self.assertEqual(checked_execution_batch(self.scope, []), ())
        self.assertEqual(checked_execution_batch(self.scope, ()), ())
        for scope in (None, {}, replace(self.scope, user_id=" "),
                      replace(self.scope, project_id=""), replace(self.scope, user_id=True)):
            with self.subTest(scope=scope):
                with self.assertRaises(MemoryPolicyError):
                    checked_execution_batch(scope, [])

    def test_non_list_or_tuple_batch_is_rejected_without_consuming_iterators(self):
        consumed = []

        def generate():
            consumed.append(True)
            yield self.remember

        for batch in (None, {}, "", b"", 1, set(), generate()):
            with self.subTest(batch=batch):
                with self.assertRaises(MemoryPolicyError):
                    checked_execution_batch(self.scope, batch)
        self.assertEqual(consumed, [])


class WriteExecutionTests(_ExecutionFixture, unittest.TestCase):
    def test_empty_and_entry_only_batches_preserve_snapshots_and_make_no_store_calls(self):
        with self.no_store_calls():
            self.assertEqual(execute_plans(self.store, self.scope, []), ())
        self.assertFalse(self.path.parent.exists())
        first = self.store.remember(self.scope, self.source, self.draft)
        withdrawn = self.store.retract(self.scope, self.control, self.draft.key,
                                       expected_version=1, operation_id="withdraw-before-pass-through")
        before = self.path.read_bytes()
        with self.no_store_calls():
            result = execute_plans(self.store, self.scope, (first, withdrawn, first))
        self.assertEqual(result, (first, withdrawn, first))
        self.assertIs(result[0], first)
        self.assertIs(result[1], withdrawn)
        self.assertEqual((result[0].state, result[1].state), ("active", "retracted"))
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_tail_member_or_foreign_scope_rejects_before_any_store_call(self):
        foreign = MemoryScope("other-user", self.scope.project_id)
        other_project = MemoryScope(self.scope.user_id, "other-project")
        bad_items = [None, {}, object(), replace(self.entry, scope=foreign),
                     replace(self.remember, scope=foreign), replace(self.update, scope=other_project),
                     replace(self.withdraw, scope=foreign)]
        with self.no_store_calls():
            for bad in bad_items:
                with self.subTest(bad=bad):
                    with self.assertRaises(MemoryPolicyError):
                        execute_plans(self.store, self.scope, [self.remember, bad])
            for scope, batch in ((None, []), (replace(self.scope, user_id=""), []),
                                 (self.scope, None), (self.scope, iter([self.remember]))):
                with self.subTest(scope=scope, batch=batch):
                    with self.assertRaises(MemoryPolicyError):
                        execute_plans(self.store, scope, batch)
        self.assertFalse(self.path.parent.exists())

    def test_multiple_plans_including_duplicate_plan_are_rejected_before_first_mutation(self):
        batches = ((self.remember, self.remember), (self.remember, self.update),
                   (self.entry, self.withdraw, self.entry, self.update))
        with self.no_store_calls():
            for batch in batches:
                with self.subTest(batch=batch):
                    with self.assertRaises(MemoryPolicyError):
                        execute_plans(self.store, self.scope, batch)
        self.assertFalse(self.path.parent.exists())

    def test_one_remember_plan_persists_content_and_preserves_result_position(self):
        history_source = replace(self.source, source_id="history-source")
        history = self.store.remember(self.scope, history_source, replace(self.draft, key="history_only"))
        with self.no_replanning():
            result = execute_plans(self.store, self.scope, [history, self.remember, history])
        self.assertEqual((result[0], result[2]), (history, history))
        saved = result[1]
        self.assertEqual((saved.version, saved.source.text, saved.draft.content),
                         (1, self.source.text, self.draft.content))
        self.assertEqual(self.store.get(self.scope, saved.memory_id), saved)
        self.assertEqual(len(SQLiteMemoryBackend(self.path).read_entries(self.scope)), 2)

    def test_replace_original_plan_replays_receipt_after_later_version_without_replanning(self):
        self.store.remember(self.scope, self.source, self.draft)
        with self.no_replanning():
            second, = execute_plans(self.store, self.scope, [self.update])
        self.assertEqual((second.version, second.text), (2, self.draft2.content))
        source3 = replace(self.source2, source_id="execution-source-3", text="以后改用 Rust 示例。",
                          recorded_at="2026-10-25T10:00:00+08:00")
        draft3 = replace(self.draft2, end=len(source3.text), valid_from=source3.recorded_at,
                         content="用户要求使用 Rust 示例。")
        self.store.replace(self.scope, source3, draft3, expected_version=2, operation_id="later-v3")
        before = self.path.read_bytes()
        with self.no_replanning():
            replay, = execute_plans(self.store, self.scope, [self.update])
        self.assertEqual((replay.memory_id, replay.version, replay.state),
                         (second.memory_id, 2, "superseded"))
        self.assertEqual(self.path.read_bytes(), before)

    def test_retract_original_plan_replays_receipt_and_preserves_control_source(self):
        first = self.store.remember(self.scope, self.source, self.draft)
        with self.no_replanning():
            withdrawn, = execute_plans(self.store, self.scope, [self.withdraw])
        self.assertEqual((withdrawn.memory_id, withdrawn.version, withdrawn.state),
                         (first.memory_id, 1, "retracted"))
        self.assertEqual(withdrawn.source, first.source)
        receipt = SQLiteMemoryBackend(self.path).read_receipt(self.scope, self.withdraw.operation_id)
        self.assertEqual((receipt.source.source_id, receipt.source.text),
                         (self.control.source_id, self.control.text))
        before = self.path.read_bytes()
        with self.no_replanning():
            self.assertEqual(execute_plans(self.store, self.scope, [self.withdraw]), (withdrawn,))
        self.assertEqual(self.path.read_bytes(), before)

    def test_retract_forwards_conditions_and_withdraws_only_target_series_all_versions(self):
        conditions = (("period", "weekend"),)
        source1 = replace(self.source, text="学习时默认用 Java，周末用 Python 举例。")
        source2 = replace(self.source2, text="以后默认改用 Rust，周末改用 TypeScript 举例。")
        target1 = replace(self.draft, end=len(source1.text), conditions=conditions,
                           content="用户要求周末使用 Python 示例。")
        target2 = replace(self.draft2, end=len(source2.text), conditions=conditions,
                           content="用户要求周末改用 TypeScript 示例。")
        first = self.store.remember(self.scope, source1, target1)
        second = self.store.replace(self.scope, source2, target2,
                                    expected_version=1, operation_id="target-series-update")
        # 默认系列也推进到 v2；漏传 conditions 将误撤该系列，不能靠版本差侥幸拒绝。
        self.store.remember(self.scope, source1, replace(target1, conditions=(), content="默认使用 Java 示例。"))
        self.store.replace(self.scope, source2,
                           replace(target2, conditions=(), content="默认改用 Rust 示例。"),
                           expected_version=1, operation_id="default-series-update")
        backend = SQLiteMemoryBackend(self.path)
        before = {entry.memory_id: entry for entry in backend.read_entries(self.scope)}
        control = replace(self.control, text="撤回周末示例语言偏好。")
        plan = RetractPlan(self.scope, control, self.draft.key, conditions, 2, "withdraw-weekend")
        with self.no_replanning():
            withdrawn, = execute_plans(self.store, self.scope, [plan])
        self.assertEqual((withdrawn.memory_id, withdrawn.version, withdrawn.state),
                         (second.memory_id, 2, "retracted"))
        self.assertEqual(withdrawn.source, second.source)
        target_ids = {first.memory_id, second.memory_id}
        expected = {memory_id: replace(entry, state="retracted") if memory_id in target_ids else entry
                    for memory_id, entry in before.items()}
        self.assertEqual({entry.memory_id: entry for entry in backend.read_entries(self.scope)}, expected)

    def _assert_intervening_version_preserves_original_cas(self, name, plan):
        path = self.root / f"cas-{name}.sqlite3"
        store = MemoryStore(path)
        store.remember(self.scope, self.source, self.draft)
        competing = store.replace(self.scope, self.source2, self.draft2,
                                   expected_version=1, operation_id="competing-v2")
        before = path.read_bytes()
        with self.no_replanning(store):
            with self.assertRaises(MemoryConflict):
                execute_plans(store, self.scope, [plan])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(store.latest(self.scope, self.draft.key), competing)

    def test_intervening_version_preserves_original_cas_for_replace(self):
        self._assert_intervening_version_preserves_original_cas("replace", self.update)

    def test_intervening_version_preserves_original_cas_for_retract(self):
        self._assert_intervening_version_preserves_original_cas("retract", self.withdraw)

    def test_store_exception_is_propagated_without_partial_result_or_rewrite(self):
        failure = sqlite3.OperationalError("controlled Store failure")
        with patch.object(self.store, "remember", side_effect=failure) as remember:
            with self.assertRaises(sqlite3.OperationalError) as caught:
                execute_plans(self.store, self.scope, [self.entry, self.remember])
            self.assertIs(caught.exception, failure)
            remember.assert_called_once_with(self.remember.scope, self.remember.source, self.remember.draft)
        self.assertFalse(self.path.parent.exists())


if __name__ == "__main__":
    unittest.main()
