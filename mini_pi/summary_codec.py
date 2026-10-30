"""D17 辅助：将旧会话记录编码为摘要模型可读取的资料。"""

from dataclasses import asdict
import json

from mini_pi.models import Message, ToolResult


def encode_summary_history(history):
    """保留角色、工具调用、返回状态及结果；不发送请求、不修改输入。"""
    records = []
    for item in history:
        if isinstance(item, Message):
            kind = "message"
        elif isinstance(item, ToolResult):
            kind = "tool_result"
        else:
            raise TypeError("摘要输入必须是消息或工具结果")
        records.append({"type": kind, "data": asdict(item)})
    return json.dumps(records, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
