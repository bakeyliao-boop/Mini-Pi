"""运行：python -X utf8 -m examples.d05_read_file。仅执行本地读取工具。"""

import asyncio
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from mini_pi.models import ToolCall
from mini_pi.tools.read_file import ReadFileExecutor


async def main():
    repository = Path(__file__).resolve().parents[1]
    evidence = repository / "local-learning" / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    records = []

    with TemporaryDirectory(prefix="_d05_read_file_", dir=evidence) as directory:
        workdir = Path(directory).resolve()
        workdir.relative_to(evidence.resolve())
        (workdir / "discount.py").write_text(
            "def final_price(price, discount_rate):\n    return price * discount_rate\n",
            encoding="utf-8",
        )
        executor = ReadFileExecutor(workdir)
        scenarios = [
            ("读取成功", ToolCall("call_001", "read_file", {"path": "discount.py"})),
            ("文件不存在", ToolCall("call_002", "read_file", {"path": "missing.txt"})),
            ("参数不合法", ToolCall("call_003", "read_file", {"path": 123})),
        ]
        for scenario, call in scenarios:
            result = await executor.execute(call)
            records.append({"scenario": scenario, "call": asdict(call), "result": asdict(result)})

    report = {"scope": "本地读取工具验证，未调用模型，未验证折扣修复", "records": records}
    report_path = evidence / "d05-read-file-results.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"结果已保存：{report_path}")


if __name__ == "__main__":
    asyncio.run(main())
