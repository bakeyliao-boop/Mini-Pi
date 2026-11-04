"""D20：Pi smoke 的独立判定、离线排演及显式百炼真实调用。"""

import asyncio
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from evals.logs import save_json
from mini_pi.bootstrap import ToolBundle
from mini_pi.cli import _wait_for_command_idle
from mini_pi.harness import Harness, RunBudget
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolResult
from mini_pi.qwen_client import QwenProvider
from mini_pi.session_store import SessionStore
from mini_pi.tools.tool_router import ToolRouter


CASE_PATH = Path(__file__).parent / "cases" / "pi_smoke.json"
# 使用 JavaScript trim 的空白字符范围，避免悄悄改变原样例的输出判定。
TRIM_CHARS = "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


def load_case():
    return json.loads(CASE_PATH.read_text(encoding="utf-8"))


def judge_smoke(output, errors, expected_identity, observed_identity=None, usage=None):
    """保留五项原判定；未获得的模型身份和用量记为未验证。"""
    case = load_case()
    checks = {}

    def add(name, actual, expected, passed, *, observed=True):
        checks[name] = {
            "status": ("passed" if passed else "failed") if observed else "unverified",
            "actual": actual, "expected": expected,
        }

    normalized = output.strip(TRIM_CHARS)
    add("output_matches", normalized, case["expected_output"], normalized == case["expected_output"])
    add("no_errors", errors, [], errors == [])
    identity = observed_identity or {}
    for field in ("provider", "model"):
        actual = identity.get(field)
        add(field + "_matches", actual, expected_identity[field],
            actual == expected_identity[field], observed=actual is not None)
    total = usage.get("total_tokens") if usage is not None else None
    add("usage_positive", total, "> 0", type(total) in (int, float) and total > 0,
        observed=total is not None)
    statuses = {item["status"] for item in checks.values()}
    verdict = "failed" if "failed" in statuses else "unverified" if "unverified" in statuses else "passed"
    return {"case_verdict": verdict, "checks": checks}


async def run_offline_smoke(output_dir, *, answer="Paris", simulated_error=None,
                            expected_provider="bailian", expected_model="qwen3.8-flash"):
    """运行现有 Harness，模型回复来自脚本，不访问模型服务。"""
    def respond(history, tools):
        if simulated_error is not None:
            raise RuntimeError(simulated_error)
        return Message("assistant", answer, stop_reason="stop")

    return await _execute_smoke(
        output_dir, lambda: MockProvider([respond]), mode="offline_scripted",
        identity={"provider": expected_provider, "model": expected_model},
        extra_protocol={"scripted_response": {"output": answer, "error": simulated_error}},
    )


async def run_live_smoke(output_dir, *, api_key=None, auth_file=None, model="qwen3.8-flash"):
    """只请求一次现有百炼适配器；凭证不进入协议、请求日志或结果。"""
    case = load_case()

    def create_provider():
        key = api_key
        if auth_file is not None:
            auth = json.loads(Path(auth_file).read_text(encoding="utf-8"))
            entry = auth.get("bailian", {})
            key = entry.get("key")
            if entry.get("type") != "api_key" or not isinstance(key, str) or not key.startswith("sk-"):
                raise ValueError("Pi 百炼配置没有本入口支持的字面 API Key")
        return QwenProvider(
            api_key=key, model=model, max_requests=1, max_completion_tokens=128,
            timeout=case["mini_pi_budget"]["total_timeout_seconds"],
        )

    return await _execute_smoke(
        output_dir, create_provider, mode="live_bailian",
        identity={"provider": "bailian", "model": model},
        extra_protocol={"provider_configuration": {
            "provider": "bailian", "model": model,
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "max_requests": 1, "max_completion_tokens": 128,
            "credential_source": "Pi bailian auth entry" if auth_file is not None else "explicit key or DASHSCOPE_API_KEY",
        }},
    )


