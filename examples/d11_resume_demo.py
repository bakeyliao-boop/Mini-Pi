"""助手准备：用独立进程和真实文件工具演示 D11 的三种恢复状态。"""

import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from uuid import uuid4

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall
from mini_pi.session_resume import resume_session
from mini_pi.session_store import SessionStore
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy
from mini_pi.tools.read_file import ReadFileExecutor


READ_ONLY_TOOLS = frozenset({"read_file", "list_files"})
BEFORE = "def final_price(price, rate):\n    return price * rate\n"
AFTER = "def final_price(price, rate):\n    return price * (1 - rate)\n"


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


async def ready_stage(stage, root):
    """先由一个进程保存并退出，再由另一个进程加载并提问。"""
    reader = ReadFileExecutor(root)
    path = root / "session.jsonl"
    if stage == "seed":
        provider = MockProvider([
            Message("assistant", "先读取。", [
                ToolCall("read_001", "read_file", {"path": "discount.py"}),
            ]),
            Message("assistant", "读取完成，尚未修改。"),
        ])
        result = await run_loop(
            provider, reader, [Message("user", "读取 discount.py。")],
            [reader.definition], SessionStore(path, "run_A"),
        )
        assert result.status == "finished"
        return

    before = path.read_bytes()
    (root / "session-before-resume.jsonl").write_bytes(before)
    store = SessionStore(path, "run_B")
    old_history = store.load().history
    user = Message("user", "解释之前读取的公式。")
    provider = MockProvider([Message("assistant", "该公式计算优惠金额，未修改文件。")])
    with patch.object(reader, "execute", wraps=reader.execute) as execute:
        result = await resume_session(
            store, provider, reader, user.content, [reader.definition], READ_ONLY_TOOLS,
        )
        tool_count = execute.call_count
    loaded = store.load()
    checks = {
        "恢复状态为ready": result.plan.state == "ready",
        "模型收到完整旧历史和新问题": provider.requests == [old_history + [user]],
        "历史工具没有重放": tool_count == 0,
        "旧记录字节保留": path.read_bytes().startswith(before),
        "只追加四条新记录": len(loaded.records) == 10,
        "运行结束但没有宣称任务验收通过": (
            result.run_result.status == "finished" and result.run_result.task_passed is None
        ),
    }
    save_json(root / "summary.json", {
        "state": result.plan.state,
        "pending_calls": [asdict(item) for item in result.plan.pending_calls],
        "model_requests_during_resume": len(provider.requests),
        "tool_calls_during_resume": tool_count,
        "new_record_types": [r["type"] for r in loaded.records if r["run_id"] == "run_B"],
        "checks": checks,
    })
    assert all(checks.values()), checks


async def interrupted_stage(root, tool_name):
    """真实执行工具但故意不保存结果，模拟中断窗口；恢复阶段不重放。"""
    root.mkdir()
    target = root / "discount.py"
    target.write_text(BEFORE, encoding="utf-8")
    if tool_name == "read_file":
        executor = ReadFileExecutor(root)
        call = ToolCall("read_001", tool_name, {"path": "discount.py"})
        expected_state = "read_interrupted"
        expected_file = BEFORE
    else:
        executor = EditFileExecutor(EditPolicy(root, ["discount.py"]))
        call = ToolCall("edit_001", tool_name, {
            "path": "discount.py", "old_text": "return price * rate",
            "new_text": "return price * (1 - rate)",
        })
        expected_state = "needs_review"
        expected_file = AFTER
    path = root / "session.jsonl"
    store = SessionStore(path, "run_A")
    store.append_entry("run_start", {"status": "running"})
    store.append_item(Message("user", "检查折扣公式。"))
    store.append_item(Message("assistant", "发出工具请求。", [call]))
    actual_result = await executor.execute(call)
    assert actual_result.error is None, actual_result.error
    # 不保存 actual_result 或 run_end；这不是一次真实进程崩溃。
    before_records = path.read_bytes()
    (root / "session-before-resume.jsonl").write_bytes(before_records)
    before_file = target.read_bytes()
    provider = MockProvider([Message("assistant", "门禁应阻止这次请求。")])
    with patch.object(executor, "execute", wraps=executor.execute) as execute:
        result = await resume_session(
            SessionStore(path, "run_B"), provider, executor,
            "继续检查。", [], READ_ONLY_TOOLS,
        )
        tool_count = execute.call_count
    checks = {
        "返回明确恢复状态": result.plan.state == expected_state,
        "保留原调用用于核对": len(result.plan.pending_calls) == 1 and result.plan.pending_calls[0].call == call,
        "没有运行结果": result.run_result is None,
        "模型和工具零调用": len(provider.requests) == 0 and tool_count == 0,
        "没有追加会话记录": path.read_bytes() == before_records,
        "恢复期间没有修改实际文件": target.read_bytes() == before_file,
        "工具执行后的实际内容符合预期": target.read_text(encoding="utf-8") == expected_file,
    }
    summary = {
        "state": result.plan.state,
        "pending_calls": [asdict(item) for item in result.plan.pending_calls],
        "tool_executed_before_interruption_simulation": tool_name,
        "model_requests_during_resume": len(provider.requests),
        "tool_calls_during_resume": tool_count,
        "actual_file_after": target.read_text(encoding="utf-8"),
        "checks": checks,
    }
    save_json(root / "summary.json", summary)
    assert all(checks.values()), checks
    return summary


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-stage", choices=("seed", "resume"))
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if args.ready_stage:
        if args.root is None:
            parser.error("--ready-stage 需要 --root")
        await ready_stage(args.ready_stage, args.root)
        return

    project = Path(__file__).resolve().parents[1]
    run_dir = project / "local-learning" / "evidence" / f"d11-resume-{uuid4().hex}"
    ready_root = run_dir / "ready"
    ready_root.mkdir(parents=True)
    (ready_root / "discount.py").write_text(BEFORE, encoding="utf-8")
    for stage in ("seed", "resume"):
        subprocess.run([
            sys.executable, "-X", "utf8", "-m", "examples.d11_resume_demo",
            "--ready-stage", stage, "--root", str(ready_root),
        ], cwd=project, check=True)
    ready = json.loads((ready_root / "summary.json").read_text(encoding="utf-8"))
    read = await interrupted_stage(run_dir / "read_interrupted", "read_file")
    edit = await interrupted_stage(run_dir / "needs_review", "edit_file")
    report = {
        "scope": "助手构造场景，使用模拟模型和真实文件工具。正常继续使用两个独立进程；中断通过省略结果记录模拟，不是真实崩溃。未请求真实模型服务，未运行业务测试。",
        "ready_seed_process_exited_before_resume": True,
        "scenarios": [ready, read, edit],
    }
    save_json(run_dir / "summary.json", report)
    print(f"证据目录：{run_dir}")
    for scenario in report["scenarios"]:
        print(f"{scenario['state']}: model={scenario['model_requests_during_resume']}, "
              f"tools={scenario['tool_calls_during_resume']}, checks=PASS")


if __name__ == "__main__":
    asyncio.run(main())
