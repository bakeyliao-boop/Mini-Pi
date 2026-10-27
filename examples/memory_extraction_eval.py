"""MEM-W评测辅助：默认只预览；--live按已授权固定计划最多6次，不评分语义。"""

import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
from time import perf_counter


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_pi.memory.extraction_client import MemoryExtractor, build_extraction_request
from mini_pi.memory.models import MemoryScope, MemorySource
from mini_pi.memory.selection import route_candidates


FIXTURE = ROOT / "examples/fixtures/memory_extraction_eval_v1.json"
MODEL = "qwen3.8-flash"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MAX_REQUESTS = 6
OUTPUT_TOKENS = 1536


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def load_dataset(path=FIXTURE):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    config = data["run_config"]
    expected = {"model": MODEL, "base_url": BASE_URL, "region": "华北2（北京）", "max_requests": MAX_REQUESTS,
                "max_completion_tokens": OUTPUT_TOKENS, "automatic_retries": 0,
                "extra_judge_api_calls": 0, "enable_thinking": False, "stream": False, "serial": True,
                "timeout_seconds": 30}
    if any(config.get(key) != value for key, value in expected.items()):
        raise ValueError("评测配置与已确认计划不一致")
    if [case["case_id"] for case in data["cases"]] != [f"S{i}" for i in range(1, 7)]:
        raise ValueError("评测必须使用已确认的S1至S6")
    if sum(len(case["required_units"]) for case in data["cases"]) != 9:
        raise ValueError("评测标注必须包含九个必需语义单元")
    return data


def preview_plan(data=None):
    data = load_dataset() if data is None else data
    scope = MemoryScope(**data["scope"])
    requests = []
    for case in data["cases"]:
        source = MemorySource(scope=scope, **case["source"])
        payload = build_extraction_request(MODEL, scope, source)
        material = json.loads(payload["messages"][1]["content"])
        if material != {"role": source.role, "recorded_at": source.recorded_at, "text": source.text}:
            raise ValueError("预览包含非Source材料")
        requests.append({"case_id": case["case_id"], "request": payload})
    return {"mode": "preview", "real_model_calls": 0, "run_config": data["run_config"],
            "required_semantic_units": 9, "requests": requests, "semantic_acceptance": None}


def read_live_configuration(env_file):
    """只在显式live路径读取选定本地字段；不打印密钥，不改环境。"""
    names = {"DASHSCOPE_API_KEY", "MEMORY_EMBEDDING_API_KEY", "QWEN_MODEL",
             "DASHSCOPE_BASE_URL", "MEMORY_EMBEDDING_BASE_URL"}
    values = {}
    path = Path(env_file)
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            key = key.strip()
            if not separator or key not in names:
                continue
            if key in values:
                raise ValueError("本地配置包含重复字段")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            values[key] = value
    origins = {key: "local_file" for key in values}
    for key in names:
        if key in os.environ:
            values[key], origins[key] = os.environ[key], "environment"
    if values.get("QWEN_MODEL", MODEL) != MODEL or values.get("DASHSCOPE_BASE_URL", BASE_URL).rstrip("/") != BASE_URL:
        raise ValueError("本地模型或接口与已确认计划不一致")
    key_name = "DASHSCOPE_API_KEY" if values.get("DASHSCOPE_API_KEY") else "MEMORY_EMBEDDING_API_KEY"
    if not values.get(key_name):
        raise ValueError("没有可用的本地调用密钥")
    if key_name == "MEMORY_EMBEDDING_API_KEY" and values.get("MEMORY_EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/api/v1").rstrip("/") != "https://dashscope.aliyuncs.com/api/v1":
        raise ValueError("本地凭据关联地域与北京计划不一致")
    return values[key_name], {"credential_setting": key_name, "credential_origin": origins[key_name],
                              "model": MODEL, "base_url": BASE_URL, "permission_verified_before_run": False}


def redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "<redacted>") if secret else value
    if isinstance(value, dict):
        return {redact(key, secret): redact(item, secret) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item, secret) for item in value]
    return value


