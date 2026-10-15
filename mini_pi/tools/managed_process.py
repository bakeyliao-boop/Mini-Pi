"""助手准备：固定命令的启动、等待、超时/取消清理与进程证据。

与 subprocess.run 的返回值和 TimeoutExpired / OSError 保持兼容；
CancelledError 仅在本次受控进程树清理后向外传播。
"""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from mini_pi.tools.process_tree import ProcessTree


async def _drain_cleanup(task):
    """清理中再次收到取消也先等清理完成，再把取消交回调用方。"""
    cancelled = False
    while True:
        try:
            await asyncio.shield(task)
            return cancelled
        except asyncio.CancelledError:
            cancelled = True
            if task.done():
                task.result()


async def _stop_and_wait(tree, process, waiter, attached):
    termination_error = None
    try:
        if attached:
            tree.kill()
        elif process.poll() is None:
            process.kill()  # 绑定失败时启动许可尚未发送，实际测试命令未启动。
    except OSError as error:
        termination_error = error
        tree.close()  # Windows KILL_ON_JOB_CLOSE 的兜底；仍不得报告正常清理。
        if process.poll() is None:
            process.kill()
    if waiter is None:
        await asyncio.to_thread(process.wait)
    else:
        await waiter
    if termination_error is not None:
        raise RuntimeError("停止测试进程树失败，已尝试兜底回收") from termination_error
    cleanup_deadline = asyncio.get_running_loop().time() + 5
    while tree.active_count() not in (None, 0):
        if asyncio.get_running_loop().time() >= cleanup_deadline:
            raise RuntimeError("受控测试进程树未完成清理，不能报告正常结束")
        await asyncio.sleep(0.01)


async def run_managed_process(command, *, cwd, timeout, evidence_dir):
    """执行程序配置的参数数组，不通过 shell；返回前回收本次普通进程树。"""
    root = Path(evidence_dir)
    root.mkdir(parents=True, exist_ok=True)
    stem = root / f"run-tests-process-{uuid4().hex}"
    output_path = stem.with_suffix(".txt")
    trace_path = stem.with_suffix(".json")
    worker_path = Path(str(stem) + ".worker.json")
    deadline = asyncio.get_running_loop().time() + timeout
    trace = {"supervisor_pid": None, "outcome": "starting", "tree_empty": None,
             "waiter_done": False, "output_path": str(output_path)}
    process, waiter, tree = None, None, None
    attached, timed_out = False, False
    failure = None
    output = output_path.open("wb")
    timer = None
    try:
        tree = ProcessTree()
        process = subprocess.Popen(
            [sys.executable, "-X", "utf8", str(Path(__file__).with_name("process_worker.py")),
             str(worker_path.resolve()), *command],
            cwd=cwd, stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        trace["supervisor_pid"] = process.pid
        tree.attach(process.pid)
        attached = True
        waiter = asyncio.create_task(asyncio.to_thread(process.wait))
        process.stdin.write(b"\n")
        process.stdin.flush()
        process.stdin.close()
        timer = asyncio.timeout_at(deadline)
        async with timer:
            await asyncio.shield(waiter)
    except BaseException as error:
        failure = error
        timed_out = isinstance(error, TimeoutError) and timer is not None and timer.expired()
    finally:
        try:
            if process is not None:
                cleanup = asyncio.create_task(_stop_and_wait(tree, process, waiter, attached))
                if await _drain_cleanup(cleanup):
                    failure = asyncio.CancelledError()
                    timed_out = False
                trace["tree_empty"] = tree.active_count() == 0 if os.name == "nt" else None
                trace["waiter_done"] = waiter.done() if waiter is not None else process.returncode is not None
        except Exception as cleanup_error:
            failure = cleanup_error
            timed_out = False
            trace["cleanup_error"] = str(cleanup_error)
            trace["waiter_done"] = waiter.done() if waiter is not None else False
        finally:
            if process is not None and process.stdin is not None:
                process.stdin.close()
            if tree is not None:
                tree.close()
            output.close()
    raw_output = output_path.read_bytes()
    if isinstance(failure, asyncio.CancelledError):
        trace["outcome"] = "cancelled"
    elif timed_out:
        trace["outcome"] = "timeout"
    elif failure is not None:
        trace["outcome"] = "execution_error"
    else:
        trace["outcome"] = "completed"
    trace["returncode"] = process.returncode if process is not None else None
    trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    if failure is not None:
        if timed_out:
            raise subprocess.TimeoutExpired(command, timeout, output=raw_output) from None
        raise failure
    try:
        worker_info = json.loads(worker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        trace["outcome"] = "execution_error"
        trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        raise OSError("测试启动器没有返回有效的启动记录") from error
    if "execution_error" in worker_info:
        trace["outcome"] = "execution_error"
        trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        raise OSError(worker_info["execution_error"])
    return subprocess.CompletedProcess(command, process.returncode, stdout=raw_output)
