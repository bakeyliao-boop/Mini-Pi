"""同一候选重试识别；核心手敲后运行，不把未命中当作新增许可。

仅使用临时SQLite；没有语义去重、模型调用或最新系列规划替代。
"""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.memory.codec import candidate_id
from mini_pi.memory.errors import MemoryConflict, MemoryPolicyError
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.planning import find_retry, plan_remember
from mini_pi.memory.store import MemoryStore


class MemoryRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_memory_retry_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "memory" / "state.sqlite3"
        self.scope = MemoryScope("retry-user", "mini-pi")
        self.source = MemorySource(
            "retry-source-1", self.scope, "user", "这次学习请用 Python 示例。",
            "2026-10-22T10:00:00+08:00",
        )
        self.draft = MemoryDraft(
            "example_language", 0, len(self.source.text), self.source.recorded_at,
            kind="episodic", conditions=(("timezone", "Asia/Shanghai"), ("period", "weekend")),
            content="用户在本次学习中要求使用 Python 示例。",
        )
        self.store = MemoryStore(self.path)

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def lookup(self, source, draft):
        with (
            patch.object(self.store, "latest", side_effect=AssertionError("重试识别不查询最新系列")) as latest,
            patch.object(self.store._backend, "transaction", side_effect=AssertionError("重试识别不写库")) as write,
        ):
            result = find_retry(self.store, self.scope, source, draft)
            latest.assert_not_called()
            write.assert_not_called()
            return result

    def test_missing_database_returns_none_without_creation_or_latest_query(self):
        with patch("sqlite3.connect", side_effect=AssertionError("缺库不应创建连接")) as connect:
            self.assertIsNone(self.lookup(self.source, self.draft))
            connect.assert_not_called()
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.parent.exists())

    def test_equivalent_timezones_and_condition_order_match_remember_retry_without_changes(self):
        saved = self.store.remember(self.scope, self.source, self.draft)
        source = replace(self.source, recorded_at="2026-10-22T02:00:00.000000+00:00")
        draft = replace(self.draft, valid_from="2026-10-22T02:00:00Z",
                        conditions=tuple(reversed(self.draft.conditions)))
        before = self.snapshot()
        found = self.lookup(source, draft)
        self.assertEqual(found, saved)
        self.assertEqual(found, self.store.remember(self.scope, source, draft))
        self.assertEqual(self.snapshot(), before)

    def test_same_id_changed_source_or_draft_definition_is_a_conflict(self):
        saved = self.store.remember(self.scope, self.source, self.draft)
        before = self.snapshot()
        variants = (
            (replace(self.source, text="甲" * len(self.source.text)), self.draft),
            (replace(self.source, recorded_at="2026-10-22T10:00:01+08:00"), self.draft),
            # episodic使user/tool均通过既有来源准入，冲突确由完整Source不同触发。
            (replace(self.source, role="tool"), self.draft),
            (self.source, replace(self.draft, content="用户在本次学习中要求使用 TypeScript 示例。")),
            (self.source, replace(self.draft, content=None)),
            (self.source, replace(self.draft, valid_from="2026-10-23T10:00:00+08:00")),
        )
        for source, draft in variants:
            with self.subTest(source=source, draft=draft):
                self.assertEqual(candidate_id(self.scope, source, draft), saved.memory_id)
                with self.assertRaises(MemoryConflict):
                    self.lookup(source, draft)
                self.assertEqual(self.snapshot(), before)

    def test_old_retry_returns_superseded_or_retracted_entry_without_reactivation(self):
        first = self.store.remember(self.scope, self.source, self.draft)
        source2 = replace(self.source, source_id="retry-source-2", text="十一月开始请用 TypeScript 示例。")
        draft2 = replace(self.draft, end=len(source2.text), valid_from="2026-11-01T00:00:00+08:00",
                         content="用户要求十一月起使用 TypeScript 示例。")
        second = self.store.replace(self.scope, source2, draft2,
                                    expected_version=1, operation_id="retry-future-v2")
        before = self.snapshot()
        old = self.lookup(self.source, self.draft)
        self.assertEqual(old, self.store.get(self.scope, first.memory_id))
        self.assertEqual((old.memory_id, old.version, old.state), (first.memory_id, 1, "superseded"))
        self.assertEqual(self.snapshot(), before)

        control = replace(self.source, source_id="retry-withdrawal", text="撤回学习示例语言记录。")
        self.store.retract(self.scope, control, self.draft.key, conditions=self.draft.conditions,
                           expected_version=2, operation_id="retry-withdraw-series")
        before = self.snapshot()
        old = self.lookup(self.source, self.draft)
        current = self.lookup(source2, draft2)
        self.assertEqual((old.memory_id, old.state), (first.memory_id, "retracted"))
        self.assertEqual((current.memory_id, current.state), (second.memory_id, "retracted"))
        self.assertEqual(old, self.store.get(self.scope, first.memory_id))
        self.assertEqual(current, self.store.get(self.scope, second.memory_id))
        self.assertEqual(self.snapshot(), before)

    def test_different_source_same_content_is_not_retry_and_existing_series_blocks_new_plan(self):
        saved = self.store.remember(self.scope, self.source, self.draft)
        independent = replace(self.source, source_id="independent-record")
        self.assertEqual(independent.text, self.source.text)
        self.assertNotEqual(candidate_id(self.scope, independent, self.draft), saved.memory_id)
        before = self.snapshot()
        self.assertIsNone(self.lookup(independent, self.draft))
        with self.assertRaises(MemoryConflict):
            plan_remember(self.store, self.scope, independent, self.draft)
        self.assertEqual(self.snapshot(), before)

    def test_bad_scope_source_or_draft_is_rejected_before_database_lookup(self):
        cases = (
            (None, self.source, self.draft),
            (self.scope, None, self.draft),
            (self.scope, self.source, None),
            (self.scope, replace(self.source, scope=MemoryScope("other-user", self.scope.project_id)), self.draft),
            (self.scope, replace(self.source, role="assistant"), self.draft),
            (self.scope, self.source, replace(self.draft, content=" \n")),
            (self.scope, self.source, replace(self.draft, end=len(self.source.text) - 1)),
        )
        with (
            patch.object(self.store, "get", side_effect=AssertionError("非法输入不得读取候选")) as get,
            patch.object(self.store, "latest", side_effect=AssertionError("非法输入不得读取系列")) as latest,
            patch.object(self.store._backend, "transaction", side_effect=AssertionError("非法输入不得写库")) as write,
        ):
            for scope, source, draft in cases:
                with self.subTest(scope=scope, source=source, draft=draft):
                    with self.assertRaises(MemoryPolicyError):
                        find_retry(self.store, scope, source, draft)
            get.assert_not_called()
            latest.assert_not_called()
            write.assert_not_called()
        self.assertFalse(self.path.parent.exists())


if __name__ == "__main__":
    unittest.main()