def save_json(path, value, secret):
    Path(path).write_text(json.dumps(redact(value, secret), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class RecordedExtractor(MemoryExtractor):
    """仅观察既有发送路径；发送前记尝试，返回后捕获原响应，不新增网络层。"""

    def __init__(self, *, evidence_dir, **kwargs):
        super().__init__(**kwargs)
        if (self.model != MODEL or self.endpoint != BASE_URL + "/chat/completions"
                or self.max_requests != MAX_REQUESTS or self.max_completion_tokens != OUTPUT_TOKENS or self.timeout != 30):
            raise ValueError("运行实例与已授权模型/接口/次数不一致")
        self.evidence_dir = Path(evidence_dir)
        self.current_case = None
        self.events = []

    async def _send(self, request):
        if self.request_count >= MAX_REQUESTS or len(self.events) >= MAX_REQUESTS:
            raise RuntimeError("已达到本次授权的六次发送上限")
        event = {"attempt": len(self.events) + 1, "case_id": self.current_case, "started_at": now()}
        with (self.evidence_dir / "attempts.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.events.append(event)
        try:
            response = await super()._send(request)
            event["raw_response"] = deepcopy(response)
            return response
        except BaseException as error:
            event["error_type"] = type(error).__name__
            raise
        finally:
            event["finished_at"] = now()
            if self.request_records:
                event["request_record"] = deepcopy(self.request_records[-1])
            save_json(self.evidence_dir / f"request-{event['attempt']:02d}.json", event, self._api_key)


def usage_summary(records):
    fields = ("prompt_tokens", "completion_tokens", "total_tokens")
    known = {field: [] for field in fields}
    for record in records:
        usage = record.get("usage")
        for field in fields:
            value = usage.get(field) if isinstance(usage, dict) else None
            known[field].append(value if type(value) is int and value >= 0 else None)
    totals = {field: sum(values) if values and all(item is not None for item in values) else None
              for field, values in known.items()}
    complete = bool(records) and all(value is not None for value in totals.values())
    estimate = (totals["prompt_tokens"] * 0.8 + totals["completion_tokens"] * 2.7) / 1_000_000 if complete else None
    return {**totals, "usage_complete": complete, "estimated_standard_price_cny": estimate,
            "billed_cost_cny": None, "pricing_basis": "北京标准输入0.8/输出2.7元每百万tokens，不扣缓存或优惠；账单未核对"}


async def run_cases(data, extractor, output_dir, *, preparation_seconds=0.0, config_summary=None):
    preparation_started = perf_counter()
    output_dir = Path(output_dir)
    if output_dir != extractor.evidence_dir or extractor.request_count or extractor.events:
        raise ValueError("评测需要全新且对应同一证据目录的专用实例")
    output_dir.mkdir(parents=True, exist_ok=False)
    save_json(output_dir / "dataset-snapshot.json", data, extractor._api_key)
    save_json(output_dir / "request-preview.json", preview_plan(data), extractor._api_key)
    report = {"mode": "live", "started_at": now(), "fixture_version": data["version"],
              "authorization": "用户2026-10-23确认按固定计划最多六次真实调用",
              "limits": data["run_config"], "config": config_summary, "cases": [],
              "semantic_acceptance": None, "semantic_review": "pending_review",
              "memory_database_writes": 0,
              "preparation_seconds": preparation_seconds + perf_counter() - preparation_started,
              "timing_note": "请求耗时和提取加归组端到端分别记录；解析不单独计时，语义评阅另行进行"}
    scope = MemoryScope(**data["scope"])
    started = perf_counter()
    save_json(output_dir / "result.json", report, extractor._api_key)
    for case in data["cases"]:
        source = MemorySource(scope=scope, **case["source"])
        extractor.current_case = case["case_id"]
        row = {"case_id": case["case_id"], "source": asdict(source), "status": "started", "semantic_review": None}
        case_started = perf_counter()
        try:
            candidates = await extractor.extract(scope, source)
            groups = route_candidates(scope, candidates)
            if not all(candidate.source is source for candidate in candidates):
                raise ValueError("候选没有关联原Source对象")
            row.update(status="parsed", candidates=[asdict(candidate) for candidate in candidates],
                       groups={route: [i for i, item in enumerate(candidates) if item in members]
                               for route, members in groups.items()})
        except asyncio.CancelledError:
            row.update(status="cancelled", error_type="CancelledError")
            raise
        except Exception as error:
            match = re.search(r"HTTP (\d{3})", str(error))
            row.update(status="technical_error", error_type=type(error).__name__,
                       http_status=int(match.group(1)) if match else None)
        finally:
            row["extraction_and_routing_seconds"] = perf_counter() - case_started
            report["cases"].append(row)
            report.update(model_requests=extractor.request_count,
                          requests=deepcopy(extractor.request_records),
                          usage=usage_summary(extractor.request_records),
                          execution_seconds=perf_counter() - started)
            report["technical_pass_count"] = sum(item["status"] == "parsed" for item in report["cases"])
            report["live_model_response_verified"] = report["technical_pass_count"] > 0
            report["not_executed"] = [item["case_id"] for item in data["cases"][len(report["cases"]):]]
            if row["status"] == "cancelled":
                report["status"] = "cancelled"
                report["finished_at"] = now()
            elif row["status"] == "technical_error":
                report["status"] = "technical_stopped"
            else:
                report["status"] = "technical_complete" if report["technical_pass_count"] == 6 else "in_progress"
            save_json(output_dir / "result.json", report, extractor._api_key)
            print(json.dumps({"case_id": row["case_id"], "status": row["status"],
                              "model_requests": extractor.request_count,
                              "elapsed_seconds": round(row["extraction_and_routing_seconds"], 4)}, ensure_ascii=False), flush=True)
        if row["status"] != "parsed":
            report["status"] = "technical_stopped"
            break
    report["finished_at"] = now()
    report["execution_seconds"] = perf_counter() - started
    save_json(output_dir / "result.json", report, extractor._api_key)
    return redact(report, extractor._api_key)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    started = perf_counter()
    try:
        data = load_dataset()
        if not args.live:
            print(json.dumps(preview_plan(data), ensure_ascii=False, indent=2))
            return 0
        if args.output_dir is None or args.output_dir.exists():
            raise ValueError("真实执行须指定尚不存在的证据目录，禁止重跑覆盖已有结果")
        key, config = read_live_configuration(args.env_file)
        extractor = RecordedExtractor(api_key=key, model=MODEL, base_url=BASE_URL,
                                      timeout=30.0, max_requests=MAX_REQUESTS,
                                      max_completion_tokens=OUTPUT_TOKENS, evidence_dir=args.output_dir)
        report = asyncio.run(run_cases(data, extractor, args.output_dir,
                                       preparation_seconds=perf_counter() - started, config_summary=config))
        report["total_wall_seconds"] = perf_counter() - started
        save_json(args.output_dir / "result.json", report, key)
        print(json.dumps({key: report.get(key) for key in ("status", "model_requests", "technical_pass_count", "not_executed", "usage", "execution_seconds")}, ensure_ascii=False))
        print("evidence_dir=" + str(args.output_dir.resolve()))
        return 0 if report["status"] == "technical_complete" else 2
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({"status": "stopped", "error_type": type(error).__name__,
                          "note": "未自动重试；如已创建证据目录请读取其中的部分执行记录，不能据此认定零费用。"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
