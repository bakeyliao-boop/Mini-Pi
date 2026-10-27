"""独立记忆正文与完整来源的存储反例；不判断提取内容的语义真实性。

Codec/Store/Compatibility 测试不依赖 Entry.text 的新分支，可先核对辅助层。
Text/Search 测试保留真实待验行为，不能用旧 property 的通过冒充正文接通。
所有数据库及向量均为本地临时文件和固定替身，不调用模型或网络。
"""

import asyncio
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from mini_pi.memory.codec import (
    candidate_id, dump_entry, dump_source, load_entry, load_source, make_entry,
)
from mini_pi.memory.errors import MemoryConflict, MemoryDataError, MemoryPolicyError
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.operation_codec import (
    dump_receipt, load_receipt, replacement_fingerprint, retraction_fingerprint,
)
from mini_pi.memory.sqlite_backend import SQLiteMemoryBackend
from mini_pi.memory.store import MemoryStore
from tests.test_memory_search import BlockingEmbedder, FixedEmbedder


class _ContentFixture:
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_memory_content_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "memory" / "state.sqlite3"
        self.scope = MemoryScope("content-user", "mini-pi")
        self.source = MemorySource(
            "content-source-1", self.scope, "user",
            "以后学习时请用 Python 示例。今天这题只解释，不改文件。",
            "2026-10-22T02:00:00.000000+00:00",
        )
        self.content = "用户希望后续学习使用 Python 示例。"
        self.draft = MemoryDraft(
            "learning_example_language", 0, len(self.source.text),
            self.source.recorded_at, content=self.content,
        )
        self.source2 = replace(
            self.source, source_id="content-source-2",
            text="从现在起学习示例改用 TypeScript，替代之前的 Python。",
            recorded_at="2026-10-23T02:00:00.000000+00:00",
        )
        self.draft2 = replace(
            self.draft, end=len(self.source2.text), valid_from=self.source2.recorded_at,
            content="用户要求后续学习示例改用 TypeScript。",
        )
        self.store = MemoryStore(self.path)

    def file_snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}


class MemoryContentCodecTests(_ContentFixture, unittest.TestCase):
    def test_content_roundtrip_keeps_complete_source_and_content_whitespace(self):
        draft = replace(self.draft, content="  用户希望使用 Python 示例。\n")
        entry = make_entry(self.scope, self.source, draft,
                           written_at=self.source.recorded_at)
        payload = dump_entry(entry)
        restored = load_entry(payload)
        self.assertEqual(restored, entry)
        self.assertEqual(restored.source, self.source)
        self.assertEqual(restored.draft.content, "  用户希望使用 Python 示例。\n")
        self.assertEqual(json.loads(payload)["draft"]["content"], draft.content)

    def test_explicit_null_blank_wrong_type_and_unknown_payload_fields_are_rejected(self):
        payload = json.loads(dump_entry(make_entry(self.scope, self.source, self.draft)))
        for value in (None, "", " \n\t", False, 42, [], {}):
            with self.subTest(content=value):
                changed = json.loads(json.dumps(payload))
                changed["draft"]["content"] = value
                with self.assertRaises(MemoryDataError):
                    load_entry(json.dumps(changed, ensure_ascii=False))
        for location in ("entry", "draft"):
            with self.subTest(unknown_field=location):
                changed = json.loads(json.dumps(payload))
                target = changed if location == "entry" else changed["draft"]
                target["untrusted_extra"] = "不能静默吞掉未知字段"
                with self.assertRaises(MemoryDataError):
                    load_entry(json.dumps(changed, ensure_ascii=False))

    def test_content_changes_do_not_change_candidate_identity_but_change_replace_request(self):
        other = replace(self.draft, content="用户要求使用另一种示例语言。")
        raw = replace(self.draft, content=None)
        identity = candidate_id(self.scope, self.source, self.draft)
        self.assertEqual(candidate_id(self.scope, self.source, other), identity)
        self.assertEqual(candidate_id(self.scope, self.source, raw), identity)
        fingerprint = replacement_fingerprint(self.scope, self.source, self.draft, 1)
        self.assertNotEqual(replacement_fingerprint(self.scope, self.source, other, 1),
                            fingerprint)
        self.assertNotEqual(replacement_fingerprint(self.scope, self.source, raw, 1),
                            fingerprint)

    def test_invalid_remember_content_does_not_create_database_or_parent(self):
        for index, value in enumerate(("", " \n\t", False, 42, [], {})):
            with self.subTest(content=value):
                path = self.root / f"invalid-{index}" / "state.sqlite3"
                with self.assertRaises(MemoryPolicyError):
                    MemoryStore(path).remember(
                        self.scope, self.source, replace(self.draft, content=value),
                    )
                self.assertFalse(path.exists())
                self.assertFalse(path.parent.exists())


