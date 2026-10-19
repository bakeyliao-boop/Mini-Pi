"""助手准备：操作参数、规范请求指纹与回执的严格 JSON 表示。

这里不判断旧版本能否替换、事实何时生效，也不执行数据库或工具操作。
"""

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import re

from mini_pi.memory.codec import (
    _fields, _json, _parse, _read_scope, _read_source, _scope, _scope_dict,
    _source_dict, dump_entry, load_entry, normalize_draft, normalize_source,
)
from mini_pi.memory.errors import MemoryDataError, MemoryPolicyError
from mini_pi.memory.models import (
    Conditions, MemoryDraft, MemoryEntry, MemoryReceipt, MemoryScope, MemorySource,
)
from mini_pi.memory.validation_helpers import (
    normalize_conditions, normalize_time, require_text,
)


def validate_operation_input(expected_version: int, operation_id: str) -> None:
    """只校验输入形状；不比较数据库中的实际版本。"""
    if type(expected_version) is not int or expected_version < 1:
        raise MemoryPolicyError("expected_version 必须是正整数，不能使用布尔值")
    require_text(operation_id, "operation_id")


def replacement_fingerprint(
    scope: MemoryScope, source: MemorySource, draft: MemoryDraft,
    expected_version: int,
) -> str:
    """完整更新请求的稳定指纹；操作编号不属于请求内容。

    保留原文和身份标识，只规范时间和条件顺序；角色准入与完整原文
    仍由 policy 判断，不在指纹工具中隐含更新或撤回策略。
    """
    _scope(scope)
    source = normalize_source(source)
    draft = normalize_draft(draft)
    validate_operation_input(expected_version, "fingerprint")
    if source.scope != scope:
        raise MemoryPolicyError("来源 scope 与请求 scope 不一致")
    request = {
        "action": "replace", "scope": _scope_dict(scope),
        "source": _source_dict(source),
        "draft": {
            "key": draft.key, "start": draft.start, "end": draft.end,
            "valid_from": draft.valid_from, "kind": draft.kind,
            "conditions": draft.conditions,
        },
        "expected_version": expected_version,
    }
    return hashlib.sha256(_json(request).encode("utf-8")).hexdigest()


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise MemoryPolicyError(f"{name} 必须是 64 位小写十六进制字符串")
    return value


def validate_retraction_shape(
    scope: MemoryScope, source: MemorySource, key: str, conditions: Conditions,
    expected_version: int, operation_id: str,
) -> None:
    """助手准备：仅校验格式，不决定来源角色、范围准入或数据库版本。"""
    _scope(scope)
    source = normalize_source(source)
    require_text(source.text, "撤回指令原文")
    require_text(key, "记忆属性名")
    normalize_conditions(conditions)
    validate_operation_input(expected_version, operation_id)


def retraction_fingerprint(
    scope: MemoryScope, source: MemorySource, key: str, conditions: Conditions,
    expected_version: int,
) -> str:
    """完整撤回请求的规范指纹；不包含操作编号，不检查已存状态。"""
    validate_retraction_shape(scope, source, key, conditions, expected_version, "fingerprint")
    request = {
        "action": "retract", "scope": _scope_dict(scope),
        "source": _source_dict(normalize_source(source)),
        "key": key, "conditions": normalize_conditions(conditions),
        "expected_version": expected_version,
    }
    return hashlib.sha256(_json(request).encode("utf-8")).hexdigest()


def make_retract_receipt(
    operation_id: str, request_hash: str, expected_version: int,
    source: MemorySource, entry: MemoryEntry, *, written_at: str | None = None,
) -> MemoryReceipt:
    """装配撤回回执：指令来源独立于原偏好来源，不执行撤回或递增版本。"""
    entry = load_entry(dump_entry(entry))
    if written_at is None:
        written_at = datetime.now(UTC).isoformat(timespec="microseconds")
    return _normalize_receipt(MemoryReceipt(
        scope=entry.scope, operation_id=operation_id, action="retract",
        request_hash=request_hash, key=entry.draft.key,
        conditions=entry.draft.conditions, expected_version=expected_version,
        result_memory_id=entry.memory_id, result_version=entry.version,
        source=source, written_at=written_at,
    ))


def _normalize_receipt(receipt: MemoryReceipt) -> MemoryReceipt:
    if not isinstance(receipt, MemoryReceipt):
        raise MemoryPolicyError("receipt 必须是 MemoryReceipt")
    _scope(receipt.scope)
    validate_operation_input(receipt.expected_version, receipt.operation_id)
    if receipt.action not in ("replace", "retract"):
        raise MemoryPolicyError("不支持的记忆操作")
    _digest(receipt.request_hash, "request_hash")
    _digest(receipt.result_memory_id, "result_memory_id")
    require_text(receipt.key, "key")
    if type(receipt.result_version) is not int or receipt.result_version < 1:
        raise MemoryPolicyError("result_version 必须是正整数，不能使用布尔值")
    source = normalize_source(receipt.source)
    if source.scope != receipt.scope:
        raise MemoryPolicyError("回执来源 scope 与回执 scope 不一致")
    return replace(
        receipt, source=source,
        conditions=normalize_conditions(receipt.conditions),
        written_at=normalize_time(receipt.written_at),
    )


def make_replace_receipt(
    operation_id: str, request_hash: str, expected_version: int,
    entry: MemoryEntry, *, written_at: str | None = None,
) -> MemoryReceipt:
    """从调用方给定 Entry 装配回执，不递增版本或修改其状态。"""
    # 复用既有容器格式验证；这里不读取存储、不执行来源准入和状态迁移。
    entry = load_entry(dump_entry(entry))
    if written_at is None:
        written_at = datetime.now(UTC).isoformat(timespec="microseconds")
    return _normalize_receipt(MemoryReceipt(
        scope=entry.scope, operation_id=operation_id, action="replace",
        request_hash=request_hash, key=entry.draft.key,
        conditions=entry.draft.conditions, expected_version=expected_version,
        result_memory_id=entry.memory_id, result_version=entry.version,
        source=entry.source, written_at=written_at,
    ))


def dump_receipt(receipt: MemoryReceipt) -> str:
    receipt = _normalize_receipt(receipt)
    return _json({
        "scope": _scope_dict(receipt.scope),
        "operation_id": receipt.operation_id, "action": receipt.action,
        "request_hash": receipt.request_hash, "key": receipt.key,
        "conditions": receipt.conditions,
        "expected_version": receipt.expected_version,
        "result_memory_id": receipt.result_memory_id,
        "result_version": receipt.result_version,
        "source": _source_dict(receipt.source),
        "written_at": receipt.written_at,
    })


def load_receipt(payload: str) -> MemoryReceipt:
    try:
        data = _fields(_parse(payload), {
            "scope", "operation_id", "action", "request_hash", "key",
            "conditions", "expected_version", "result_memory_id",
            "result_version", "source", "written_at",
        }, "receipt")
        raw_conditions = data["conditions"]
        if not isinstance(raw_conditions, list) or any(
            not isinstance(item, list) or len(item) != 2 for item in raw_conditions
        ):
            raise MemoryDataError("conditions 必须是二元数组列表")
        return _normalize_receipt(MemoryReceipt(**{
            **data,
            "scope": _read_scope(data["scope"]),
            "source": _read_source(data["source"]),
            "conditions": tuple(tuple(item) for item in raw_conditions),
        }))
    except (MemoryPolicyError, TypeError, OverflowError, RecursionError) as error:
        raise MemoryDataError(f"操作回执 payload 无效：{error}") from error
