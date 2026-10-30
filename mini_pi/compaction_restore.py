"""D17：读取并核对已保存的摘要；不改写原始会话。"""

from copy import deepcopy

from mini_pi.compaction import build_compacted_history, split_for_summary
from mini_pi.compaction_binding import CompactionBinding, check_compaction_binding
from mini_pi.memory.context_helpers import check_complete_messages
from mini_pi.session_records import LoadedSession, find_compaction_record, find_session_id
from mini_pi.session_recovery import find_pending_calls

def read_saved_compaction(loaded):
    """在恢复会话时，找到已保存的摘要，并确认它还能用于当前会话。"""
    if not isinstance(loaded, LoadedSession):  # 必须接收加载后的会话
        raise ValueError("会话加载结果格式不正确")

    snapshot = deepcopy(loaded)  # 固定本次要检查的记录和历史
    found = find_compaction_record(snapshot.records)  # 查找已保存的摘要
    if found is None:  # 会话没有摘要
        return None

    position, record = found  # 取出摘要在记录列表中的位置及内容
    data = record["data"]  # 取出摘要文字和来源标签
    binding = CompactionBinding(
        session_id=data["session_id"],  # 摘要所属会话
        history_count=data["history_count"],  # 保存时的历史条数
        cut_index=data["cut_index"],  # 近期原文的起点
        history_fingerprint=data["history_fingerprint"],  # 保存时的历史指纹
    )

    before = snapshot.records[:position]  # 摘要记录之前的所有记录
    session_id = find_session_id(before)  # 编号必须在摘要之前已经存在
    history_count = sum(
        1 for item in before if item["type"] in ("message", "tool_result")  # 只统计普通消息和工具结果
    )
    if history_count != binding.history_count:  # 保存位置与标签里的条数不一致
        raise ValueError("摘要记录的位置与历史条数不一致")

    check_compaction_binding(binding, session_id, snapshot.history)  # 核对编号、指纹和切点
    return data["summary"], binding  # 返回核对通过的摘要及标签

def build_restored_history(loaded):
    if not isinstance(loaded,LoadedSession):
        raise ValueError('会话加载结果格式错误')
    snapshot = deepcopy(loaded)
    saved = read_saved_compaction(snapshot)
    if saved is None:
        return snapshot.history

    if find_pending_calls(snapshot):
        raise ValueError('会话有未完成的工具调用，不能使用摘要')
    summary,binding = saved
    previous = snapshot.history[:binding.history_count]
    later = snapshot.history[binding.history_count:]
    system,_,recent = split_for_summary(previous,binding.cut_index)

    return build_compacted_history(
        system, summary, recent + later  # 分别传入系统规则、摘要和保留的记录
    )

def build_live_restored_history(loaded, live_history):
    if not isinstance(loaded, LoadedSession) or not isinstance(live_history, list):  # 检查输入
        raise ValueError("会话或运行历史格式不正确")

    saved = deepcopy(loaded)  # 复制打开会话时加载的内容
    current = deepcopy(live_history)  # 复制当前运行中的完整历史
    saved_count = len(saved.history)  # 打开会话时已有多少条历史

    if current[:saved_count] != saved.history:  # 前半段必须与打开时一致
        raise ValueError("运行历史与已加载会话不一致")

    restored = build_restored_history(saved)  # 得到摘要和打开时保留的近期记录
    new_messages = current[saved_count:]  # 取出本次继续运行后新增的记录
    messages = restored + new_messages  # 将新增记录接到恢复视图后面
    check_complete_messages(messages)  # 检查最终视图中的工具调用和结果
    return messages  # 返回给模型准备的视图
