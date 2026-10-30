"""D17：摘要候选的单写入者保存入口；不负责恢复或自动重试。"""

import asyncio
from copy import deepcopy

from mini_pi.compaction_binding import check_before_compaction_save
from mini_pi.compaction_record import check_answer_output_limit, check_candidate_before_save
from mini_pi.run_deadline import RunDeadlineExceeded, await_before_deadline
from mini_pi.session_store import SessionStore

async def save_compaction_candidate(
    store, candidate, references, tools, answer_context,  # 会话、候选摘要和回答入口
    answer_window, max_context_chars, *, deadline=None,  # 回答模型配置和总时限
):
    if not isinstance(store, SessionStore):  # 必须提供会话存储
        raise ValueError("会话存储格式不正确")

    candidate_snapshot = deepcopy(candidate)  # 固定待保存的候选结果
    reference_snapshot = deepcopy(references)  # 固定本轮资料
    tool_snapshot = deepcopy(tools)  # 固定回答模型的工具定义

    await await_before_deadline(
        lambda: asyncio.sleep(0), deadline  # 先响应取消并检查时限
    )
    loaded = store.load()  # 重新读取当前会话
    data, estimate = await check_candidate_before_save(
        loaded, candidate_snapshot, reference_snapshot, tool_snapshot,
        answer_context, answer_window, max_context_chars, deadline=deadline,
    )

    loaded_after_wait = store.load()  # 等待整理期间会话可能变化，写入前重新核对
    check_before_compaction_save(loaded_after_wait, candidate_snapshot.binding)
    check_answer_output_limit(answer_context._provider, answer_window)  # 核对实际回答模型输出上限

    task = asyncio.current_task()  # 获取当前运行任务
    if task is not None and task.cancelling():  # 检查期间收到取消请求
        raise asyncio.CancelledError  # 不写入摘要
    if deadline is not None and asyncio.get_running_loop().time() >= deadline:  # 检查期间已超时
        raise RunDeadlineExceeded("运行总时间已到")  # 不写入摘要

    store.append_entry("compaction", data)  # 检查通过后追加摘要记录
    return data, estimate  # 写入成功后返回记录和估算