class MemoryContentStoreTests(_ContentFixture, unittest.TestCase):
    def test_new_store_reads_content_and_complete_source(self):
        entry = self.store.remember(self.scope, self.source, self.draft)
        restored = MemoryStore(self.path).get(self.scope, entry.memory_id)
        self.assertEqual(restored, entry)
        self.assertEqual(restored.draft.content, self.content)
        self.assertEqual(restored.source, self.source)

    def test_same_source_changed_content_and_old_raw_to_content_are_conflicts(self):
        for first_content, second_content in (
            (self.content, "用户喜欢 TypeScript 示例。"),
            (None, self.source.text),
        ):
            with self.subTest(first_content=first_content):
                path = self.root / ("raw.sqlite3" if first_content is None else "text.sqlite3")
                store = MemoryStore(path)
                first = store.remember(
                    self.scope, self.source, replace(self.draft, content=first_content),
                )
                before = path.read_bytes()
                with self.assertRaises(MemoryConflict):
                    store.remember(
                        self.scope, self.source, replace(self.draft, content=second_content),
                    )
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(SQLiteMemoryBackend(path).read_entries(self.scope), [first])

    def test_replace_persists_new_content_and_retry_cannot_change_it(self):
        self.store.remember(self.scope, self.source, self.draft)
        updated = self.store.replace(
            self.scope, self.source2, self.draft2, expected_version=1, operation_id="replace-content",
        )
        self.assertEqual(updated.draft.content, self.draft2.content)
        self.assertEqual(MemoryStore(self.path).get(self.scope, updated.memory_id), updated)
        before = self.file_snapshot()
        retried = MemoryStore(self.path).replace(
            self.scope, self.source2, self.draft2, expected_version=1, operation_id="replace-content",
        )
        self.assertEqual(retried, updated)
        self.assertEqual(self.file_snapshot(), before)
        with self.assertRaises(MemoryConflict):
            self.store.replace(
                self.scope, self.source2, replace(self.draft2, content="另一条提取正文。"),
                expected_version=1, operation_id="replace-content",
            )
        self.assertEqual(self.file_snapshot(), before)

    def test_reextracting_retracted_content_never_reactivates_the_series(self):
        first = self.store.remember(self.scope, self.source, self.draft)
        control = replace(self.source, source_id="withdraw-content", text="撤回学习示例语言偏好。")
        self.store.retract(self.scope, control, self.draft.key,
                           expected_version=1, operation_id="retract-content")
        before = self.file_snapshot()
        replay = self.store.remember(self.scope, self.source, self.draft)
        self.assertEqual((replay.memory_id, replay.state), (first.memory_id, "retracted"))
        for source, draft in (
            (self.source, replace(self.draft, content="同一来源被重新改写的正文。")),
            (self.source2, self.draft2),
        ):
            with self.subTest(source=source.source_id):
                with self.assertRaises(MemoryConflict):
                    self.store.remember(self.scope, source, draft)
        with self.assertRaises(MemoryConflict):
            self.store.replace(self.scope, self.source2, self.draft2,
                               expected_version=1, operation_id="revive-content")
        self.assertEqual(self.file_snapshot(), before)
        self.assertEqual([entry.state for entry in SQLiteMemoryBackend(self.path).read_entries(self.scope)],
                         ["retracted"])


