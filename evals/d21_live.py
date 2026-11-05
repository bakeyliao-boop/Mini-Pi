"""D21真实试跑。保存可审阅协议后通过显式入口执行。"""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil

from evals.d21_dry_run import run_case
from evals.d21_preview import ROOT, load_case
from evals.d21_task2 import load_task2
from evals.logs import save_json
from mini_pi.compaction_restore import read_saved_compaction
from mini_pi.models import Message
from mini_pi.qwen_client import QwenProvider
from mini_pi.session_store import SessionStore


def load_plan(task="edit-history"):
    plan = json.loads((ROOT / "evals/cases/d21_live_pilot.json").read_text(encoding="utf-8"))
    if task == "config-tail":
        plan.update(protocol_id="d21-config-tail-live-pilot-v1", task_id="d21-config-tail-2",
                    scope="Second task, one run per variant; inspect summary and file outcome separately",
                    answer_requests_per_variant=4, max_total_requests=13)
    elif task != "edit-history":
        raise ValueError("未知D21任务")
    return plan


def validate_plan(plan, task="edit-history"):
    answer_cap = 4 if task == "config-tail" else 3
    if (plan["variants"] != ["A", "B", "C"] or plan["answer_requests_per_variant"] != answer_cap
            or plan["summary_requests_in_C"] != 1 or plan["max_total_requests"] != 3 * answer_cap + 1
            or plan["automatic_retries"] != 0):
        raise ValueError(f"本协议允许A/B/C各一次，回答各最多{answer_cap}次，C另有1次摘要，重试次数为0")


