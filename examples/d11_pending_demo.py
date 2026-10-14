"""助手准备：真实读写，刻意省略编辑结果落盘，演示缺结果调用识别。"""

import asyncio
from dataclasses import asdict
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from mini_pi.models import Message, ToolCall
from mini_pi.session_records import LoadedSession
from mini_pi.session_recovery import find_pending_calls
from mini_pi.session_store import SessionStore
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy
from mini_pi.tools.read_file import ReadFileExecutor


async def main() -> int:
    project = Path(__file__).resolve().parents[1]
    run_dir = project / "local-learning" / "evidence" / f"d11-pending-{uuid4().hex}"
    workdir = run_dir / "workspace"
    workdir.mkdir(parents=True)
    target = workdir / "discount.py"
    before = "def final_price(price, rate):\n    return price * rate\n"
    after = "def final_price(price, rate):\n    return price * (1 - rate)\n"
    target.write_text(before, encoding="utf-8", newline="")
    store = SessionStore(run_dir / "session.jsonl", "run_A")
    read_call = ToolCall("call_001", "read_file", {"path": "discount.py"})
    edit_call = ToolCall("call_002", "edit_file", {
        "path": "discount.py", "old_text": "return price * rate",
        "new_text": "return price * (1 - rate)",
    })
    store.append_entry("run_start", {"status": "running"})
    store.append_item(Message("user", "读取并修改折扣公式；此例只观测调用记录。"))
    store.append_item(Message("assistant", "先读取，然后修改。", [read_call, edit_call]))

    reader = ReadFileExecutor(workdir)
    editor = EditFileExecutor(EditPolicy(workdir, ["discount.py"]))
    read_result = await reader.execute(read_call)
    if read_result.error is not None:
        raise AssertionError(read_result.error)
    store.append_item(read_result)
    edit_result = await editor.execute(edit_call)
    if edit_result.error is not None:
        raise AssertionError(edit_result.error)
    # 刻意不保存 edit_result / run_end，模拟写入已发生但结果未落盘的窗口。

    loaded = store.load()
    recorded_bytes = store.path.read_bytes()
    progress = []
    with patch.object(reader, "execute") as read_execute, patch.object(editor, "execute") as edit_execute:
        for count in range(1, len(loaded.records) + 1):
            prefix_records = loaded.records[:count]
            prefix_history = [
                store._restore_item(record["type"], record["data"])
                for record in prefix_records if record["type"] in {"message", "tool_result"}
            ]
            pending = find_pending_calls(LoadedSession(prefix_history, prefix_records))
            progress.append({
                "record": count,
                "type": prefix_records[-1]["type"],
                "pending_ids": [item.call.id for item in pending],
            })
        final_pending = find_pending_calls(loaded)
        read_execute.assert_not_called()
        edit_execute.assert_not_called()

    checks = {
        "识别出缺结果的编辑": len(final_pending) == 1 and final_pending[0].call == edit_call,
        "已配对读取被移除": all(item.call.id != "call_001" for item in final_pending),
        "演示文件实际上已经修改": target.read_text(encoding="utf-8") == after,
        "检查没有修改会话记录": store.path.read_bytes() == recorded_bytes,
        "检查阶段没有执行工具": True,
    }
    report = {
        "scope": "助手构造请求，真实读取和编辑，刻意省略编辑结果及结束记录；模拟中断窗口。未请求模型服务，未运行业务测试，未实际重放或恢复调用。",
        "session_file": str(store.path),
        "edited_file": str(target),
        "before": before,
        "actual_after": target.read_text(encoding="utf-8"),
        "progress": progress,
        "pending": [asdict(item) for item in final_pending],
        "checks": checks,
    }
    (run_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
