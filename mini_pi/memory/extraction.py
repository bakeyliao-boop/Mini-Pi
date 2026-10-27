"""MEM-W：模型响应到候选；不请求模型或执行写入。

模型仅提出content/proposed_route/reason；Scope与完整Source由程序提供。
格式和来源准入不证明语义保真，也不授予新增、更新或撤回权限。
"""

import json

from mini_pi.memory.codec import normalize_source
from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.models import MemoryScope, MemorySource
from mini_pi.memory.selection import MemoryCandidate, validate_candidate_source
from mini_pi.memory.validation_helpers import require_text


_MODEL_FIELDS = frozenset(("content", "proposed_route", "reason"))


def checked_candidate_items(
    scope: MemoryScope,
    source: MemorySource,
    raw_items: object,
) -> tuple[dict, ...]:
    """助手准备：检查上下文格式、数组及每项三字段外壳，再取快照。

    不核对Scope相等/角色准入或语义，不读取Session/网络/数据库。
    normalize_source仅复用格式检查，不替换或改写传入的完整Source。
    """
    if not isinstance(scope, MemoryScope):
        raise MemoryPolicyError("scope必须使用MemoryScope")
    require_text(scope.user_id, "user_id")
    require_text(scope.project_id, "project_id")
    normalize_source(source)
    require_text(source.text, "来源原文")
    if not isinstance(raw_items, list):
        raise MemoryPolicyError("提取结果必须是已解码的JSON数组")
    items = tuple(raw_items)
    for item in items:
        if not isinstance(item, dict) or set(item) != _MODEL_FIELDS:
            raise MemoryPolicyError("每个候选必须且只能包含content/proposed_route/reason")
    return tuple(dict(item) for item in items)


def parse_candidate_items(
    scope: MemoryScope,  # 当前可信用户和项目范围
    source: MemorySource,  # 程序读取并绑定的完整原始记录
    raw_items: object,  # JSON解码后的数组，尚不能信任每项格式或语义
) -> tuple[MemoryCandidate, ...]:
    """整批构造候选或抛错；合法空数组返回空tuple，不把错误变成空结果。

    本段只处理解码后的数据；请求终态、JSON解码和提取保真另行验收。
    空数组也要核对当前范围和角色；候选正文允许规范化，不逐字匹配。
    """
    items = checked_candidate_items(scope, source, raw_items)  # 检查格式并取得条目快照
    if source.scope != scope:  # 空数组也不能绕过当前用户和项目范围
        raise MemoryPolicyError("来源不属于当前用户或项目")  # 拒绝错范围来源
    if source.role not in ("user", "tool"):  # 只采用用户陈述或工具观察
        raise MemoryPolicyError("不允许的候选来源角色")  # 不采用模型自报身份

    candidates = []  # 暂存结果，尚未写入任何记忆
    for item in items:  # 按模型返回的原顺序逐项处理
        candidate = MemoryCandidate(  # 构造建议，不执行其内容
            source=source,  # 始终绑定程序提供的同一个完整来源
            content=item["content"],  # 保留允许规范化的候选正文
            proposed_route=item["proposed_route"],  # 仅是去向建议
            reason=item["reason"],  # 模型说明，不等于事实证据
        )  # 构造结束，仍须核验
        validate_candidate_source(scope, candidate)  # 复用格式与来源准入
        candidates.append(candidate)  # 合格后加入本次暂存结果

    return tuple(candidates)  # 全部通过才返回；合法空数组得到空元组


def checked_extraction_response(response: object) -> tuple[dict, dict]:
    """助手准备：只核对非流式响应外壳及正文格式，不代做终态准入。"""
    if not isinstance(response, dict) or response.get("error") is not None:
        raise MemoryPolicyError("提取服务响应必须是无错误的对象")
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise MemoryPolicyError("提取服务必须返回唯一结果")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise MemoryPolicyError("提取结果必须包含消息对象")
    require_text(message.get("content"), "提取响应正文")
    return choice, message


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    """助手准备：JSON对象不接受同名字段，避免解码时静默覆盖。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("提取JSON出现重复字段")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    """助手准备：拒绝JSON标准以外的NaN/Infinity常量。"""
    raise ValueError("提取JSON包含非标准常量")


def parse_extraction_response(
    scope: MemoryScope,  # 本次调用的用户和项目范围
    source: MemorySource,  # 程序已读取的完整原消息
    response: object,  # 非流式模型接口返回的完整响应对象
) -> tuple[MemoryCandidate, ...]:
    """先核对正常结束和纯文本消息，再解码并复用候选解析。

    正常的[]才表示无候选；失败、截断、工具/拒绝响应或坏JSON都抛错。
    本函数不请求模型，不执行工具，不读Session或写入记忆。
    """
    choice, message = checked_extraction_response(response)  # 检查响应外壳，取出结果和消息
    if choice.get("finish_reason") != "stop":  # 只接受模型正常完成
        raise MemoryPolicyError("提取响应未正常完成")  # 截断等情况不能当作没有候选

    if message.get("role") != "assistant":  # 检查提取模型的回答身份
        raise MemoryPolicyError("提取结果必须是assistant消息")  # 原消息身份仍由上一段核验

    if message.get("tool_calls") not in (None, []) or message.get("function_call") is not None:  # 拒绝工具调用
        raise MemoryPolicyError("提取响应不能包含工具调用")  # 本流程只接收候选正文

    if message.get("refusal") not in (None, ""):  # 检查模型是否明确拒答
        raise MemoryPolicyError("模型拒绝了本次提取")  # 拒答不能解释为没有候选

    try:  # 尝试将正文字符串解码为Python数据
        raw_items = json.loads(  # 只接受完整JSON，不修补模型输出
            message["content"],  # 提取模型返回的正文
            object_pairs_hook=_unique_json_object,  # 辅助检查：拒绝重复字段
            parse_constant=_reject_json_constant,  # 辅助检查：拒绝NaN等非标准常量
        )  # 得到数据后，再交给已有候选检查
    except (ValueError, RecursionError) as error:  # 捕获JSON错误或嵌套过深
        raise MemoryPolicyError("提取正文不是有效JSON") from error  # 保留错误原因，不返回空结果

    return parse_candidate_items(scope, source, raw_items)  # 复用上一段，核验候选并关联原消息