def read_bailian_key(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entry = data.get("bailian", {})
    key = entry.get("key")
    if entry.get("type") != "api_key" or not isinstance(key, str) or not key.startswith("sk-") or "\n" in key or "\r" in key:
        raise ValueError("当前文件没有本入口支持的百炼字面API Key配置")
    return key


def prepare_pilot(directory, auth_file, *, task="edit-history"):
    # 仅核对配置可读取；不证明服务权限、余额或模型可用，也不发送请求。
    read_bailian_key(auth_file)
    plan = load_plan(task)
    validate_plan(plan, task)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    case = deepcopy(load_task2() if task == "config-tail" else load_case())
    initial = directory / "initial-source"
    shutil.copytree(ROOT / case["initial_directory"], initial)
    case["initial_directory"] = str(initial)
    protocol = {"schema": "mini-pi-d21-live-pilot/v1", "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
                "task": task, "plan": plan, "case": case, "auth_file": str(Path(auth_file).resolve()),
                "credential_source": "existing_pi_bailian_entry", "credential_config_readable": True,
                "real_model_requests": 0, "protocol_path": str(directory / "protocol.json")}
    save_json(directory / "protocol.json", protocol)
    save_json(directory / "state.json", {"state": "prepared", "real_model_requests": 0})
    return protocol


def redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[REDACTED]")
    if isinstance(value, list):
        return [redact(item, key) for item in value]
    if isinstance(value, dict):
        return {redact(name, key): redact(item, key) for name, item in value.items()}
    return value


class CapturedQwen:
    """只记录入参并透传既有真实适配器；发送次数由QwenProvider原有上限控制。"""

    def __init__(self, key, plan, max_requests):
        self._key = key
        self.provider = QwenProvider(api_key=key, model=plan["model"], base_url=plan["base_url"],
                                     timeout=plan["request_timeout_seconds"], max_requests=max_requests,
                                     max_completion_tokens=plan["max_completion_tokens"])
        self.max_completion_tokens = self.provider.max_completion_tokens
        self.requests = []
        self.tool_requests = []

    async def generate(self, history, tools):
        self.requests.append(deepcopy(list(history)))
        self.tool_requests.append(deepcopy(list(tools)))
        try:
            message = deepcopy(await self.provider.generate(history, tools))
        except Exception as error:
            raise RuntimeError(redact(f"{type(error).__name__}: {error}", self._key)) from None
        message.content = redact(message.content, self._key)
        message.error_message = redact(message.error_message, self._key)
        for call in message.tool_calls:
            call.arguments = redact(call.arguments, self._key)
            call.raw_arguments = redact(call.raw_arguments, self._key)
        return message

    def safe_records(self):
        return redact(deepcopy(self.provider.request_records), self._key)


def summarize_usage(records):
    fields = ("prompt_tokens", "completion_tokens", "total_tokens")
    observed = {field: [] for field in fields}
    complete = bool(records)
    for record in records:
        usage = record.get("usage")
        valid = record.get("status") == "received" and isinstance(usage, dict)
        for field in fields:
            value = usage.get(field) if isinstance(usage, dict) else None
            if type(value) is int and value >= 0:
                observed[field].append(value)
            else:
                valid = False
        complete &= valid
    # 缓存token若已包含于prompt，不能再次加到total；原始细项仍在请求记录里。
    totals = {field: sum(values) if complete else None for field, values in observed.items()}
    return {"complete": bool(complete), "requests_observed": len(records), **totals,
            "known_subtotals": {field: sum(values) if values else None for field, values in observed.items()}}


def telemetry(answer, summary):
    phases = {"answer": answer.safe_records(), "summary": summary.safe_records() if summary is not None else []}
    records = phases["answer"] + phases["summary"]
    usage = summarize_usage(records)
    return {"real_model_requests": len(records), "provider_requests": phases, "usage": usage,
            "actual_usage": {field: usage[field] for field in ("prompt_tokens", "completion_tokens", "total_tokens")} if usage["complete"] else None,
            "model_identity_source": "actual request record; service returned_model recorded separately"}


def skipped_group(reason):
    return {"execution_status": "not_started", "run_status": "not_started", "case_verdict": "unverified",
            "reason": reason, "real_model_requests": 0, "actual_usage": None}


def config_tail_observations(report, case):
    session = SessionStore(Path(report["session_path"])).load()
    saved = read_saved_compaction(session)
    summary_text = saved[0] if saved is not None else None
    last = session.history[-1]
    final_reply = None
    if report["run_status"] == "finished" and isinstance(last, Message) and last.role == "assistant" and not last.tool_calls:
        final_reply = last.content or None

    value = re.escape(case["task_data"]["approved_value"])
    exact_value = re.compile(rf"(?<![a-zA-Z0-9_-]){value}(?![a-zA-Z0-9_-])")
    phases = report["provider_requests"]
    first_has_value = None
    if phases["answer"]:
        messages = phases["answer"][0]["request_body"]["messages"]
        first_has_value = any(exact_value.search(item.get("content") or "") for item in messages)
    source_has_full_read = None
    if phases["summary"]:
        history = case["constructed_history"]
        notes = (Path(case["initial_directory"]) / history["background_file"]).read_text(encoding="utf-8")
        messages = phases["summary"][0]["request_body"]["messages"]
        source = json.loads(messages[1]["content"])
        source_has_full_read = any(row["type"] == "tool_result" and
                                   row["data"]["tool_call_id"] == history["historical_read_call_id"] and
                                   row["data"]["output"] == notes for row in source)
    return {"first_answer_has_approved_value": first_has_value, "summary_text": summary_text,
            "summary_has_approved_value": bool(exact_value.search(summary_text)) if summary_text is not None else None,
            "summary_source_has_full_read": source_has_full_read, "final_reply": final_reply}


async def run_live_pilot(directory):
    directory = Path(directory).resolve()
    protocol = json.loads((directory / "protocol.json").read_text(encoding="utf-8"))
    state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    if state["state"] != "prepared":
        raise ValueError("该目录已经启动过，禁止自动重跑真实请求")
    task = protocol.get("task", "edit-history")
    plan = protocol["plan"]
    validate_plan(plan, task)
    if plan != load_plan(task):
        raise ValueError("当前试跑配置已变化，请先重新准备可审阅协议")
    case = protocol["case"]
    if case["id"] != plan["task_id"]:
        raise ValueError("冻结案例与试跑协议不一致")
    key = read_bailian_key(protocol["auth_file"])
    try:
        (directory / "execution.lock").open("x").close()
    except FileExistsError:
        raise ValueError("该目录已经启动过，禁止自动重跑真实请求") from None
    save_json(directory / "state.json", {"state": "started", "real_model_requests": 0})
    groups = {}
    stop_reason = None
    for name in plan["variants"]:
        if stop_reason is not None:
            groups[name] = skipped_group(stop_reason)
            continue
        answer = CapturedQwen(key, plan, plan["answer_requests_per_variant"])
        summary = CapturedQwen(key, plan, plan["summary_requests_in_C"]) if name == "C" else None
        report = await run_case(directory / name, name, case, max_answer_turns=plan["answer_requests_per_variant"],
                                answer_provider=answer, summary_provider=summary, run_config=plan,
                                mode="live_bailian_pilot", telemetry=lambda a=answer, s=summary: telemetry(a, s))
        if task == "config-tail":
            report.update(config_tail_observations(report, case))
        report["execution_status"] = "executed"
        groups[name] = report
        save_json(directory / name / "provider-requests.json", report["provider_requests"])
        save_json(directory / name / "result.json", report)
        records = report["provider_requests"]["answer"] + report["provider_requests"]["summary"]
        # 任务未做对或正常耗尽轮数仍继续记录其他组；接口/取消等运行故障停止后续付费。
        if report["run_status"] in ("exception", "error", "cancelled", "timeout") or any(row["status"] != "received" for row in records):
            stop_reason = f"{name}组发生运行或服务请求故障，后续组未启动；不重试、不换预算"
        save_json(directory / "state.json", {"state": "started", "real_model_requests": sum(item["real_model_requests"] for item in groups.values())})
    records = [record for item in groups.values() if item["execution_status"] == "executed"
               for phase in ("answer", "summary") for record in item["provider_requests"][phase]]
    usage = summarize_usage(records)
    cohort_complete = all(groups[name]["execution_status"] == "executed" for name in plan["variants"])
    scores_available = cohort_complete and all(item["case_verdict"] in ("passed", "failed") for item in groups.values())
    integrity = all(item["pipeline_checks"]["original_history_preserved"] and item["pipeline_checks"]["no_historical_call_replay"]
                    and item["pipeline_checks"]["summary_policy_exercised"] for item in groups.values() if item["execution_status"] == "executed")
    result = {"schema": protocol["schema"], "mode": "live_bailian_pilot", "protocol_id": plan["protocol_id"],
              "groups": groups, "real_model_requests": len(records), "max_total_requests": plan["max_total_requests"],
              "usage": usage, "actual_usage": {field: usage[field] for field in ("prompt_tokens", "completion_tokens", "total_tokens")} if usage["complete"] else None,
              "cohort_complete": cohort_complete, "telemetry_complete": usage["complete"],
              "task_scores_available": scores_available,
              "pilot_observations_complete": cohort_complete and usage["complete"] and integrity and scores_available,
              "all_tasks_passed": cohort_complete and all(item["case_verdict"] == "passed" for item in groups.values()),
              "total_agent_run_seconds": sum(item.get("run_elapsed_seconds", 0) for item in groups.values()),
              "stop_reason": stop_reason, "effectiveness_verified": False,
              "scope": plan["scope"] if task == "config-tail" else "First task, one run per variant; no general winner or stability conclusion"}
    save_json(directory / "result.json", result)
    save_json(directory / "state.json", {"state": "finished" if cohort_complete else "stopped", "real_model_requests": len(records)})
    title = "# D21 第二任务真实试跑" if task == "config-tail" else "# D21：首轮真实模型试跑"
    lines = [title, "", "同一任务每组运行一次。", "",
             "| 组别 | 执行状态 | 运行状态 | 实际文件 | 任务判定 | 真实请求数（含摘要） |",
             "| --- | --- | --- | --- | --- | --- |"]
    for name, item in groups.items():
        content = (item.get("actual_content") or "未获得").replace("\n", " / ")
        lines.append(f"| {name} | {item['execution_status']} | {item['run_status']} | `{content}` | {item['case_verdict']} | {item['real_model_requests']} |")
    lines += ["", f"请求总数：{len(records)} / {plan['max_total_requests']}。摘要与回答都已计入；耗时取完整运行及收尾，不再重复累加摘要请求耗时。",
              "", f"服务usage完整：{usage['complete']}；总tokens：{usage['total_tokens']}。字段来自服务原始usage，不是字符估算。",
              "", "HTTP429等服务状态不能单凭状态码断定余额耗尽；具体原因须另行核实。"]
    if task == "config-tail":
        lines += ["", "| 组别 | 首次回答输入出现准确值 | 摘要出现准确值 | 摘要材料含完整读取 |",
                  "| --- | --- | --- | --- |"]
        for name, item in groups.items():
            lines.append(f"| {name} | {item.get('first_answer_has_approved_value')} | {item.get('summary_has_approved_value')} | {item.get('summary_source_has_full_read')} |")
        lines += ["", "准确值字段检查字面出现情况。请结合真实摘要上下文确认它是否把该值作为批准值，文件和最终答复单独核对。", "", "## C 组实际摘要", "", groups["C"].get("summary_text") or "未获得摘要"]
    else:
        lines += ["", "此轮不包含第二任务及重复试验。"]
    (directory / "review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result
