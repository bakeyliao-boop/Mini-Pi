"""D07：--check-config 只检查本地配置；--live 才实际请求模型服务。"""

import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

from mini_pi.loop import run_loop
from mini_pi.models import Message
from mini_pi.qwen_client import QwenProvider
from mini_pi.tools.read_file import ReadFileExecutor


class RecordedReader:
    """实际读取工具的日志包装，不改变工具的校验或执行逻辑。"""

    def __init__(self, reader):
        self.reader = reader
        self.records = []

    async def execute(self, call):
        result = await self.reader.execute(call)
        self.records.append({"call": asdict(deepcopy(call)), "result": asdict(result)})
        return result


def check_evidence(run, executions, requests, source, marker):
    successful_reads = [
        record for record in executions
        if record["call"]["name"] == "read_file"
        and record["call"]["arguments"] == {"path": "discount.py"}
        and record["result"]["error"] is None
        and record["result"]["output"] == source
    ]
    read_ids = {record["call"]["id"] for record in successful_reads}
    sent_back = False
    for request in requests:
        for message in request["request_body"].get("messages", []):
            if message.get("role") == "tool" and message.get("tool_call_id") in read_ids:
                try:
                    payload = json.loads(message["content"])
                except (KeyError, TypeError, ValueError):
                    continue
                if isinstance(payload, dict) and payload.get("output") == source and payload.get("error") is None:
                    sent_back = True
    final_text = ""
    if run and run.messages and isinstance(run.messages[-1], Message):
        final_text = run.messages[-1].content
    usages_present = bool(requests) and all(
        record["status"] == "received"
        and isinstance(record["usage"], dict)
        and all(type(record["usage"].get(key)) is int for key in ("prompt_tokens", "completion_tokens", "total_tokens"))
        for record in requests
    )
    return {
        "run_finished": run is not None and run.status == "finished",
        "matching_file_actually_read": bool(successful_reads),
        "call_result_ids_match": bool(executions) and all(
            record["call"]["id"] == record["result"]["tool_call_id"]
            and record["call"]["name"] == record["result"]["tool_name"]
            for record in executions
        ),
        "tool_result_sent_to_later_model_request": sent_back,
        "final_answer_contains_file_marker": marker in final_text,
        "supplier_usage_recorded": usages_present,
    }


async def run_demo(provider):
    repository = Path(__file__).resolve().parents[1]
    evidence = repository / "local-learning" / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex
    marker = "d07-" + run_id[:12]
    source = (
        "# 验证标记: " + marker + "\n"
        "def final_price(price, discount_rate):\n"
        "    return price * discount_rate\n"
    )
    run = None
    error = None
    with TemporaryDirectory(prefix="_d07_qwen_", dir=evidence) as directory:
        workdir = Path(directory).resolve()
        workdir.relative_to(evidence.resolve())
        (workdir / "discount.py").write_text(source, encoding="utf-8")
        reader = ReadFileExecutor(workdir)
        executor = RecordedReader(reader)
        started = perf_counter()
        try:
            run = await run_loop(
                provider,
                executor,
                [
                    Message("system", "使用提供的工具完成读取。只依据实际工具结果说明文件内容。"),
                    Message("user", "请先调用 read_file 读取 discount.py，解释 final_price 函数实际返回的含义，最后原样引用文件中的验证标记。只解释，不修改文件。"),
                ],
                [reader.definition],
            )
        except (RuntimeError, ValueError) as failure:
            error = {"type": type(failure).__name__, "message": str(failure)}
        except Exception as failure:
            error = {"type": type(failure).__name__, "message": "响应处理失败，请核对接口结构；未输出原始响应或凭证。"}
        elapsed = round(perf_counter() - started, 6)

    checks = check_evidence(run, executor.records, provider.request_records, source, marker)
    passed = all(checks.values())
    report = {
        "scope": "真实模型调用与实际本地读取；只使用临时示例文件，未验证折扣修复",
        "mode": "live",
        "requested_model": provider.model,
        "endpoint": provider.endpoint,
        "elapsed_seconds": elapsed,
        "limits": {"max_requests": provider.max_requests, "max_completion_tokens": provider.max_completion_tokens},
        "requests": provider.request_records,
        "tool_executions": executor.records,
        "run": asdict(run) if run is not None else None,
        "error": error,
        "checks": checks,
        "automatic_checks_passed": passed,
        "manual_review": "还需人工核对模型对代码含义的解释；自动检查不证明折扣修复正确。",
    }
    path = evidence / ("d07-qwen-" + run_id + ".json")
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    path.write_text(output, encoding="utf-8")
    print(output, end="")
    print(f"执行轨迹已保存：{path}")
    return 0 if passed else 2


def main():
    parser = argparse.ArgumentParser(description="D07 Qwen 接入示例，不在输出中显示密钥。")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check-config", action="store_true", help="只检查本地配置，不发送请求")
    modes.add_argument("--live", action="store_true", help="实际请求模型并消耗服务额度，最多 4 次请求")
    args = parser.parse_args()
    try:
        provider = QwenProvider(
            model=os.getenv("QWEN_MODEL", "qwen3.8-flash"),
            base_url=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )
    except ValueError as error:
        print(json.dumps({"status": "configuration_error", "message": str(error), "model_requests": 0}, ensure_ascii=False, indent=2))
        return 1
    if args.check_config:
        print(json.dumps({
            "status": "configured",
            "scope": "仅本地配置检查，未验证凭证有效性或模型权限",
            "model": provider.model,
            "endpoint": provider.endpoint,
            "credential_configured": True,
            "model_requests": 0,
        }, ensure_ascii=False, indent=2))
        return 0
    return asyncio.run(run_demo(provider))


if __name__ == "__main__":
    raise SystemExit(main())
