"""助手准备：记忆容器的规范化、稳定标识与严格 JSON 编解码。

这里只检查存储表示，不代替 policy 的来源许可、完整片段与写入决策。
"""

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json

from mini_pi.memory.errors import MemoryDataError, MemoryPolicyError
from mini_pi.memory.models import MemoryDraft, MemoryEntry, MemoryScope, MemorySource
from mini_pi.memory.validation_helpers import normalize_conditions, normalize_time


def _text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise MemoryPolicyError(f"{name} 必须是{'字符串' if allow_empty else '非空字符串'}")
    return value


def _scope(scope: MemoryScope) -> MemoryScope:
    if not isinstance(scope, MemoryScope):
        raise MemoryPolicyError("scope 必须是 MemoryScope")
    _text(scope.user_id, "user_id")
    _text(scope.project_id, "project_id")
    return scope


def normalize_source(source: MemorySource) -> MemorySource:
    """保留来源原文及身份标识；只将 recorded_at 统一到 UTC。"""
    if not isinstance(source, MemorySource):
        raise MemoryPolicyError("source 必须是 MemorySource")
    _scope(source.scope)
    _text(source.source_id, "source_id")
    _text(source.role, "role")
    _text(source.text, "text", allow_empty=True)
    return replace(source, recorded_at=normalize_time(source.recorded_at))


def normalize_draft(draft: MemoryDraft) -> MemoryDraft:
    """规范化时间和条件；不判断角色是否允许、片段是否完整。"""
    if not isinstance(draft, MemoryDraft):
        raise MemoryPolicyError("draft 必须是 MemoryDraft")
    _text(draft.key, "key")
    if type(draft.start) is not int or type(draft.end) is not int:
        raise MemoryPolicyError("start/end 必须是整数")
    if draft.start < 0 or draft.end < draft.start:
        raise MemoryPolicyError("片段位置必须满足 0 <= start <= end")
    if draft.kind not in ("semantic", "episodic", "procedural"):
        raise MemoryPolicyError("不支持的记忆类型")
    return replace(
        draft,
        valid_from=normalize_time(draft.valid_from),
        conditions=normalize_conditions(draft.conditions),
    )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _scope_dict(scope: MemoryScope) -> dict:
    return {"user_id": scope.user_id, "project_id": scope.project_id}


def candidate_id(scope: MemoryScope, source: MemorySource, draft: MemoryDraft) -> str:
    """同一来源候选的稳定 SHA-256；生效时间和来源正文不进入标识。

    因而来源内容被改写、同候选改时间，都必须由核心比较并拒绝冲突；
    不能依靠生成一个新 ID 绕开此前的已存或撤回状态。
    """
    _scope(scope)
    source = normalize_source(source)
    draft = normalize_draft(draft)
    if source.scope != scope:
        raise MemoryPolicyError("来源 scope 与候选 scope 不一致")
    identity = {
        "scope": _scope_dict(scope),
        "source_id": source.source_id,
        "key": draft.key,
        "start": draft.start,
        "end": draft.end,
        "kind": draft.kind,
        "conditions": draft.conditions,
    }
    return hashlib.sha256(_json(identity).encode("utf-8")).hexdigest()


def make_entry(
    scope: MemoryScope,
    source: MemorySource,
    draft: MemoryDraft,
    *,
    version: int = 1,
    state: str = "active",
    valid_to: str | None = None,
    written_at: str | None = None,
) -> MemoryEntry:
    """装配容器；版本号和状态来自调用方，不自动递增或重新激活。"""
    source = normalize_source(source)
    draft = normalize_draft(draft)
    memory_id = candidate_id(scope, source, draft)
    if draft.end > len(source.text):
        raise MemoryPolicyError("片段 end 超出来源原文")
    if type(version) is not int or version < 1:
        raise MemoryPolicyError("version 必须是正整数")
    if state not in ("active", "superseded", "retracted"):
        raise MemoryPolicyError("不支持的记忆状态")
    normalized_end = None if valid_to is None else normalize_time(valid_to)
    if normalized_end is not None and normalized_end < draft.valid_from:
        raise MemoryPolicyError("valid_to 不能早于 valid_from")
    if written_at is None:
        written_at = datetime.now(UTC).isoformat(timespec="microseconds")
    return MemoryEntry(
        memory_id=memory_id, scope=scope, source=source, draft=draft,
        version=version, state=state, written_at=normalize_time(written_at),
        valid_to=normalized_end,
    )


