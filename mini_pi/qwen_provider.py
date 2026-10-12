"""D07：Qwen 兼容接口的消息转换；核心逻辑由学习者分段敲入。"""

import json
from collections.abc import Sequence

from mini_pi.models import ConversationItem, Message, ToolCall, ToolDefinition, ToolResult


def parse_tool_call(raw_call: dict) -> ToolCall:
    """将服务返回的一条 function 调用转换为统一 ToolCall，不执行工具。"""
    function = raw_call["function"]
    arguments = json.loads(function["arguments"])

    if not isinstance(arguments,dict):
        raise ValueError("工具参数必须是 JSON 对象")

    return ToolCall(
        id = raw_call["id"],
        name = function["name"],
        arguments=arguments,
        )


def parse_assistant_message(raw_message: dict) -> Message:
    """把服务返回的 assistant 消息转换为统一 Message，不执行其中的调用。"""
    if raw_message.get("role") != "assistant":
        raise ValueError("模型响应必须是assistant消息")

    tool_calls = []
    for raw_call in raw_message.get("tool_calls") or []:
        tool_calls.append(parse_tool_call(raw_call))

    return Message(
        role="assistant",
        content=raw_message.get("content") or "",
        tool_calls=tool_calls,
    )


def tool_result_to_api(result: ToolResult) -> dict:
    """把内部工具结果转换为服务接受的 tool 消息，保留输出、错误和调用 ID。"""
    payload = {"output":result.output,"error":result.error}
    return {
    "role":"tool",
    "tool_call_id":result.tool_call_id,
    "content":json.dumps(payload,ensure_ascii=False),
    }


def tool_call_to_api(call: ToolCall) -> dict:
    """将历史中的统一调用转换回接口格式，供下一轮重放 assistant 调用请求。"""
    return {
      "id":call.id,
      "type":"function",
      "function":{
      "name":call.name,
      "arguments":json.dumps(call.arguments,ensure_ascii=False),
      },
    }


def message_to_api(message: Message) -> dict:
    """转换用户或 assistant 消息，保留文字和已有工具调用。"""
    api_message = {"role":message.role,"content":message.content}

    if message.tool_calls:
        raw_calls = []
        for call in message.tool_calls:
            raw_calls.append(tool_call_to_api(call))
        api_message["tool_calls"] = raw_calls
    return api_message


def history_to_api(history: Sequence[ConversationItem]) -> list[dict]:
    """按原顺序转换整段内部历史，不修改输入列表。"""
    api_messages = []

    for item in history:
        if isinstance(item,ToolResult):
            api_messages.append(tool_result_to_api(item))
        else:
            api_messages.append(message_to_api(item))
    return api_messages


def tool_definition_to_api(tool: ToolDefinition) -> dict:
    """将工具能力说明与参数 schema 转换为接口接受的工具定义。"""
    return {
    "type":"function",
    "function":{
    "name":tool.name,
    "description":tool.description,
    "parameters":tool.parameters,
      },
    }


def build_request(
    model: str,
    history: Sequence[ConversationItem],
    tools: Sequence[ToolDefinition],
) -> dict:
    """组装模型名称、消息历史和工具定义；本函数不发送网络请求。"""
    request = {
    "model":model,
    "messages":history_to_api(history),
    "stream":False,
    }

    if tools:
        api_tools = []
        for tool in tools:
            api_tools.append(tool_definition_to_api(tool))
        request["tools"] = api_tools
    return request
