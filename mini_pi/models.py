"""Mini-Pi 的统一数据结构。"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ToolCall:
    """模型提出的一次工具调用；创建这个对象不会执行工具。"""

    id: str
    name: str
    arguments: dict[str, object]


@dataclass
class ToolResult:
    """工具报告的执行结果；不替代任务最终的业务验收。"""

    tool_call_id: str
    tool_name: str
    output: str
    error: str | None = None


@dataclass
class Message:
    """消息的角色、文字与结构化工具调用；默认分别创建调用列表。"""

    role: str
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)


ConversationItem = Message | ToolResult  #对话历史


@dataclass
class ToolDefinition:
    """向模型介绍可用工具；parameters 保存 JSON Schema 形式的参数要求。"""

    name: str
    description: str
    parameters: dict[str, object]


RunStatus = Literal["finished", "error", "cancelled", "budget_exhausted", "timeout"]


@dataclass
class RunResult:
    """整次运行的结束状态与验收证据；二者不自动互相推导。"""

    status: RunStatus
    messages: list[ConversationItem] = field(default_factory=list)
    task_passed: bool | None = None
    error: str | None = None
