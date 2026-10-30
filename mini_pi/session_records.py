"""助手准备：D11 的记录读取、结构校验与加载结果容器。"""

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path

from mini_pi.models import ConversationItem


@dataclass
class LoadedSession:
    """history 用于对话；records 保留事件和运行信息供恢复检查。"""

    history: list[ConversationItem]
    records: list[dict[str, object]]
    session_id: str | None = None

def find_session_id(records):
    session_id = None  # 先假设这是还没有编号的旧会话

    for record in records:  # 按顺序查看会话记录
        if not isinstance(record, dict):  # 每条记录都应是字典
            raise ValueError("会话记录必须是字典")
        if record.get("type") != "session_identity":  # 只处理会话编号记录
            continue
        if session_id is not None:  # 不允许同一会话出现两条编号记录
            raise ValueError("会话包含重复的编号记录")

        data = record.get("data")  # 读取这条记录的内容
        if not isinstance(data, dict):  # 内容必须是字典
            raise ValueError("会话编号记录格式不正确")
        value = data.get("session_id")  # 取出固定的会话编号
        if not isinstance(value, str) or not value.strip():  # 编号不能为空
            raise ValueError("会话编号必须是非空字符串")
        session_id = value  # 保存找到的编号

    return session_id  # 没找到时返回 None

def find_compaction_record(records):
    found = None

    for index,record in enumerate(records):
        if record['type'] != 'compaction':
            continue
        if found is not None:
            raise ValueError('会话包含多条摘要记录')
        found = (index,record)

    return found


def _text(data: dict, key: str, nonempty: bool = False) -> None:
    value = data.get(key)
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise ValueError(f"{key} 必须是{'非空' if nonempty else ''}字符串")

def check_compaction_data(data):
    if not isinstance(data,dict):
        raise ValueError('摘要记录内容必须是字典')

    required = {'summary','session_id','history_count','cut_index','history_fingerprint'}
    if set(data) != required:
        raise ValueError('摘要记录字段不正确')

    _text(data, "summary", nonempty=True)  # 摘要文字不能为空
    _text(data, "session_id", nonempty=True)  # 会话编号不能为空
    _text(data, "history_fingerprint", nonempty=True)  # 历史指纹不能为空

    count = data['history_count']
    cut = data['cut_index']
    if type(count) is not int or count < 2:
        raise ValueError('摘要历史条数不正确')
    if type(cut) is not int or not 0 < cut < count:
        raise ValueError('摘要切点不正确')

    fingerprint = data['history_fingerprint']
    if len(fingerprint) != 64 or any(char not in '0123456789abcdef' for char in fingerprint):
        raise ValueError('历史指纹格式不正确')

def _validate_record(record: object) -> None:
    if not isinstance(record, dict):
        raise ValueError("记录必须是 JSON 对象")
    event_type = record.get("type")
    if event_type not in ("run_start", "message", "tool_result", "run_end", "session_identity", "compaction"):
        raise ValueError("不支持的记录类型")
    _text(record, "run_id", nonempty=True)
    _text(record, "timestamp", nonempty=True)
    if datetime.fromisoformat(record["timestamp"]).tzinfo is None:
        raise ValueError("timestamp 必须包含时区")
    data = record.get("data")
    if not isinstance(data, dict):
        raise ValueError("data 必须是 JSON 对象")
    if event_type == "message":
        _text(data, "role", nonempty=True)
        _text(data, "content")
        if data["role"] not in ("system", "user", "assistant"):
            raise ValueError("不支持的消息角色")
        calls = data.get("tool_calls", [])
        if not isinstance(calls, list):
            raise ValueError("tool_calls 必须是列表")
        if calls and data["role"] != "assistant":
            raise ValueError("只有 assistant 消息可以包含工具调用")
        for call in calls:
            required_fields = {"id", "name", "arguments"}
            allowed_fields = required_fields | {"raw_arguments"}
            if (
                not isinstance(call, dict)
                or not required_fields <= set(call)
                or set(call) - allowed_fields
            ):
                raise ValueError("调用必须包含 id、name 和 arguments")
            _text(call, "id", nonempty=True)
            _text(call, "name", nonempty=True)
            raw_arguments = call.get("raw_arguments")
            if raw_arguments is not None and not isinstance(raw_arguments, str):
                raise ValueError("raw_arguments 必须是字符串或 null")
            if call["arguments"] is None:
                if data.get("stop_reason") not in ("length", "error", "aborted") or not isinstance(raw_arguments, str):
                    raise ValueError("未解析参数只允许用于带有原文的 length/error/aborted 消息")
            elif not isinstance(call["arguments"], dict):
                raise ValueError("arguments 必须是字典")
    elif event_type == "tool_result":
        _text(data, "tool_call_id", nonempty=True)
        _text(data, "tool_name", nonempty=True)
        _text(data, "output")
        if data.get("error") is not None and not isinstance(data["error"], str):
            raise ValueError("error 必须是字符串或 null")

    elif event_type == "session_identity":
        _text(data,"session_id",nonempty=True)
    elif event_type == "compaction":
        check_compaction_data(data)  # 只验证单条记录格式，历史绑定留给恢复检查

    else:
        _text(data, "status", nonempty=True)
        if data.get("task_passed") is not None and type(data["task_passed"]) is not bool:
            raise ValueError("task_passed 必须是布尔值或 null")


def read_session_records(path: Path) -> list[dict[str, object]]:
    """读取并校验每行；坏记录报出行号，不静默丢弃调用证据。"""
    records = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                _validate_record(record)
            except (ValueError, TypeError) as error:
                raise ValueError(f"会话第 {line_number} 行无效：{error}") from error
            records.append(record)
    find_session_id(records)
    return records
