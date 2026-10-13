"""助手准备：观测用户手敲的编辑执行链，只修改本例创建的临时文件。"""

import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
from uuid import uuid4

from mini_pi.models import ToolCall
from mini_pi.tools.edit_diff import render_edit_diff
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_file import find_unique_match, replace_unique_text
from mini_pi.tools.edit_policy import EditPolicy


async def main() -> int:
    root = Path(__file__).resolve().parents[1]
    evidence = (root / "local-learning" / "evidence").resolve()
    evidence.relative_to(root)
    evidence.mkdir(parents=True, exist_ok=True)
    trace: list[dict[str, object]] = []
    observed = {
        EditFileExecutor.execute.__code__: "execute",
        EditFileExecutor.validate_edit_call.__code__: "validate_edit_call",
        EditFileExecutor.apply_edit.__code__: "apply_edit",
        EditFileExecutor.prepare_edit.__code__: "prepare_edit",
        EditFileExecutor.read_editable_file.__code__: "read_editable_file",
        EditFileExecutor.resolve_edit_path.__code__: "executor.resolve_edit_path",
        EditPolicy.resolve_edit_path.__code__: "policy.resolve_edit_path",
        EditFileExecutor.check_file_access.__code__: "check_file_access",
        Path.read_bytes.__code__: "Path.read_bytes（实际读取）",
        replace_unique_text.__code__: "replace_unique_text",
        find_unique_match.__code__: "find_unique_match",
        Path.write_bytes.__code__: "Path.write_bytes（实际写入）",
        render_edit_diff.__code__: "render_edit_diff",
    }
    seen = set()
    recording = True

    def observe(frame, event, arg):
        # 只记录白名单函数的首次进入，避免把协程恢复误记为另一次工具执行。
        if recording and event == "call" and frame.f_code in observed and frame.f_code not in seen:
            seen.add(frame.f_code)
            trace.append({
                "function": observed[frame.f_code],
                "source": frame.f_code.co_filename,
                "line": frame.f_code.co_firstlineno,
                "thread": threading.current_thread().name,
            })

    before = "def final_price(price, rate):\n    return price * rate\n"
    expected = "def final_price(price, rate):\n    return price * (1 - rate)\n"
    call = ToolCall("call_001", "edit_file", {
        "path": "discount.py",
        "old_text": "return price * rate",
        "new_text": "return price * (1 - rate)",
    })
    with TemporaryDirectory(prefix="_d08_trace_", dir=evidence) as temporary:
        workspace = Path(temporary).resolve()
        workspace.relative_to(evidence)
        target = workspace / "discount.py"
        target.write_bytes(before.encode("utf-8"))
        executor = EditFileExecutor(EditPolicy(workspace, ["discount.py"]))
        previous_main_profile = sys.getprofile()
        previous_thread_profile = threading.getprofile()
        threading.setprofile(observe)
        sys.setprofile(observe)
        try:
            result = await executor.execute(call)
        finally:
            recording = False
            sys.setprofile(previous_main_profile)
            threading.setprofile(previous_thread_profile)
        after = target.read_bytes().decode("utf-8")
        checks = {
            "结果关联原调用": result.tool_call_id == call.id and result.tool_name == call.name,
            "没有工具错误": result.error is None,
            "磁盘文件实际修改": after == expected and after != before,
            "观测到实际读取": Path.read_bytes.__code__ in seen,
            "观测到实际写入": Path.write_bytes.__code__ in seen,
            "工具结果包含差异": "-    return price * rate" in result.output
            and "+    return price * (1 - rate)" in result.output,
        }
        report = {
            "scope": "助手构造 ToolCall；用户手敲核心真实执行；临时文件真实修改；未调用模型服务，未运行业务测试。",
            "model_requests": 0,
            "call": asdict(call),
            "configuration": {"workdir": str(workspace), "allowed_files": ["discount.py"]},
            "trace": trace,
            "before": before,
            "after": after,
            "result": asdict(result),
            "checks": checks,
        }
    report["temporary_workspace_removed"] = not workspace.exists()
    run_id = uuid4().hex
    record_path = evidence / f"d08-edit-trace-{run_id}.json"
    diff_path = evidence / f"d08-edit-trace-{run_id}.diff"
    record_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    diff_path.write_bytes(result.output.encode("utf-8"))
    print(json.dumps({
        "scope": report["scope"],
        "call": report["call"],
        "actual_call_order": [item["function"] for item in trace],
        "before": before,
        "after": after,
        "result": report["result"],
        "checks": checks,
        "record_path": str(record_path),
        "diff_path": str(diff_path),
    }, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) and report["temporary_workspace_removed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