async def _execute_smoke(output_dir, provider_factory, *, mode, identity, extra_protocol):
    """两种模式共用同一套原题、Harness、日志和独立判定。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)  # 每次使用新目录，保留已有日志。
    case = load_case()
    run_id = "d20-smoke-" + uuid4().hex
    protocol = {
        "schema": "mini-pi-d20-smoke/v1", "run_id": run_id,
        "mode": mode, "case": case,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "expected_identity": identity,
        "budget_origin": "Mini-Pi execution limit, not an upstream Pi assertion",
        **extra_protocol,
    }
    save_json(output_dir / "protocol.json", protocol)

    # 模型看不到工具定义；即使出现工具请求，空路由器也没有可执行工具。
    tools = ToolBundle(ToolRouter({}), [], frozenset())
    provider = None
    harness = None
    store = SessionStore(output_dir / "session.jsonl", run_id)
    started = perf_counter()
    result = None
    exception = None
    cancelled = False
    stage = "provider_configuration"
    try:
        provider = provider_factory()
        harness = Harness(provider, tools, budget=RunBudget(**case["mini_pi_budget"]))
        stage = "running"
        result = await harness.run(case["prompt"], store)
    except asyncio.CancelledError:
        cancelled = True
        exception = {"type": "CancelledError", "message": "evaluation caller cancelled"}
    except Exception as error:
        exception = {"type": type(error).__name__, "message": str(error), "stage": stage}
    finally:
        if harness is not None and harness.agent.is_running:
            harness.agent.abort()
            await _wait_for_command_idle(harness)  # 复用既有稳定收尾，重复取消也要等工作结束。
    elapsed = perf_counter() - started
    observed_identity = None
    usage = None
    returned_model = None
    if mode == "live_bailian":
        requests = deepcopy(provider.request_records) if provider is not None else []
        received = [record for record in requests if record["status"] == "received"]
        if received:
            last = received[-1]
            # Pi 原例的 provider/model 也取自所选运行配置；这里核对实际发出的模型标识。
            observed_identity = {"provider": "bailian", "model": last["requested_model"]}
            returned_model = last["returned_model"]
            usage = deepcopy(last["usage"])
        telemetry_note = "Identity from selected Bailian adapter and recorded request; usage and returned model from service response"
    else:
        requests = [{"request": index, "history": [asdict(item) for item in history],
                     "tools": [asdict(tool) for tool in provider.tool_requests[index - 1]]}
                    for index, history in enumerate(provider.requests, 1)] if provider is not None else []
        telemetry_note = "Scripted response: no real provider/model identity or service usage observed"
    save_json(output_dir / "requests.json", requests)

    loaded = store.load() if store.path.exists() else None
    messages = result.messages if result is not None else loaded.history if loaded is not None else []
    output = ""
    if messages and isinstance(messages[-1], Message) and messages[-1].role == "assistant":
        output = messages[-1].content
    errors = [result.error] if result is not None and result.error else []
    if exception is not None:
        errors.append(exception["message"])
    for item in messages:
        reason = item.error if isinstance(item, ToolResult) else item.error_message
        if reason and reason not in errors:
            errors.append(reason)
    report = {
        "schema": protocol["schema"], "case_id": case["id"], "run_id": run_id,
        "mode": mode, "native_pi_evaluation": False,
        "run_status": result.status if result is not None else "cancelled" if cancelled else "exception",
        "run_task_passed": result.task_passed if result is not None else None,
        "exception": exception,
        "session_has_run_end": loaded is not None and any(record["type"] == "run_end" for record in loaded.records),
        "output": output, "errors": errors, "elapsed_seconds": round(elapsed, 6),
        "model_requests": len(requests), "expected_identity": identity,
        "observed_identity": observed_identity, "returned_model": returned_model, "usage": usage,
        "telemetry_note": telemetry_note,
        **judge_smoke(output, errors, identity, observed_identity, usage),
    }
    save_json(output_dir / "result.json", report)
    return report


def verdict_exit_code(report):
    return {"passed": 0, "failed": 1, "unverified": 2}[report["case_verdict"]]