class MemoryContentCompatibilityTests(unittest.TestCase):
    def setUp(self):
        fixture_dir = Path(__file__).parent / "fixtures"
        self.frozen = json.loads((fixture_dir / "memory_legacy_content_v1.json").read_text(encoding="utf-8"))
        self.sql = (fixture_dir / "memory_legacy_content_v1.sql").read_text(encoding="utf-8")
        self.scope = MemoryScope(**self.frozen["scope"])
        self.temp = TemporaryDirectory(prefix="_memory_content_legacy_")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "legacy.sqlite3"

    def request_source(self, request):
        raw = request["source"]
        return MemorySource(**{**raw, "scope": MemoryScope(**raw["scope"])})

    def replace_request(self):
        request = self.frozen["replace_request"]
        raw = request["draft"]
        draft = MemoryDraft(**{
            **raw, "conditions": tuple(tuple(item) for item in raw["conditions"]),
        })
        return request, self.request_source(request), draft

    def restore_database(self):
        # 只执行冻结 SQL；不能通过新 codec 重新生成旧库来冒充兼容。
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executescript(self.sql)
        return MemoryStore(self.path)

    def test_frozen_payloads_identifiers_and_receipts_roundtrip_without_new_content_field(self):
        for frozen in self.frozen["entries"]:
            with self.subTest(memory_id=frozen["memory_id"]):
                entry = load_entry(frozen["payload"])
                self.assertIsNone(entry.draft.content)
                self.assertEqual(entry.memory_id, frozen["memory_id"])
                self.assertEqual(candidate_id(self.scope, entry.source, entry.draft), frozen["memory_id"])
                self.assertEqual(dump_entry(entry), frozen["payload"])
        for frozen in self.frozen["sources"]:
            with self.subTest(source_id=frozen["source_id"]):
                self.assertEqual(dump_source(load_source(frozen["payload"])), frozen["payload"])
        for frozen in self.frozen["receipts"]:
            with self.subTest(operation_id=frozen["operation_id"]):
                receipt = load_receipt(frozen["payload"])
                self.assertEqual(receipt.request_hash, frozen["request_hash"])
                self.assertEqual(dump_receipt(receipt), frozen["payload"])

    def test_frozen_replace_and_retract_request_fingerprints_are_unchanged(self):
        request, source, draft = self.replace_request()
        self.assertEqual(replacement_fingerprint(self.scope, source, draft, request["expected_version"]),
                         request["request_hash"])
        control = self.frozen["retract_request"]
        self.assertEqual(retraction_fingerprint(
            self.scope, self.request_source(control), control["key"],
            tuple(tuple(item) for item in control["conditions"]), control["expected_version"],
        ), control["request_hash"])

    def test_frozen_sql_database_reopens_and_receipt_retries_do_not_rewrite_it(self):
        store = self.restore_database()
        before = self.path.read_bytes()
        for frozen in self.frozen["entries"]:
            entry = store.get(self.scope, frozen["memory_id"])
            self.assertIsNone(entry.draft.content)
            self.assertEqual(dump_entry(entry), frozen["payload"])
        request, source, draft = self.replace_request()
        updated = store.replace(self.scope, source, draft,
                                expected_version=request["expected_version"], operation_id=request["operation_id"])
        self.assertEqual(updated.memory_id, request["result_memory_id"])
        control = self.frozen["retract_request"]
        withdrawn = store.retract(
            self.scope, self.request_source(control), control["key"],
            conditions=tuple(tuple(item) for item in control["conditions"]),
            expected_version=control["expected_version"], operation_id=control["operation_id"],
        )
        self.assertEqual((withdrawn.memory_id, withdrawn.state),
                         (control["result_memory_id"], "retracted"))
        self.assertEqual(self.path.read_bytes(), before)

    def test_frozen_database_accepts_new_content_and_preserves_old_receipt_replay(self):
        store = self.restore_database()
        request, source, draft = self.replace_request()
        new_source = replace(source, source_id="legacy-language-3",
                             text="以后改用 TypeScript 举例。",
                             recorded_at="2026-10-23T09:00:00+08:00")
        new_draft = replace(draft, end=len(new_source.text), valid_from=new_source.recorded_at,
                            content="用户要求后续使用 TypeScript 示例。")
        new_entry = store.replace(self.scope, new_source, new_draft,
                                  expected_version=2, operation_id="content-after-legacy")
        self.assertEqual(new_entry.version, 3)
        self.assertEqual(MemoryStore(self.path).get(self.scope, new_entry.memory_id).draft.content,
                         new_draft.content)
        old_replay = store.replace(self.scope, source, draft,
                                   expected_version=request["expected_version"], operation_id=request["operation_id"])
        self.assertEqual((old_replay.memory_id, old_replay.state, old_replay.draft.content),
                         (request["result_memory_id"], "superseded", None))
        self.assertEqual(len(SQLiteMemoryBackend(self.path).read_entries(self.scope)), 4)


