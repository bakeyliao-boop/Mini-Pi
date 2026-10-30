"""D17：摘要与原始会话历史的绑定信息；尚不执行持久化。"""

from dataclasses import asdict, dataclass
from copy import deepcopy
import hashlib
import json

from mini_pi.compaction import is_safe_cut
from mini_pi.models import Message, ToolResult
from mini_pi.session_records import LoadedSession
from mini_pi.session_recovery import find_pending_calls


@dataclass(frozen=True)
class CompactionBinding:
    session_id: str
    history_count: int
    cut_index: int
    history_fingerprint: str


def fingerprint_history(history):
    """对原始记录做稳定编码，用于之后发现历史不一致；不读取或写入会话。"""
    records = []
    for item in history:
        if isinstance(item, Message):
            kind = "message"
        elif isinstance(item, ToolResult):
            kind = "tool_result"
        else:
            raise TypeError("历史必须只包含消息和工具结果")
        records.append({"type": kind, "data": asdict(item)})
    encoded = json.dumps(records, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def make_compaction_binding(session_id, history, cut_index):
    if not isinstance(session_id, str) or not session_id.strip():  # 会话标识不能为空
        raise ValueError("会话标识必须是非空字符串")
    if not isinstance(history, list):  # 本阶段接收完整原始历史列表
        raise ValueError("历史必须是列表")

    snapshot = deepcopy(history)  # 固定生成标签时的历史内容
    if not is_safe_cut(snapshot, cut_index):  # 摘要边界不能拆开工具组
        raise ValueError("摘要切点不安全")

    return CompactionBinding(
        session_id=session_id,  # 指明标签属于哪个会话
        history_count=len(snapshot),  # 记录当时共有多少条历史
        cut_index=cut_index,  # 记录从哪条开始保留原文
        history_fingerprint=fingerprint_history(snapshot),  # 为这份历史生成校验值
    )

def check_compaction_binding(binding, session_id, history):
    if not isinstance(binding, CompactionBinding):  # 必须是摘要标签
        raise ValueError("摘要标签格式不正确")
    if not isinstance(session_id, str) or not session_id.strip():  # 当前会话标识不能为空
        raise ValueError("会话标识必须是非空字符串")
    if binding.session_id != session_id:  # 标签必须属于当前会话
        raise ValueError("摘要不属于当前会话")
    if not isinstance(history, list):  # 本阶段接收原始历史列表
        raise ValueError("历史必须是列表")
    if type(binding.history_count) is not int or binding.history_count < 2:  # 检查标签中的历史条数
        raise ValueError("摘要历史条数不正确")
    if len(history) < binding.history_count:  # 当前历史缺少生成摘要时的记录
        raise ValueError("当前历史不完整")
    if type(binding.cut_index) is not int or not 0 < binding.cut_index < binding.history_count:  # 检查切点范围
        raise ValueError("摘要切点不正确")

    snapshot = deepcopy(history[:binding.history_count])  # 取出生成摘要时已有的那段历史
    if fingerprint_history(snapshot) != binding.history_fingerprint:  # 比较历史内容
        raise ValueError("摘要对应的历史已变化")
    if not is_safe_cut(snapshot, binding.cut_index):  # 再确认工具组没有被拆开
        raise ValueError("摘要切点不安全")

def check_before_compaction_save(loaded, binding):
    """保存前核对一次完整会话快照；调用方负责从 SessionStore 加载。"""
    if not isinstance(loaded, LoadedSession):
        raise ValueError("会话加载结果格式不正确")
    if not isinstance(binding, CompactionBinding):
        raise ValueError("摘要标签格式不正确")

    snapshot = deepcopy(loaded)  # 一次复制，后续检查均针对同一份快照
    if not isinstance(snapshot.session_id, str) or not snapshot.session_id.strip():
        raise ValueError("会话没有固定编号")
    if snapshot.session_id != binding.session_id:
        raise ValueError("摘要不属于当前会话")
    if any(record.get("type") == "compaction" for record in snapshot.records):
        raise ValueError("会话已有摘要，本阶段暂不重复压缩")
    if find_pending_calls(snapshot):
        raise ValueError("会话有未完成的工具调用")

    if fingerprint_history(snapshot.history) != binding.history_fingerprint:
        raise ValueError("会话历史已变化，需要重新准备摘要")
    if type(binding.history_count) is not int or binding.history_count != len(snapshot.history):
        raise ValueError("摘要标签中的历史条数不正确")  # 条数本身要写入标签，须与历史一致
    if not is_safe_cut(snapshot.history, binding.cut_index):
        raise ValueError("摘要切点不安全")
