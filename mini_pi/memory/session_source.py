"""助手准备：从真实 JSONL 会话读取来源；不执行工具或决定记忆准入。

record_index 是 read_session_records 返回的非空记录序号（从 0 开始），
不是物理行号。来源标识适用于同一路径中追加保存的记录；搬迁文件、
重排记录不是透明操作。scope 由可信调用方提供，旧 Session 本身没有
用户认证字段，本适配器不会凭文件内容证明作者身份。
"""

import hashlib
import json
import os
from pathlib import Path

from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.models import MemoryScope, MemorySource
from mini_pi.session_records import read_session_records


def read_memory_source(
    path: str | Path, record_index: int, scope: MemoryScope,
) -> MemorySource:
    """读取已保存原文与实际角色；来源许可仍由 validate_draft 判断。"""
    if type(record_index) is not int or record_index < 0:
        raise MemoryPolicyError("record_index 必须是从 0 开始的整数，不能是布尔值")
    if not isinstance(scope, MemoryScope) or any(
        not isinstance(value, str) or not value.strip()
        for value in (scope.user_id, scope.project_id)
    ):
        raise MemoryPolicyError("来源 scope 必须包含非空 user_id/project_id")
    source_path = Path(path).expanduser().resolve(strict=True)
    try:
        records = read_session_records(source_path)
    except (ValueError, TypeError) as error:
        raise MemoryPolicyError(f"无法采用无效会话记录：{error}") from error
    if record_index >= len(records):
        raise MemoryPolicyError("record_index 超出已保存会话记录范围")
    record = records[record_index]
    data = record["data"]
    if record["type"] == "message":
        role = data["role"]
        text = data["content"]
    elif record["type"] == "tool_result":
        role = "tool"
        try:
            # 保存完整结果状态，不能只取 output 而丢失 error/工具/调用 ID。
            text = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (ValueError, TypeError) as error:
            raise MemoryPolicyError("工具结果不能编码为可靠的来源 JSON") from error
    else:
        raise MemoryPolicyError("run_start/run_end 是运行事件，没有可导入的记忆正文")
    identity = {
        "path": os.path.normcase(str(source_path)),
        "run_id": record["run_id"],
        "record_index": record_index,
    }
    source_id = hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return MemorySource(
        source_id=source_id, scope=scope, role=role, text=text,
        recorded_at=record["timestamp"],
    )
