"""D13-D：命令入口分段接线；参数解析和终端中断处理尚待接入。"""

import argparse
import asyncio
import json
import math
import signal
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mini_pi.bootstrap import build_tools
from mini_pi.harness import Harness, RunBudget
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, RunResult
from mini_pi.session_store import SessionStore


@dataclass(frozen=True)
class CommandResult:
    """供后续终端输出使用；恢复被阻止时没有运行结果。"""

    status: str
    session_path: Path
    run_result: RunResult | None


def parse_command_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析当前分流需要的参数，不启动模型或工具。"""
    parser = argparse.ArgumentParser(prog="mini-pi")
    parser.add_argument("text", help="本次任务文本")
    parser.add_argument("--session", required=True, type=Path, help="会话JSONL路径")
    parser.add_argument("--resume", action="store_true", help="显式恢复旧会话")
    parser.add_argument("--workdir", type=Path, default=Path.cwd(), help="四工具工作目录")
    parser.add_argument("--allow-file", action="append", default=[], help="允许编辑的相对文件，可重复指定")
    parser.add_argument("--test-command-json", type=_test_command, default=[sys.executable, "-m", "unittest", "discover", "-s", "tests"], help="固定测试命令的JSON字符串数组")
    parser.add_argument("--provider", choices=("mock", "qwen"), default="mock", help="默认mock不请求外部模型")
    parser.add_argument("--model", default="qwen3.8-flash", help="qwen适配器的模型ID")
    parser.add_argument("--max-model-turns", type=_positive_int, default=4)
    parser.add_argument("--total-timeout", type=_positive_seconds, default=60.0)
    return parser.parse_args(argv)


def _test_command(value: str) -> list[str]:
    try:
        command = json.loads(value)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError("测试命令必须是JSON字符串数组") from error
    if not isinstance(command, list) or not command or any(not isinstance(x, str) or not x for x in command):
        raise argparse.ArgumentTypeError("测试命令必须是非空JSON字符串数组")
    return command


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("轮数必须为正整数")
    return number


def _positive_seconds(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("时限必须为有限正数")
    return number


def _build_terminal_harness(options: argparse.Namespace) -> Harness:
    """复用已学组装；mock无外部请求，qwen仅按显式选项构造。"""
    if options.provider == "qwen":
        from mini_pi.qwen_client import QwenProvider
        provider = QwenProvider(model=options.model, max_requests=options.max_model_turns)
    else:
        provider = MockProvider([Message("assistant", "模拟运行结束；未执行任务验收。", stop_reason="stop")])
    tools = build_tools(options.workdir, options.allow_file, options.test_command_json,
                        options.session.resolve().parent / "tool-evidence")
    return Harness(provider, tools, budget=RunBudget(
        max_model_turns=options.max_model_turns,
        total_timeout_seconds=options.total_timeout))


def _print_terminal_result(status: str, path: Path, result: RunResult | None = None, *, error: str | None = None) -> None:
    """只整理输出；null明确表示没有任务验收结论。"""
    print(json.dumps({"status": status, "session_path": str(path.resolve()),
                      "task_passed": None if result is None else result.task_passed,
                      "error": error if error is not None else (None if result is None else result.error)}, ensure_ascii=False))


def command_exit_code(outcome: CommandResult) -> int:
    """应用自定退出码，不声称与Pi完全相同。"""
    codes = {  # 定义 Mini-Pi 自己的退出码约定
        "finished": 0, "error": 1,  # 正常结束或运行错误
        "budget_exhausted": 3,  # 模型请求次数预算耗尽
        "needs_review": 4, "read_interrupted": 4,  # 恢复门禁阻止继续
        "timeout": 124, "cancelled": 130,  # 总时限到达或运行取消
    }
    if outcome.status not in codes:  # 未知状态不默认为成功
        raise ValueError(f"未知终态：{outcome.status}")
    if outcome.status == "finished" and outcome.run_result is not None:
        if outcome.run_result.task_passed is False:  # 明确验收失败时覆盖正常结束码
            return 1
    return codes[outcome.status]


def main(argv: Sequence[str] | None = None) -> int:
    """解析、组装、运行、输出；中断必须先完成Agent收尾。"""
    options = parse_command_args(argv)
    try:
        harness = _build_terminal_harness(options)
        outcome = asyncio.run(_run_in_terminal(harness,options))
    except (KeyboardInterrupt,asyncio.CancelledError):
        _print_terminal_result("cancelled",options.session)

        return 130
    except (ValueError,OSError) as error:
        _print_terminal_result("error",options.session,error=str(error))

        return 2
    _print_terminal_result(outcome.status,outcome.session_path,outcome.run_result)
    return command_exit_code(outcome)



async def _run_in_terminal(harness: Harness, options: argparse.Namespace) -> CommandResult:
    """将SIGINT转成入口任务取消；重复信号仍经过既有收尾链。"""
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    previous = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, lambda signum, frame: loop.call_soon_threadsafe(task.cancel))
    try:
        return await run_command_safely(harness, options.text, options.session, resume=options.resume)
    finally:
        signal.signal(signal.SIGINT, previous)


async def run_command(
    harness: Harness,
    user_text: str,
    session_path: str | Path,
    *,
    resume: bool = False,
) -> CommandResult:
    """按显式标记分流；不自行创建模型、工具或第二套循环。"""
    store = SessionStore(session_path)
    if resume:
        outcome = await harness.resume(user_text,store)
        result = outcome.run_result
        status = outcome.plan.state if result is None else result.status
    else:
        result = await harness.run(user_text,store)
        status = result.status

    return CommandResult(
        status=status,
        session_path=store.path,
        run_result=result,
        )


async def run_command_safely(
    harness: Harness,
    user_text: str,
    session_path: str | Path,
    *,
    resume: bool = False,
) -> CommandResult:
    """终端等待入口；取消时请求Agent取消，等收尾后再传播。"""
    try:
        return await run_command(harness,user_text,session_path,resume=resume)
    except asyncio.CancelledError:
        harness.agent.abort()
        await _wait_for_command_idle(harness)
        raise

async def _wait_for_command_idle(harness: Harness) -> None:
    """取消后的稳定等待；重复取消不能跳过当前运行收尾。"""
    waiter = asyncio.create_task(harness.agent.wait_for_idle())
    while not waiter.done():
        try:
            await asyncio.shield(waiter)
        except asyncio.CancelledError:
            continue
    waiter.result()
