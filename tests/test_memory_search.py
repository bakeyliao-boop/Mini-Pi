"""MEM-03 向量召回行为合同：固定向量替身与真实 SQLite 验证。

助手准备的 FixedEmbedder 只映射固定文本到向量，用于检验过滤、余弦、
排序、失败及取消流程；它不是语义模型，测试通过不能证明真实语义质量。
真实 SQLite 记录承担范围、版本、撤回、来源和只读边界的验证。
"""

import asyncio
from contextlib import closing, suppress
from dataclasses import replace
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from mini_pi.memory.codec import dump_entry, dump_source
from mini_pi.memory.embedding import EmbeddingSpec
from mini_pi.memory.errors import MemoryDataError, MemoryEmbeddingError
from mini_pi.memory.models import MemoryDraft, MemoryHit, MemoryScope, MemorySource
from mini_pi.memory.sqlite_backend import SQLiteMemoryBackend
from mini_pi.memory.store import MemoryStore


_UNSET = object()


class FixedEmbedder:
    """明确指定每段文本的向量，同时保存实际调用轨迹；不模拟语义理解。"""

    def __init__(self, vectors):
        self.vectors = vectors
        self._spec = EmbeddingSpec('fixed-test-model', 'revision-1', 2)
        self.query_calls = []
        self.document_calls = []

    @property
    def spec(self):
        return self._spec

    async def embed_query(self, text):
        self.query_calls.append(text)
        return self.vectors[text]

    async def embed_documents(self, texts):
        self.document_calls.append(tuple(texts))
        return [self.vectors[text] for text in texts]


class BlockingEmbedder(FixedEmbedder):
    """在所选实际 await 暂停，让另一连接修改主记录或让调用方取消。"""

    def __init__(self, vectors, *, stage='documents'):
        super().__init__(vectors)
        self.stage = stage
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.exited = asyncio.Event()
        self.cancelled = False

    async def _pause(self):
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.exited.set()

    async def embed_query(self, text):
        result = await super().embed_query(text)
        if self.stage == 'query':
            await self._pause()
        return result

    async def embed_documents(self, texts):
        result = await super().embed_documents(texts)
        if self.stage == 'documents':
            await self._pause()
        return result


class InvalidOutputEmbedder(FixedEmbedder):
    """仅在边界测试中注入不符合端口合同的响应。"""

    def __init__(self, vectors, *, query_output=_UNSET, document_output=_UNSET):
        super().__init__(vectors)
        self.query_output = query_output
        self.document_output = document_output

    async def embed_query(self, text):
        result = await super().embed_query(text)
        return result if self.query_output is _UNSET else self.query_output

    async def embed_documents(self, texts):
        result = await super().embed_documents(texts)
        return result if self.document_output is _UNSET else self.document_output


class FailingEmbedder(FixedEmbedder):
    def __init__(self, vectors, *, stage):
        super().__init__(vectors)
        self.stage = stage
        self.failure = ConnectionError('controlled embedding transport failure')

    async def embed_query(self, text):
        result = await super().embed_query(text)
        if self.stage == 'query':
            raise self.failure
        return result

    async def embed_documents(self, texts):
        result = await super().embed_documents(texts)
        if self.stage == 'documents':
            raise self.failure
        return result


class MemorySearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix='_memory_vector_search_')
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'db' / 'memory.sqlite3'
        self.scope = MemoryScope('A', 'Pi')
        self.store = MemoryStore(self.path)
        self.at = '2026-10-19T18:00:00+08:00'
        self.query = '应该怎样给我示例？'

    def add(self, name, text='请使用 Python 示例。', *, key=None,
            scope=None, conditions=(), at=None):
        scope = self.scope if scope is None else scope
        source = MemorySource(name, scope, 'user', text,
                              at or '2026-10-19T09:00:00+08:00')
        return self.store.remember(scope, source,
            MemoryDraft(key or name, 0, len(text), source.recorded_at,
                        conditions=conditions))

    def embedder(self, entries=(), **changes):
        vectors = {self.query: (1.0, 0.0)}
        vectors.update({entry.text: (1.0, 0.0) for entry in entries})
        vectors.update(changes)
        return FixedEmbedder(vectors)

    async def search(self, embedder, **changes):
        args = dict(scope=self.scope, query=self.query, at=self.at,
                    embedder=embedder, top_k=5, min_score=0.1)
        args.update(changes)
        return await self.store.search(**args)

    def retract(self, entry, *, operation_id='withdraw'):
        source = replace(entry.source, source_id=operation_id,
                         text='撤回这项偏好。')
        return self.store.retract(self.scope, source, entry.draft.key,
            conditions=entry.draft.conditions, expected_version=entry.version,
            operation_id=operation_id)

    async def _cancel_pending(self, task):
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def paused_search(self, embedder, **changes):
        """核心提前失败时直接显示该异常，避免把接口错误伪装成等待超时。"""
        task = asyncio.create_task(self.search(embedder, **changes))
        self.addAsyncCleanup(self._cancel_pending, task)
        entered = asyncio.create_task(embedder.entered.wait())
        try:
            done, _ = await asyncio.wait(
                {task, entered}, timeout=2,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if task in done:
                result = await task
                self.fail(f'搜索在受控 embedding 返回之前已结束：{result!r}')
            self.assertIn(entered, done, '搜索没有进入受控 embedding await')
            return task
        finally:
            entered.cancel()
            with suppress(asyncio.CancelledError):
                await entered

    def source_payload(self, entry):
        with closing(sqlite3.connect(self.path)) as conn:
            return conn.execute(
                'SELECT payload FROM sources WHERE user_id=? AND project_id=? AND source_id=?',
                (entry.scope.user_id, entry.scope.project_id, entry.source.source_id),
            ).fetchone()[0]

    def set_source_payload(self, entry, payload):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                'UPDATE sources SET payload=? WHERE user_id=? AND project_id=? AND source_id=?',
                (payload, entry.scope.user_id, entry.scope.project_id, entry.source.source_id),
            )
            conn.commit()

    async def test_empty_database_scope_or_eligible_set_never_calls_embedding(self):
        fixed = self.embedder()
        self.assertEqual(await self.search(fixed), [])
        self.assertFalse(self.path.parent.exists())
        self.assertEqual(fixed.query_calls, [])
        self.assertEqual(fixed.document_calls, [])

        self.add('future', '明天才生效。', at='2026-10-20T09:00:00+08:00')
        self.assertEqual(await self.search(fixed, scope=MemoryScope('B', 'Pi')), [])
        self.assertEqual(await self.search(fixed), [])
        self.assertEqual(fixed.query_calls, [])
        self.assertEqual(fixed.document_calls, [])

    async def test_scope_time_conditions_and_retraction_filter_before_embedding(self):
        wanted = self.add('wanted', '允许送入 embedding 的正文。')
        self.add('foreign_user', '别人的私有正文。', scope=MemoryScope('B', 'Pi'))
        self.add('foreign_project', '其他项目的私有正文。', scope=MemoryScope('A', 'Other'))
        self.add('future', '未来才允许的正文。', at='2026-10-20T09:00:00+08:00')
        self.add('weekend', '条件不匹配的正文。', conditions=(('day', 'weekend'),))
        dead = self.add('dead', '已撤回的正文。')
        self.retract(dead)
        # 字典中故意没有非法候选的原文：泄漏会直接暴露，不能回退到关键词。
        fixed = self.embedder([wanted])
        hits = await self.search(fixed, conditions=(('day', 'weekday'),))
        self.assertEqual(hits, [MemoryHit(wanted, 1.0)])
        self.assertEqual(fixed.query_calls, [self.query])
        self.assertEqual(fixed.document_calls, [(wanted.text,)])

    async def test_cosine_scores_use_query_and_text_and_search_preserves_database(self):
        best = self.add('best', '没有查询关键词但由固定向量指定高分。')
        middle = self.add('middle', '第二段原始正文。')
        lexical = self.add('lexical', self.query, key='query_words_are_not_a_score')
        fixed = FixedEmbedder({self.query: (1.0, 0.0),
                               best.text: (20.0, 0.0),
                               middle.text: (4.0, 3.0)})
        # 查询与同字正文需要分别走两个端口；文档端特意给同字正文低分。
        class SeparateQueryAndDocumentEmbedder(FixedEmbedder):
            async def embed_documents(inner, texts):
                inner.document_calls.append(tuple(texts))
                return [(0.0, 2.0) if text == self.query else inner.vectors[text]
                        for text in texts]

        fixed = SeparateQueryAndDocumentEmbedder(fixed.vectors)
        before = self.path.read_bytes()
        entries_before = SQLiteMemoryBackend(self.path).read_entries(self.scope)
        hits = await self.search(fixed)
        self.assertEqual([hit.entry for hit in hits], [best, middle])
        self.assertAlmostEqual(hits[0].score, 1.0)
        self.assertAlmostEqual(hits[1].score, 0.8)
        self.assertEqual(hits[0].entry.source, best.source)
        self.assertNotIn(lexical.memory_id, [hit.entry.memory_id for hit in hits])
        self.assertEqual(fixed.query_calls, [self.query])
        self.assertEqual(fixed.document_calls,
                         [tuple(entry.text for entry in entries_before)])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(SQLiteMemoryBackend(self.path).read_entries(self.scope), entries_before)
        # 请求结束后实际取得写锁，验证短连接已释放；此处随后回滚。
        with closing(sqlite3.connect(self.path, isolation_level=None, timeout=0)) as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.rollback()

    async def test_min_score_is_inclusive_and_stable_descending_order_precedes_top_k(self):
        tied_b = self.add('b', '同分乙。')
        below = self.add('low', '低于阈值。')
        strongest = self.add('strong', '最高分。')
        tied_a = self.add('a', '同分甲。')
        fixed = FixedEmbedder({self.query: (1.0, 0.0),
                               tied_b.text: (3.0, 4.0), below.text: (0.0, 1.0),
                               strongest.text: (2.0, 0.0), tied_a.text: (3.0, 4.0)})
        hits = await self.search(fixed, min_score=0.6, top_k=3)
        self.assertEqual([hit.entry for hit in hits], [strongest, tied_a, tied_b])
        self.assertAlmostEqual(hits[1].score, 0.6)
        self.assertAlmostEqual(hits[2].score, 0.6)
        limited = await self.search(fixed, min_score=0.6, top_k=2)
        self.assertEqual([hit.entry for hit in limited], [strongest, tied_a])
        # 再次读取重新生成向量，当前方案不靠隐式缓存隐藏调用。
        self.assertEqual(fixed.query_calls, [self.query, self.query])
        self.assertEqual(len(fixed.document_calls), 2)
        self.assertEqual(await self.search(fixed, min_score=1.0, top_k=5),
                         [MemoryHit(strongest, 1.0)])

    async def test_future_v2_preserves_v1_until_its_exclusive_end_boundary(self):
        old = self.add('one', '目前使用 Python。', key='language')
        source2 = replace(old.source, source_id='two', text='以后使用 Java。')
        new = self.store.replace(self.scope, source2,
            replace(old.draft, end=len(source2.text), valid_from='2026-10-20T00:00:00+08:00'),
            expected_version=1, operation_id='update')
        old_now = self.store.get(self.scope, old.memory_id)
        before = self.embedder([old_now])
        self.assertEqual(await self.search(before), [MemoryHit(old_now, 1.0)])
        self.assertEqual(before.document_calls, [(old_now.text,)])
        boundary = self.embedder([new])
        self.assertEqual(await self.search(boundary, at='2026-10-20T00:00:00+08:00'),
                         [MemoryHit(new, 1.0)])
        self.assertEqual(boundary.document_calls, [(new.text,)])

    async def test_retract_removes_all_versions_even_for_historical_queries(self):
        old = self.add('one', '旧版本。', key='preference')
        source2 = replace(old.source, source_id='two', text='新版本。')
        new = self.store.replace(self.scope, source2,
            replace(old.draft, end=len(source2.text), valid_from='2026-10-19T12:00:00+08:00'),
            expected_version=1, operation_id='update')
        self.retract(new)
        for at in ('2026-10-19T09:00:00+08:00', self.at):
            with self.subTest(at=at):
                fixed = self.embedder()
                self.assertEqual(await self.search(fixed, at=at), [])
                self.assertEqual(fixed.query_calls, [])
                self.assertEqual(fixed.document_calls, [])
        self.assertEqual(self.store.get(self.scope, old.memory_id).state, 'retracted')
        self.assertEqual(self.store.get(self.scope, new.memory_id).state, 'retracted')

    async def test_retraction_during_embedding_is_rechecked_before_top_k(self):
        withdrawn = self.add('first', '高分但等待期间被撤回。')
        allowed = self.add('second', '仍可用的第二名。')
        fixed = BlockingEmbedder({self.query: (1.0, 0.0),
                                 withdrawn.text: (1.0, 0.0), allowed.text: (4.0, 3.0)})
        task = await self.paused_search(fixed, top_k=1)
        # 另一个真实短连接必须能完成写入，不能跨外部 await 持有旧读取事务。
        self.retract(withdrawn)
        fixed.release.set()
        hits = await task
        self.assertEqual([hit.entry for hit in hits], [allowed])
        self.assertAlmostEqual(hits[0].score, 0.8)
        self.assertTrue(fixed.exited.is_set())

    async def test_replacement_during_embedding_rechecks_validity_of_initial_candidates(self):
        old = self.add('one', '即将失效的旧偏好。', key='preference')
        fixed = BlockingEmbedder({self.query: (1.0, 0.0), old.text: (1.0, 0.0)})
        task = await self.paused_search(fixed)
        source2 = replace(old.source, source_id='two', text='等待期间生效的新偏好。')
        new = self.store.replace(self.scope, source2,
            replace(old.draft, end=len(source2.text), valid_from='2026-10-19T12:00:00+08:00'),
            expected_version=1, operation_id='update')
        fixed.release.set()
        # 新 v2 未在本次候选快照中；不把未生成向量的新记录夹入结果。
        self.assertEqual(await task, [])
        self.assertEqual(fixed.document_calls, [(old.text,)])
        self.assertEqual(self.store.get(self.scope, old.memory_id).valid_to,
                         new.draft.valid_from)

    async def test_corrupt_source_is_explicit_error_before_or_after_embedding(self):
        entry = self.add('one')
        original_payload = self.source_payload(entry)
        for when in ('before', 'during_await'):
            with self.subTest(when=when):
                fixed = BlockingEmbedder({self.query: (1.0, 0.0), entry.text: (1.0, 0.0)})
                try:
                    if when == 'before':
                        self.set_source_payload(entry, '{}')
                        with self.assertRaises(MemoryDataError):
                            await self.search(fixed)
                        self.assertEqual(fixed.query_calls, [])
                        self.assertEqual(fixed.document_calls, [])
                    else:
                        task = await self.paused_search(fixed)
                        self.set_source_payload(entry, '{}')
                        fixed.release.set()
                        with self.assertRaises(MemoryDataError):
                            await task
                finally:
                    self.set_source_payload(entry, original_payload)

    async def test_consistently_rewritten_immutable_fields_raise_explicit_data_error(self):
        for field in ('source', 'draft', 'version', 'written_at'):
            with self.subTest(field=field):
                self.path = self.path.with_name('rewritten-' + field + '.sqlite3')
                self.store = MemoryStore(self.path)
                old = self.add('a', '旧的完整原文。')
                blocked = BlockingEmbedder({self.query: (1, 0), old.text: (1, 0)}, stage='documents')
                task = await self.paused_search(blocked)
                changes = dict(
                    source=replace(old.source, text='新的完整原文。'),
                    draft=replace(old.draft, valid_from='2026-10-19T02:00:00.000000+00:00'),
                    version=2, written_at='2026-10-19T01:00:00.000000+00:00',
                )
                changed = replace(old, **{field: changes[field]})
                # 来源、索引与payload一致且可解码；必须由await后的定义复核拒绝。
                with closing(sqlite3.connect(self.path)) as conn:
                    conn.execute('UPDATE sources SET payload=? WHERE source_id=?',
                                 (dump_source(changed.source), changed.source.source_id))
                    conn.execute('UPDATE entries SET version=?, payload=? WHERE memory_id=?',
                                 (changed.version, dump_entry(changed), changed.memory_id))
                    conn.commit()
                self.assertEqual(self.store.get(self.scope, old.memory_id), changed)
                before = self.path.read_bytes()
                blocked.release.set()
                with self.assertRaisesRegex(MemoryDataError, '^计分后的记忆来源或定义发生变化$'):
                    await task
                self.assertEqual(self.store.get(self.scope, old.memory_id), changed)
                self.assertEqual(self.path.read_bytes(), before)

    async def test_invalid_query_or_document_vectors_raise_embedding_error(self):
        entry = self.add('one')
        vectors = {self.query: (1.0, 0.0), entry.text: (1.0, 0.0)}
        invalid = {'nan': (float('nan'), 1.0), 'infinity': (1.0, float('inf')),
                   'zero': (0.0, 0.0), 'wrong_dimensions': (1.0, 0.0, 0.0)}
        for stage in ('query', 'documents'):
            for label, vector in invalid.items():
                with self.subTest(stage=stage, vector=label):
                    kwargs = ({'query_output': vector} if stage == 'query'
                              else {'document_output': [vector]})
                    fixed = InvalidOutputEmbedder(vectors, **kwargs)
                    with self.assertRaises(MemoryEmbeddingError):
                        await self.search(fixed)

    async def test_document_batch_count_must_match_eligible_candidate_count(self):
        entry = self.add('one')
        vectors = {self.query: (1.0, 0.0), entry.text: (1.0, 0.0)}
        for output in ([], [(1.0, 0.0), (1.0, 0.0)]):
            with self.subTest(count=len(output)):
                fixed = InvalidOutputEmbedder(vectors, document_output=output)
                with self.assertRaises(MemoryEmbeddingError):
                    await self.search(fixed)

    async def test_model_revision_or_dimensions_cannot_change_across_either_await(self):
        entry = self.add('one')
        vectors = {self.query: (1.0, 0.0), entry.text: (1.0, 0.0)}
        for stage in ('query', 'documents'):
            for field, value in (('model_id', 'another-model'),
                                 ('revision', 'revision-2'), ('dimensions', 3)):
                with self.subTest(stage=stage, field=field):
                    fixed = BlockingEmbedder(vectors, stage=stage)
                    task = await self.paused_search(fixed)
                    fixed._spec = replace(fixed.spec, **{field: value})
                    fixed.release.set()
                    with self.assertRaises(MemoryEmbeddingError):
                        await task

    async def test_embedding_transport_failures_are_never_empty_success(self):
        entry = self.add('one')
        vectors = {self.query: (1.0, 0.0), entry.text: (1.0, 0.0)}
        for stage in ('query', 'documents'):
            with self.subTest(stage=stage):
                fixed = FailingEmbedder(vectors, stage=stage)
                # 保留底层异常或包装 RuntimeError 均可，返回 [] 不可。
                with self.assertRaises((ConnectionError, RuntimeError)):
                    await self.search(fixed)
                self.assertEqual(fixed.query_calls, [self.query])
                self.assertEqual(fixed.document_calls,
                                 [] if stage == 'query' else [(entry.text,)])

    async def test_cancellation_reaches_embedding_and_cleanup_precedes_cancelled_terminal(self):
        entry = self.add('one')
        vectors = {self.query: (1.0, 0.0), entry.text: (1.0, 0.0)}
        before = self.path.read_bytes()
        for stage in ('query', 'documents'):
            with self.subTest(stage=stage):
                fixed = BlockingEmbedder(vectors, stage=stage)
                task = await self.paused_search(fixed)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(fixed.cancelled)
                self.assertTrue(fixed.exited.is_set())
                self.assertTrue(task.cancelled())
                self.assertEqual(self.path.read_bytes(), before)
                self.assertEqual(self.store.get(self.scope, entry.memory_id), entry)


if __name__ == '__main__':
    unittest.main()