class MemoryContentTextTests(_ContentFixture, unittest.TestCase):
    def test_text_returns_independent_content_without_changing_complete_source(self):
        entry = self.store.remember(self.scope, self.source, self.draft)
        self.assertEqual(entry.text, self.content)
        self.assertNotEqual(entry.text, entry.source.text)
        self.assertEqual(entry.source, self.source)
        restored = MemoryStore(self.path).get(self.scope, entry.memory_id)
        self.assertEqual(restored.text, self.content)
        self.assertEqual(restored.source.text, self.source.text)

    def test_none_keeps_existing_source_text_fallback(self):
        entry = self.store.remember(self.scope, self.source, replace(self.draft, content=None))
        self.assertIsNone(entry.draft.content)
        self.assertEqual(entry.text, self.source.text)
        self.assertNotIn("content", json.loads(dump_entry(entry))["draft"])
        self.assertEqual(MemoryStore(self.path).get(self.scope, entry.memory_id).text, self.source.text)


class MemoryContentSearchTests(_ContentFixture, unittest.IsolatedAsyncioTestCase):
    async def test_search_embeds_independent_content_and_returns_original_source(self):
        saved = self.store.remember(self.scope, self.source, self.draft)
        query = "学习示例使用什么语言？"
        embedder = FixedEmbedder({query: (1.0, 0.0), self.content: (1.0, 0.0)})
        before = self.file_snapshot()
        hits = await self.store.search(self.scope, query, at=self.source.recorded_at,
                                       embedder=embedder, top_k=1, min_score=0.8)
        self.assertEqual(embedder.document_calls, [(self.content,)])
        self.assertEqual([hit.entry for hit in hits], [saved])
        self.assertEqual(hits[0].entry.source, self.source)
        self.assertEqual(self.file_snapshot(), before)

    async def test_content_changed_during_embedding_is_rejected_as_changed_definition(self):
        saved = self.store.remember(self.scope, self.source, self.draft)
        query = "学习示例使用什么语言？"
        embedder = BlockingEmbedder({query: (1.0, 0.0), self.content: (1.0, 0.0)})
        task = asyncio.create_task(self.store.search(
            self.scope, query, at=self.source.recorded_at,
            embedder=embedder, top_k=1, min_score=0.8,
        ))
        try:
            await asyncio.wait_for(embedder.entered.wait(), timeout=5)
            changed = json.loads(dump_entry(saved))
            changed["draft"]["content"] = "等待期间被外部修改的记忆正文。"
            with closing(sqlite3.connect(self.path)) as conn:
                conn.execute("UPDATE entries SET payload = ? WHERE memory_id = ?",
                             (json.dumps(changed, ensure_ascii=False), saved.memory_id))
                conn.commit()
            # 先确认篡改后仍是可解码记录；最终错误须揭露 await 前后定义改变。
            current = self.store.get(self.scope, saved.memory_id)
            self.assertEqual(current.draft.content, changed["draft"]["content"])
            self.assertEqual(current.source, self.source)
            embedder.release.set()
            with self.assertRaises(MemoryDataError):
                await asyncio.wait_for(task, timeout=5)
            self.assertEqual(embedder.document_calls, [(self.content,)])
        finally:
            embedder.release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
