"""D11：识别没有配对结果的历史调用，不执行工具。"""

from dataclasses import dataclass

from mini_pi.models import ToolCall
from mini_pi.session_records import LoadedSession


@dataclass(frozen=True)
class PendingCall:
    """缺少记录结果的调用；不能据此判断它是否实际执行过。"""

    run_id: str
    call: ToolCall


def _validate_pairing(records: list[dict[str, object]]) -> None:
    """助手准备：拒绝重复、孤立或工具名错配，避免掩盖待核对写入。"""
    seen_calls = {}
    completed = set()
    for record_number, record in enumerate(records, start=1):
        run_id = record["run_id"]
        if record["type"] == "message":
            for saved_call in record["data"].get("tool_calls", []):
                key = (run_id, saved_call["id"])
                if key in seen_calls:
                    raise ValueError(
                        f"第 {record_number} 条记录：运行 {run_id} 中调用 ID {key[1]} 重复"
                    )
                seen_calls[key] = saved_call["name"]
        elif record["type"] == "tool_result":
            data = record["data"]
            key = (run_id, data["tool_call_id"])
            if key not in seen_calls:
                raise ValueError(
                    f"第 {record_number} 条记录：运行 {run_id} 的结果 {key[1]} 没有前置请求"
                )
            if key in completed:
                raise ValueError(
                    f"第 {record_number} 条记录：运行 {run_id} 的结果 {key[1]} 重复"
                )
            if data["tool_name"] != seen_calls[key]:
                raise ValueError(
                    f"第 {record_number} 条记录：运行 {run_id} 的结果 {key[1]} 工具名不匹配"
                )
            completed.add(key)


def find_pending_calls(loaded: LoadedSession) -> list[PendingCall]:
    """收集请求并移除已有结果的调用；返回执行结果未知的项目。"""
    _validate_pairing(loaded.records)
    pending = {}
    for record in loaded.records:
        if record["type"] == "message":
            for saved_call in record["data"].get("tool_calls",[]):
                call = ToolCall(**saved_call)
                key = (record["run_id"],call.id)
                pending[key] = PendingCall(record["run_id"],call)
        elif record["type"] == "tool_result":
            key = (record["run_id"],record["data"]["tool_call_id"])
            pending.pop(key)
    return list(pending.values())
