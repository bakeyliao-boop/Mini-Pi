"""MEM-01/02：记忆写入、版本更新与撤回决策；数据库细节由辅助层提供。"""

from dataclasses import replace as replace_fields
from pathlib import Path

from mini_pi.memory.codec import candidate_id, make_entry, normalize_draft, normalize_source
from mini_pi.memory.errors import MemoryConflict, MemoryDataError, MemoryEmbeddingError, MemoryPolicyError
from mini_pi.memory.models import Conditions, MemoryDraft, MemoryEntry, MemoryHit, MemoryScope, MemorySource
from mini_pi.memory.embedding import Embedder, cosine_similarity, normalize_document_vectors, unit_vector
from mini_pi.memory.operation_codec import (
    make_replace_receipt, replacement_fingerprint, validate_operation_input,
    make_retract_receipt, retraction_fingerprint, validate_retraction_shape,
)
from mini_pi.memory.policy import validate_draft
from mini_pi.memory.sqlite_backend import SQLiteMemoryBackend
from mini_pi.memory.validation_helpers import normalize_conditions
from mini_pi.memory.retrieval import is_usable
from mini_pi.memory.retrieval_helpers import normalize_search_request, normalize_vector_search_request


class MemoryStore:
    def __init__(self, path: str | Path):
        # 助手准备：仅登记路径，不能在业务门禁之前创建数据库。
        self._backend = SQLiteMemoryBackend(path)

    def remember(
        self, scope: MemoryScope, source: MemorySource, draft: MemoryDraft,
    ) -> MemoryEntry:
        """核验、重试去重和首次写入；本单元不自动覆盖已有记忆。"""
        validate_draft(scope,source,draft)
        source = normalize_source(source)
        draft = normalize_draft(draft)
        memory_id = candidate_id(scope,source,draft)

        with self._backend.transaction() as conn:
            stored_source = self._backend.get_source(
                conn, scope, source.source_id,
            )
            if stored_source is not None and stored_source != source:
                raise MemoryConflict("同一来源编号的原始记录发生变化")

            existing = self._backend.find_candidate(conn, scope, memory_id)
            if existing is not None:
                if existing.source != source or existing.draft != draft:
                    raise MemoryConflict("同一候选的来源或定义发生变化")
                return existing

            latest = self._backend.latest_entry(
                conn,scope,draft.key,draft.conditions,)  #查看最新的内容是否已经有存档
            if latest is not None:
                raise MemoryConflict("该属性已有记忆，请使用显式更新")
            entry = make_entry(scope,source,draft,version=1,state="active")
            if stored_source is None:
                self._backend.insert_source(conn, source)
            self._backend.insert_entry(conn,entry)
            return entry


    def replace(
        self, scope: MemoryScope, source: MemorySource, draft: MemoryDraft,
        *, expected_version: int, operation_id: str,
    ) -> MemoryEntry:
        """MEM-02：显式版本替换；回执、版本与状态决策。"""
        validate_draft(scope,source,draft)
        validate_operation_input(expected_version,operation_id)
        source = normalize_source(source)
        draft = normalize_draft(draft)
        request_hash = replacement_fingerprint(
            scope,source,draft,expected_version,
            )

        with self._backend.transaction() as conn:
            receipt = self._backend.get_receipt(conn, scope, operation_id)
            if receipt is not None:
                if receipt.action != "replace" or receipt.request_hash != request_hash:
                    raise MemoryConflict("同一操作编号不能改换请求")
                existing = self._backend.find_candidate(
                    conn, scope, receipt.result_memory_id,
                )
                if (
                    existing is None
                    or receipt.expected_version != expected_version
                    or existing.version != expected_version + 1
                    or existing.source != source
                    or existing.draft != draft
                ):
                    raise MemoryDataError("回执结果与本次请求不一致")
                return existing

            latest = self._backend.latest_entry(
                conn, scope, draft.key, draft.conditions,
            )
            if latest is None or latest.version != expected_version:
                raise MemoryConflict("目标系列不存在或版本已变化")
            if latest.state != "active":
                raise MemoryConflict("当前系列状态不允许更新")
            if latest.draft.kind != draft.kind:
                raise MemoryConflict("更新不能改变记忆类型")
            if draft.valid_from <= latest.draft.valid_from:
                raise MemoryConflict("新版本生效时间必须晚于上一版本")

            stored_source = self._backend.get_source(conn, scope, source.source_id)
            if stored_source is not None and stored_source != source:
                raise MemoryConflict("同一来源编号的原始记录发生变化")
            memory_id = candidate_id(scope, source, draft)
            if self._backend.find_candidate(conn, scope, memory_id) is not None:
                raise MemoryConflict("新版本不能复用已有来源候选")

            previous = replace_fields(
                latest, state="superseded", valid_to=draft.valid_from,
            )
            entry = make_entry(
                scope, source, draft, version=latest.version + 1, state="active",
            )
            receipt = make_replace_receipt(  # 构造本次更新的操作回执
                operation_id, request_hash, expected_version, entry,
            )
            if stored_source is None:
                self._backend.insert_source(conn, source)
            self._backend.update_entry(conn, previous)
            self._backend.insert_entry(conn, entry)
            self._backend.insert_receipt(conn, receipt)
            return entry

    def retract(
        self, scope: MemoryScope, source: MemorySource, key: str,
        *, conditions: Conditions = (), expected_version: int, operation_id: str,
    ) -> MemoryEntry:
        """MEM-02：整系列立即撤回。"""
        validate_retraction_shape(    #step1 准备撤回请求
            scope, source, key, conditions, expected_version, operation_id,
        )
        if source.scope != scope:
            raise MemoryPolicyError("撤回指令不属于当前用户或项目")
        if source.role != "user":
            raise MemoryPolicyError("只接受用户的明确撤回指令")

        source = normalize_source(source)
        conditions = normalize_conditions(conditions)
        request_hash = retraction_fingerprint(
            scope, source, key, conditions, expected_version,
        )

        with self._backend.transaction() as conn:    #step2 判断本次操作是否已经执行过
            receipt = self._backend.get_receipt(conn, scope, operation_id)
            if receipt is not None:
                if receipt.action != "retract" or receipt.request_hash != request_hash:
                    raise MemoryConflict("同一操作编号不能改换请求")

                existing = self._backend.find_candidate(
                    conn, scope, receipt.result_memory_id,
                )
                if (
                    receipt.expected_version != expected_version
                    or receipt.source != source
                    or receipt.key != key
                    or receipt.conditions != conditions
                    or existing is None
                    or existing.version != expected_version
                    or existing.state != "retracted"
                ):
                    raise MemoryDataError("撤回回执与结果不一致")
                return existing

            latest = self._backend.latest_entry(  #step3 首次撤回前检查
                conn, scope, key, conditions,
            )
            if latest is None or latest.version != expected_version:
                raise MemoryConflict("目标系列不存在或版本已变化")
            if latest.state != "active":
                raise MemoryConflict("当前系列状态不允许首次撤回")

            stored_source = self._backend.get_source(
                conn, scope, source.source_id,
            )
            if stored_source is not None and stored_source != source:
                raise MemoryConflict("同一来源编号的原始记录发生变化")

            entries = self._backend.entries_for_series(  #step4 真正撤回并保存回执
                conn, scope, key, conditions,
            )
            result = replace_fields(latest, state="retracted")
            receipt = make_retract_receipt(
                operation_id, request_hash, expected_version, source, result,
            )

            if stored_source is None:
                self._backend.insert_source(conn, source)
            for entry in entries:
                withdrawn = replace_fields(entry, state="retracted")
                self._backend.update_entry(conn, withdrawn)
            self._backend.insert_receipt(conn, receipt)
            return result

    async def search(
        self, scope: MemoryScope, query: str, *,
        at: str, embedder: Embedder,
        conditions: Conditions = (), top_k: int = 5,
        min_score: float,
    ) -> list[MemoryHit]:
        """自然语言查询；先读取并筛选允许使用的候选。"""
        conditions, at, query, top_k, min_score = normalize_vector_search_request(
            scope, conditions, at, query, top_k, min_score,
        )
        candidates = self._backend.read_entries(scope)

        eligible = []
        for entry in candidates:
            if not is_usable(entry, scope, conditions=conditions, at=at):
                continue
            eligible.append(entry)

        if not eligible:
            return []
        spec = embedder.spec
        query_vector = await embedder.embed_query(query)
        if embedder.spec != spec:
            raise MemoryEmbeddingError("问题向量返回时模型规格发生变化")

        query_vector = unit_vector(query_vector,spec.dimensions)

        texts = [entry.text for entry in eligible]
        document_vectors = await embedder.embed_documents(texts)
        if embedder.spec != spec:
            raise MemoryEmbeddingError("候选向量返回时模型规格发生变化")

        document_vectors = normalize_document_vectors(
            document_vectors, len(eligible), spec.dimensions,
        )

        scored = []
        for entry, vector in zip(eligible, document_vectors):
            score = cosine_similarity(
                query_vector, vector, spec.dimensions,
            )
            scored.append(MemoryHit(entry, score))

        current_by_id = {
            entry.memory_id: entry
            for entry in self._backend.read_entries(scope)
        }
        verified = []
        for hit in scored:
            current = current_by_id.get(hit.entry.memory_id)
            if current is None:
                continue
            if (
                current.source != hit.entry.source
                or current.draft != hit.entry.draft
                or current.version != hit.entry.version
                or current.written_at != hit.entry.written_at
            ):
                raise MemoryDataError("计分后的记忆来源或定义发生变化")
            if not is_usable(current, scope, conditions=conditions, at=at):
                continue
            verified.append(MemoryHit(current, hit.score))

        selected = []
        for hit in verified:
            if hit.score >= min_score:
                selected.append(hit)
        selected.sort(key=lambda hit: hit.score,reverse=True)
        return selected[:top_k]

    def latest(
        self, scope: MemoryScope, key: str, *, conditions: Conditions = (),
    ) -> MemoryEntry | None:
        """助手准备：取得规划时的最高持久版本；实际变更仍须事务内重查。"""
        return self._backend.read_latest(scope, key, conditions)

    def get(self, scope: MemoryScope, memory_id: str) -> MemoryEntry | None:
        """助手准备：按范围读回已存版本供核对，不判定该版本当前是否可用。"""
        return self._backend.read_entry(scope, memory_id)
