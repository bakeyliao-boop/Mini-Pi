"""助手准备：记忆模块的数据容器，不在容器中隐藏入库或读取决策。"""

from dataclasses import dataclass
from typing import Literal


MemoryKind = Literal["semantic", "episodic", "procedural"]
MemoryState = Literal["active", "superseded", "retracted"]
Conditions = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class MemoryScope:
    """由可信调用方提供，不能采用模型自行声称的用户/项目身份。"""

    user_id: str
    project_id: str


@dataclass(frozen=True)
class MemorySource:
    """已保存经历的稳定定位与原文；recorded_at 是记录时间。"""

    source_id: str
    scope: MemoryScope
    role: str
    text: str
    recorded_at: str


@dataclass(frozen=True)
class MemoryDraft:
    """来源定位与拟保存正文；content=None 保持旧原文读取语义。

    start/end 始终定位 Source 原文，使用 Python 左闭右开字符位置；
    独立 content 不改变来源，非空字符串的格式要求由辅助校验执行。
    """

    key: str
    start: int
    end: int
    valid_from: str
    kind: MemoryKind = "semantic"
    conditions: Conditions = ()
    content: str | None = None


@dataclass(frozen=True)
class MemoryEntry:
    """保存的版本；superseded 仍可在原适用区间内用于历史查询。"""

    memory_id: str
    scope: MemoryScope
    source: MemorySource
    draft: MemoryDraft
    version: int
    state: MemoryState
    written_at: str
    valid_to: str | None = None

    @property
    def text(self) -> str:
        if self.draft.content is not None:
            return self.draft.content
        return self.source.text[self.draft.start:self.draft.end]


@dataclass(frozen=True)
class MemoryHit:
    """向量检索的一条证据：完整已存条目及相似度，不生成新的事实。"""

    entry: MemoryEntry
    score: float


MemoryOperation = Literal["replace", "retract"]


@dataclass(frozen=True)
class MemoryReceipt:
    """同一事务内保存的操作结果定位；容器不执行重试或版本决策。"""

    scope: MemoryScope
    operation_id: str
    action: MemoryOperation
    request_hash: str
    key: str
    conditions: Conditions
    expected_version: int
    result_memory_id: str
    result_version: int
    source: MemorySource
    written_at: str
