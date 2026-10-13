"""助手准备：四工具实际联调；调用顺序预先编排，不调用模型服务。"""

import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys
from uuid import uuid4

from mini_pi.models import ToolCall
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy
from mini_pi.tools.list_files import ListFilesExecutor
from mini_pi.tools.read_file import ReadFileExecutor
from mini_pi.tools.run_tests import RunTestsExecutor
from mini_pi.tools.tool_router import ToolRouter


async def main() -> int:
    project = Path(__file__).resolve().parents[1]
    evidence = project / "local-learning" / "evidence" / f"d09-{uuid4().hex}"
    workdir = evidence / "workspace"
    workdir.mkdir(parents=True)
    source = "def final_price(price, discount_rate):\n    return price * discount_rate\n"
    (workdir / "discount.py").write_text(source, encoding="utf-8", newline="")
    (workdir / "test_discount.py").write_text(
        "import unittest\n"
        "from discount import final_price\n\n"
        "class DiscountTests(unittest.TestCase):\n"
        "    def test_twenty_percent_off(self):\n"
        "        self.assertEqual(final_price(100, 0.2), 80)\n",
        encoding="utf-8",
        newline="",
    )
    reader = ReadFileExecutor(workdir)
    editor = EditFileExecutor(EditPolicy(workdir, ["discount.py"]))
    lister = ListFilesExecutor(workdir)
    tester = RunTestsExecutor(
        workdir,
        (sys.executable, "-B", "-X", "utf8", "-m", "unittest", "discover",
         "-s", ".", "-p", "test_discount.py", "-v"),
        workdir / "logs",
    )
    router = ToolRouter({
        "list_files": lister,
        "read_file": reader,
        "edit_file": editor,
        "run_tests": tester,
    })
    steps = [
        ("列出文件", ToolCall("call_001", "list_files", {})),
        ("目录不存在", ToolCall("call_002", "list_files", {"path": "missing"})),
        ("读取原代码", ToolCall("call_003", "read_file", {"path": "discount.py"})),
        ("文件不存在", ToolCall("call_004", "read_file", {"path": "missing.py"})),
        ("修改前测试", ToolCall("call_005", "run_tests", {})),
        ("旧文本不匹配", ToolCall("call_006", "edit_file", {
            "path": "discount.py", "old_text": "不存在的旧文本", "new_text": "不应写入",
        })),
        ("修正公式", ToolCall("call_007", "edit_file", {
            "path": "discount.py",
            "old_text": "return price * discount_rate",
            "new_text": "return price * (1 - discount_rate)",
        })),
        ("修改后测试", ToolCall("call_008", "run_tests", {})),
    ]
    records = []
    rejected_edit_did_not_write = False
    for label, call in steps:
        result = await router.execute(call)
        record = {"step": label, "call": asdict(call), "result": asdict(result)}
        if call.name == "run_tests":
            record["test_report"] = json.loads(result.output)
        if call.id == "call_006":
            rejected_edit_did_not_write = (
                (workdir / "discount.py").read_text(encoding="utf-8") == source
            )
        records.append(record)
        outcome = record.get("test_report", {}).get("outcome")
        print(f"{call.id} {label}：{outcome or result.error or '执行成功'}")

    before_test = records[4]["test_report"]
    after_test = records[7]["test_report"]
    checks = {
        "调用与结果逐一配对": all(
            record["call"]["id"] == record["result"]["tool_call_id"]
            for record in records
        ),
        "四工具成功与失败均有记录": all(
            record["result"]["error"] is not None for record in (records[1], records[3], records[5])
        ) and all(
            record["result"]["error"] is None for record in (records[0], records[2], records[6])
        ) and before_test["outcome"] == "tests_failed" and after_test["outcome"] == "tests_passed",
        "修改前真实用例失败": before_test["exit_code"] == 1,
        "拒绝的编辑没有写入": rejected_edit_did_not_write,
        "修改后真实用例通过": after_test["exit_code"] == 0,
        "测试失败仍保留日志": "AssertionError" in before_test["output"],
    }
    report = {
        "scope": "助手编排调用；四工具真实执行；独立演示目录内的折扣用例实际失败后通过。未调用模型服务，未运行模型驱动的 Agent 循环。",
        "model_requests": 0,
        "workdir": str(workdir),
        "records": records,
        "checks": checks,
    }
    record_path = evidence / "trace.json"
    record_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"检查：{json.dumps(checks, ensure_ascii=False)}")
    print(f"完整记录：{record_path}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