def _source_dict(source: MemorySource) -> dict:
    return {
        "source_id": source.source_id, "scope": _scope_dict(source.scope),
        "role": source.role, "text": source.text, "recorded_at": source.recorded_at,
    }


def dump_source(source: MemorySource) -> str:
    return _json(_source_dict(normalize_source(source)))


def dump_entry(entry: MemoryEntry) -> str:
    if not isinstance(entry, MemoryEntry):
        raise MemoryPolicyError("entry 必须是 MemoryEntry")
    if not isinstance(entry.written_at, str):
        raise MemoryPolicyError("已构造 entry 的 written_at 必须是明确时间")
    normalized = make_entry(
        entry.scope, entry.source, entry.draft, version=entry.version, state=entry.state,
        valid_to=entry.valid_to, written_at=entry.written_at,
    )
    if entry.memory_id != normalized.memory_id:
        raise MemoryPolicyError("memory_id 与来源候选不匹配")
    draft = normalized.draft
    return _json({
        "memory_id": normalized.memory_id,
        "scope": _scope_dict(normalized.scope),
        "source": _source_dict(normalized.source),
        "draft": {
            "key": draft.key, "start": draft.start, "end": draft.end,
            "valid_from": draft.valid_from, "kind": draft.kind,
            "conditions": draft.conditions,
        },
        "version": normalized.version, "state": normalized.state,
        "written_at": normalized.written_at, "valid_to": normalized.valid_to,
    })


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise MemoryDataError(f"JSON 出现重复字段：{key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise MemoryDataError(f"JSON 出现非有限数：{value}")


def _parse(payload: str) -> object:
    if not isinstance(payload, str):
        raise MemoryDataError("payload 必须是 JSON 字符串")
    try:
        return json.loads(payload, object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)
    except (ValueError, TypeError, RecursionError) as error:
        raise MemoryDataError(f"记忆 JSON 无法还原：{error}") from error


def _fields(value: object, expected: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise MemoryDataError(f"{label} 字段不完整或包含未知字段")
    return value


def _read_scope(value: object) -> MemoryScope:
    data = _fields(value, {"user_id", "project_id"}, "scope")
    return _scope(MemoryScope(**data))


def _read_source(value: object) -> MemorySource:
    data = _fields(value, {"source_id", "scope", "role", "text", "recorded_at"}, "source")
    return normalize_source(MemorySource(**{**data, "scope": _read_scope(data["scope"])}))


def load_source(payload: str) -> MemorySource:
    try:
        return _read_source(_parse(payload))
    except (MemoryPolicyError, TypeError, OverflowError, RecursionError) as error:
        raise MemoryDataError(f"来源 payload 无效：{error}") from error


def load_entry(payload: str) -> MemoryEntry:
    try:
        data = _fields(_parse(payload), {
            "memory_id", "scope", "source", "draft", "version", "state", "written_at", "valid_to",
        }, "entry")
        raw_draft = _fields(data["draft"], {
            "key", "start", "end", "valid_from", "kind", "conditions",
        }, "draft")
        raw_conditions = raw_draft["conditions"]
        if not isinstance(raw_conditions, list) or any(
            not isinstance(item, list) or len(item) != 2 for item in raw_conditions
        ):
            raise MemoryDataError("conditions 必须是二元数组列表")
        if not isinstance(data["written_at"], str):
            raise MemoryDataError("已保存 written_at 必须是明确的时间字符串")
        draft = MemoryDraft(**{
            **raw_draft, "conditions": tuple(tuple(item) for item in raw_conditions),
        })
        result = make_entry(
            _read_scope(data["scope"]), _read_source(data["source"]), draft,
            version=data["version"], state=data["state"],
            valid_to=data["valid_to"], written_at=data["written_at"],
        )
        if data["memory_id"] != result.memory_id:
            raise MemoryDataError("已保存 memory_id 与来源候选不匹配")
        return result
    except (MemoryPolicyError, TypeError, OverflowError, RecursionError) as error:
        raise MemoryDataError(f"记忆 payload 无效：{error}") from error
