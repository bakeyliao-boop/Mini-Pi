"""D10：线性 JSONL 会话记录；追加写入核心由学习者实现。"""

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from mini_pi.models import ConversationItem, Message, ToolCall, ToolResult
from mini_pi.session_records import LoadedSession, read_session_records


class SessionStore:
    """保存与还原线性记录；恢复检查和继续运行分段实现。"""

    def __init__(self, path: str | Path, run_id: str | None = None):
        # 助手准备：路径、运行标识和目录配置；不覆盖已有记录。
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = uuid4().hex if run_id is None else run_id
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("run_id 必须是非空字符串")

    def _make_entry(self, event_type: str, data: dict[str, object]) -> dict[str, object]:
        """助手准备：为实际消息或结果添加记录类型、运行 ID 和时间。"""
        if event_type not in {"run_start", "message", "tool_result", "run_end"}:
            raise ValueError("不支持的会话记录类型")
        if not isinstance(data, dict):
            raise TypeError("data 必须是字典")
        return {
            "type": event_type,
            "run_id": self.run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }

    def append_entry(self, event_type: str, data: dict[str, object]) -> None:
        """追加一条完整 JSON 记录；成功返回不代表整个任务通过。"""
        entry = self._make_entry(event_type,data)
        line = json.dumps(entry, ensure_ascii=False)
        with self.path.open("a",encoding="utf-8",newline="") as file:
            file.write(line + "\n")

    def append_item(self, item: ConversationItem) -> None:
        """保存一条消息或工具结果，保留嵌套调用及其标识。"""
        if not isinstance(item, (Message, ToolResult)):
            raise TypeError("item 必须是 Message 或 ToolResult")
        event_type = "tool_result" if isinstance(item, ToolResult) else "message"
        self.append_entry(event_type, asdict(item))

    def _restore_item(self, event_type: str, data: dict[str, object]) -> ConversationItem:
        """D11：将记录字典还原为统一对象；不执行历史工具调用。"""
        if event_type == "tool_result":
            return ToolResult(
              tool_call_id=data["tool_call_id"],
              tool_name=data["tool_name"],
              output=data["output"],
              error=data.get("error"),
              )
        if event_type == "message":
            calls = [ToolCall(**call) for call in data.get("tool_calls", [])]
            return Message(
                role=data["role"], content=data["content"], tool_calls=calls)

    def load(self) -> LoadedSession:
        """加载完整记录和对话历史，不执行调用，也不决定能否继续运行。"""
        records = read_session_records(self.path)
        history = []
        for record in records:
            if record["type"] in {"message","tool_result"}:
                history.append(self._restore_item(record["type"],record["data"]))
        return LoadedSession(history=history,records=records)
