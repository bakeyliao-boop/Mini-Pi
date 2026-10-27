"""D16：仅整理模型请求中的工具结果副本，不改原始会话记录。"""

from dataclasses import replace  # 创建字段保留的新数据类对象，不原地修改输入。

from mini_pi.models import ToolResult  # 沿用工具调用ID、工具名、输出与错误字段。


def shorten_read_result(result:ToolResult,max_output_chars:int)->ToolResult:
    if type(max_output_chars) is not int or max_output_chars <= 0:
        raise ValueError("max_output_chars必须是正整数")

    if result.tool_name != "read_file" or result.error is not None:
        return replace(result)

    if len(result.output) <= max_output_chars:
        return replace(result)

    marker = f"\n[后续内容已经省略；请在原始会话记录中回查调用id：{result.tool_call_id}]"
    if max_output_chars <= len(marker):
        raise ValueError("输出上限不足以容纳正文和省略提示")

    keep_chars = max_output_chars- len(marker)
    shortened = result.output[:keep_chars] + marker
    return replace(result,output=shortened)