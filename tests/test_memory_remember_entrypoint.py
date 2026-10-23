"""重试或首次新增的整合入口；只规划，不执行持久变更。"""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.memory.errors import MemoryConflict
from mini_pi.memory.models import MemoryDraft, MemoryEntry, MemoryScope, MemorySource
from mini_pi.memory.planning import RememberPlan, plan_remember_or_retry
from mini_pi.memory.store import MemoryStore


class RememberEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_memory_remember_entrypoint_")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "memory" / "state.sqlite3"
        self.scope = MemoryScope("entrypoint-user", "mini-pi")
        self.source = MemorySource(
            "entrypoint-source-1", self.scope, "user", "以后学习请用 Python 示例。",
            "2026-10-22T10:00:00+08:00",
        )
        self.draft = MemoryDraft(
            "example_language", 0, len(self.source.text), self.source.recorded_at,
            content="用户希望后续学习使用 Python 示例。",
        )
        self.store = MemoryStore(self.path)

    def test_retry_returns_old_superseded_or_retracted_entry_without_latest_or_write(self):
        first = self.store.remember(self.scope, self.source, self.draft)
        source2 = replace(self.source, source_id="entrypoint-source-2", text="十一月起学习改用 TypeScript 示例。")
        draft2 = replace(self.draft, end=len(source2.text), valid_from="2026-11-01T00:00:00+08:00",
                         content="用户要求十一月起使用 TypeScript 示例。")
        self.store.replace(self.scope, source2, draft2,
                           expected_version=1, operation_id="entrypoint-future-v2")
        for state in ("superseded", "retracted"):
            with self.subTest(state=state):
                if state == "retracted":
                    control = replace(self.source, source_id="entrypoint-withdrawal", text="撤回示例语言偏好。")
                    self.store.retract(self.scope, control, self.draft.key,
                                       expected_version=2, operation_id="entrypoint-retract")
                expected = self.store.get(self.scope, first.memory_id)
                before = self.path.read_bytes()
                with (
                    patch.object(self.store, "latest", side_effect=AssertionError("命中重试不查head")) as latest,
                    patch.object(self.store._backend, "transaction", side_effect=AssertionError("入口不写库")) as write,
                    patch("mini_pi.memory.planning.plan_remember", side_effect=AssertionError("重试不进入新增规划")) as plan,
                ):
                    result = plan_remember_or_retry(self.store, self.scope, self.source, self.draft)
                    latest.assert_not_called()
                    write.assert_not_called()
                    plan.assert_not_called()
                self.assertIsInstance(result, MemoryEntry)
                self.assertEqual(result, expected)
                self.assertEqual((result.memory_id, result.version, result.state),
                                 (first.memory_id, 1, state))
                self.assertEqual(self.path.read_bytes(), before)

    def test_fresh_missing_database_returns_concrete_plan_without_creation(self):
        with patch("sqlite3.connect", side_effect=AssertionError("缺库规划不应创建连接")) as connect:
            result = plan_remember_or_retry(self.store, self.scope, self.source, self.draft)
            connect.assert_not_called()
        self.assertIsInstance(result, RememberPlan)
        self.assertEqual(result.scope, self.scope)
        self.assertEqual(result.source.text, self.source.text)
        self.assertEqual(result.source.source_id, self.source.source_id)
        self.assertEqual(result.source.recorded_at, "2026-10-22T02:00:00.000000+00:00")
        self.assertEqual(result.draft.content, self.draft.content)
        self.assertEqual(result.draft.valid_from, "2026-10-22T02:00:00.000000+00:00")
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.parent.exists())

    def test_same_candidate_changed_content_conflict_is_not_swallowed_as_new_plan(self):
        self.store.remember(self.scope, self.source, self.draft)
        before = self.path.read_bytes()
        with (
            patch("mini_pi.memory.planning.plan_remember", side_effect=AssertionError("重试冲突不得转新增")) as plan,
            patch.object(self.store, "latest", side_effect=AssertionError("重试冲突不得查head")) as latest,
            patch.object(self.store._backend, "transaction", side_effect=AssertionError("入口不写库")) as write,
        ):
            with self.assertRaises(MemoryConflict):
                plan_remember_or_retry(
                    self.store, self.scope, self.source,
                    replace(self.draft, content="被重新改写的候选正文。"),
                )
            plan.assert_not_called()
            latest.assert_not_called()
            write.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    def test_distinct_source_same_text_is_not_retry_and_existing_series_blocks_plan(self):
        self.store.remember(self.scope, self.source, self.draft)
        independent = replace(self.source, source_id="independent-entrypoint-source")
        self.assertEqual(independent.text, self.source.text)
        before = self.path.read_bytes()
        with patch.object(self.store._backend, "transaction", side_effect=AssertionError("入口不写库")) as write:
            with self.assertRaises(MemoryConflict):
                plan_remember_or_retry(self.store, self.scope, independent, self.draft)
            write.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
