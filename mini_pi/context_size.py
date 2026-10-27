"""D16：Qwen输入投影的大小记录；字符启发式不是精确token计数。"""

from collections.abc import Sequence
from dataclasses import dataclass
import json

from mini_pi.models import ConversationItem, ToolDefinition
from mini_pi.qwen_provider import history_to_api, tool_definition_to_api


@dataclass(frozen=True)
class InputSizeEstimate:
    """保存测量范围、字符数与估算方法，避免把估算当成服务端usage。"""

    json_chars: int
    estimated_input_tokens: int
    method: str


def serialize_qwen_input(
    messages: Sequence[ConversationItem],
    tools: Sequence[ToolDefinition],
) -> str:
    """复用适配器编码消息及工具定义；不发送请求，不含服务端模板。"""
    payload = {"messages": history_to_api(messages)}
    if tools:
        payload["tools"] = [tool_definition_to_api(tool) for tool in tools]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def estimate_qwen_input(
    messages: Sequence[ConversationItem],  # 构建完成的消息及参考材料。
    tools: Sequence[ToolDefinition],  # 同一次请求的工具说明和参数schema。
) -> InputSizeEstimate:
    encoded = serialize_qwen_input(messages, tools)  # 复用适配器编码，包含工具定义。
    char_count = len(encoded)  # 统计Unicode字符，不统计UTF-8字节。
    estimated_tokens = (char_count + 3) // 4  # 实验启发式：字符数除以4，向上取整。
    return InputSizeEstimate(
        json_chars=char_count,
        estimated_input_tokens=estimated_tokens,
        method="qwen-input-json-chars-div4-v1",  # 明确记录规则，不当作服务端usage。
    )
