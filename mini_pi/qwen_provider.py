"""D07：Qwen 兼容接口的消息转换；核心逻辑由学习者分段敲入。"""

import json
from collections.abc import Sequence

from mini_pi.models import ConversationItem, Message, ToolCall, ToolDefinition, ToolResult


class ModelResponseError(ValueError):
    """外部模型响应不符合适配器要求。"""


def get_response_choice(response: object) -> dict:
    """检查响应外壳，返回第一条候选结果。"""
    if not isinstance(response, dict):
        raise ModelResponseError("模型响应必须是对象")

    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelResponseError("模型响应 choices 必须是非空列表")

    choice = choices[0]
    if not isinstance(choice, dict):
        raise ModelResponseError("模型响应 choice 必须是对象")

    return choice


def parse_tool_call(raw_call: dict, preserve_unparsed:bool = False) -> ToolCall:
    """将服务返回的一条 function 调用转换为统一 ToolCall，不执行工具。"""
    if not isinstance(raw_call, dict):
        raise ModelResponseError("工具调用必须是对象")

    call_id = raw_call.get("id")
    if not isinstance(call_id, str) or not call_id.strip():
        raise ModelResponseError("工具调用 ID 必须是非空字符串")

    if raw_call.get("type") != "function":
        raise ModelResponseError("只支持 function 类型的工具调用")

    function = raw_call.get("function")
    if not isinstance(function, dict):
        raise ModelResponseError("工具调用 function 必须是对象")

    name = function.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ModelResponseError("工具名必须是非空字符串")

    raw_arguments = function.get("arguments")
    if not isinstance(raw_arguments, str):
        raise ModelResponseError("工具参数原文必须是字符串")

    try:  #保证残缺调用也能被保留下来，送到循环
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError:
        if not preserve_unparsed:
            raise
        arguments = None
    if not isinstance(arguments, dict):
        if not preserve_unparsed:
            # raise ValueError("工具参数必须是JSON对象")
            raise ModelResponseError("工具参数必须是JSON对象")
        arguments = None

    return ToolCall(
        id = call_id,
        name = name,
        arguments = arguments,
        raw_arguments = raw_arguments if preserve_unparsed else None,
        )

def parse_assistant_message(
    raw_message: dict,
    stop_reason: str | None = None,
    error_message: str | None = None,
) -> Message:
# def parse_assistant_message(raw_message: dict) -> Message:
    """把服务返回的 assistant 消息转换为统一 Message，不执行其中的调用。"""
    if not isinstance(raw_message,dict):
        raise ModelResponseError("模型消息必须是对象")

    if raw_message.get("role") != "assistant":
        raise ModelResponseError("模型响应必须是 assistant 消息")

    content = raw_message.get("content")
    if content is None:
        content = ""
    elif not isinstance(content,str):
        raise ModelResponseError("模型消息正文必须是字符串或null")


    raw_calls = raw_message.get("tool_calls")
    if raw_calls is None:
        raw_calls = []
    elif not isinstance(raw_calls,list):
        raise ModelResponseError("tool_calls必须是列表或null")
    tool_calls = []
    seen_ids = set()

    for raw_call in raw_calls:
        call = parse_tool_call(
            raw_call,
            preserve_unparsed=stop_reason in ("length", "error", "aborted"),
        )

        if call.id in seen_ids:
            raise ModelResponseError(f"工具调用 ID 重复：{call.id}")

        seen_ids.add(call.id)
        tool_calls.append(call)

    return Message(
        role="assistant",
        # content=raw_message.get("content") or "",
        content=content,
        tool_calls=tool_calls,
        stop_reason=stop_reason,
        error_message=error_message,
    )

def parse_response(response:object)->Message:
    """校验完整响应并转换消息，不执行工具"""
    choice = get_response_choice(response)

    reason = choice.get("finish_reason")
    if not isinstance(reason,str) or not reason.strip():
        raise ModelResponseError("finish_reason必须是非空字符串")

    stop_reason = reason
    error_message = None
    if reason not in ("stop","tool_calls","length"):
        stop_reason = "error"
        error_message = f"模型服务结束原因：{reason}"

    try:
        return parse_assistant_message(
            choice.get("message"),
            stop_reason=stop_reason,
            error_message=error_message,
            )
    except json.JSONDecodeError as error:
        raise ModelResponseError("工具参数不是有效 JSON") from error




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
    if call.raw_arguments is not None:
        arguments = call.raw_arguments
    elif isinstance(call.arguments,dict):
        arguments = json.dumps(call.arguments,ensure_ascii=False)
    else:
        raise ValueError("工具调用缺少参数对象和原始参数文本")

    return {
      "id":call.id,
      "type":"function",
      "function":{
      "name":call.name,
      "arguments":arguments,
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
