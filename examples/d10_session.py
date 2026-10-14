"""D10：模拟模型配合实际读取，逐条保存 JSONL；不实现加载恢复。"""

import asyncio
from dataclasses import asdict
import json
from pathlib import Path
from uuid import uuid4

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore
from mini_pi.tools.read_file import ReadFileExecutor


async def main() -> int:
    project = Path(__file__).resolve().parents[1]
    run_id = uuid4().hex
    run_dir = project / "local-learning" / "evidence" / f"d10-{run_id}"
    workdir = run_dir / "workspace"
    workdir.mkdir(parents=True)
    source = "def final_price(price, discount_rate):\n    return price * discount_rate\n"
    (workdir / "discount.py").write_text(source, encoding="utf-8", newline="")
    reader = ReadFileExecutor(workdir)
    store = SessionStore(run_dir / "session.jsonl", run_id)
    request = Message("assistant", "先读取文件。", [
        ToolCall("call_001", "read_file", {"path": "discount.py"}),
    ])

    def answer(history, tools):
        result = history[-1]
        if not isinstance(result, ToolResult) or result.error is not None:
            raise AssertionError("示例应收到实际读取成功的工具结果")
        return Message("assistant", "已读取文件：\n" + result.output + "本次未修改或验证折扣公式。")

    provider = MockProvider([request, answer])
    run = await run_loop(
        provider, reader,
        [Message("user", "读取 discount.py 并展示内容。")],
        [reader.definition], store,
    )
    entries = [json.loads(line) for line in store.path.read_text(encoding="utf-8").splitlines()]
    checks = {
        "六条记录顺序正确": [entry["type"] for entry in entries] == [
            "run_start", "message", "message", "tool_result", "message", "run_end",
        ],
        "运行标识一致": all(entry["run_id"] == run_id for entry in entries),
        "时间戳已保存": all(entry["timestamp"] for entry in entries),
        "请求与结果ID配对": entries[2]["data"]["tool_calls"][0]["id"] == entries[3]["data"]["tool_call_id"],
        "磁盘消息与内存历史一致": [
            entry["data"] for entry in entries if entry["type"] in {"message", "tool_result"}
        ] == [asdict(item) for item in run.messages],
        "下一次请求收到工具结果": provider.requests[1][-1].output == source,
        "结束状态不等于验收通过": entries[-1]["data"] == {
            "status": "finished", "task_passed": None, "error": None,
        },
    }
    summary = {
        "scope": "模拟模型、实际循环和读取、逐条写入会话；未调用模型服务，未修复折扣，未验证加载恢复。",
        "run_id": run_id,
        "session_file": str(store.path),
        "mock_model_requests": len(provider.requests),
        "model_service_requests": 0,
        "records": len(entries),
        "checks": checks,
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
