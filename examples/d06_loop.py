"""运行：python -X utf8 -m examples.d06_loop。模拟模型请求，实际读取临时文件。"""

import asyncio
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.tools.read_file import ReadFileExecutor


def answer_from_result(history, tools):
    result = history[-1]
    if not isinstance(result, ToolResult) or result.tool_call_id != "call_001":
        raise AssertionError("第二次请求必须包含 call_001 的工具结果")
    if result.error is not None:
        return Message(role="assistant", content="读取失败：" + result.error)
    return Message(
        role="assistant",
        content="已读取文件，内容如下：\n" + result.output + "本次未修改代码，未验证折扣修复。",
    )


async def main():
    repository = Path(__file__).resolve().parents[1]
    evidence = repository / "local-learning" / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    provider = MockProvider([
        Message(
            role="assistant",
            content="先读取 discount.py。",
            tool_calls=[ToolCall("call_001", "read_file", {"path": "discount.py"})],
        ),
        answer_from_result,
    ])

    with TemporaryDirectory(prefix="_d06_loop_", dir=evidence) as directory:
        workdir = Path(directory).resolve()
        workdir.relative_to(evidence.resolve())
        (workdir / "discount.py").write_text(
            "def final_price(price, discount_rate):\n    return price * discount_rate\n",
            encoding="utf-8",
        )
        executor = ReadFileExecutor(workdir)
        run = await run_loop(
            provider,
            executor,
            [Message(role="user", content="读取 discount.py 并展示内容。")],
            [executor.definition],
        )

    steps = []
    for index, history in enumerate(provider.requests):
        steps.append({
            "event": "model_request",
            "request": index + 1,
            "history": [asdict(item) for item in history],
            "tools": [asdict(tool) for tool in provider.tool_requests[index]],
        })
        response_index = len(history)
        steps.append({"event": "assistant_response", "message": asdict(run.messages[response_index])})
        for item in run.messages[response_index + 1:]:
            if not isinstance(item, ToolResult):
                break
            steps.append({"event": "tool_result", "result": asdict(item)})
    steps.append({"event": "run_end", "status": run.status, "task_passed": run.task_passed})
    report = {
        "scope": "模拟模型 + 实际本地读取 + 实际循环；未调用模型服务，未验证折扣修复",
        "steps": steps,
        "run": asdict(run),
    }
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    report_path = evidence / "d06-loop-trace.json"
    report_path.write_text(output, encoding="utf-8")
    print(output, end="")
    print(f"执行轨迹已保存：{report_path}")


if __name__ == "__main__":
    asyncio.run(main())
