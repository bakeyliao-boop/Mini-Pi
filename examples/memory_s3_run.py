"""执行本轮已确认的S3三次计划；默认不执行，不修改提取核心或语义评分。"""

import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from time import perf_counter

from examples.memory_extraction_eval import now, read_live_configuration, redact, save_json, usage_summary
from examples.memory_s3_preview import FIXTURE, ROOT
from mini_pi.memory.extraction_client import MemoryExtractor, build_extraction_request
from mini_pi.memory.models import MemoryScope, MemorySource
from mini_pi.memory.selection import route_candidates


OUTPUT = ROOT / "local-learning/evidence/memw-s3-v2-live-20261026-01"
PREVIEW = ROOT / "local-learning/evidence/memw-s3-v2-prepare/request-preview.json"
EXPECTED = {
    "model": "qwen3.8-flash", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "region": "华北2（北京）", "max_requests": 3, "max_completion_tokens": 768,
    "timeout_seconds": 30, "enable_thinking": False, "stream": False, "serial": True,
    "automatic_retries": 0, "extra_judge_api_calls": 0,
}
AUTHORIZATION = "用户本轮明确确认：按S3方案最多3次真实调用，无重试/额外评审，不写长期记忆"


def prepared_plan():
    """只读样本与准备请求，冻结当前提示和参数，不读取凭据。"""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    preview = json.loads(PREVIEW.read_text(encoding="utf-8"))
    if data["proposed_run_config"] != EXPECTED or preview["proposed_run_config"] != EXPECTED:
        raise ValueError("S3配置已偏离本轮确认计划")
    if [case["case_id"] for case in data["cases"]] != ["A", "B", "C"] or len(preview["requests"]) != 3:
        raise ValueError("只允许已确认的A/B/C三案")
    if sum(len(case["required_units"]) for case in data["cases"]) != 5:
        raise ValueError("必需单元数已变化")
    scope = MemoryScope(**data["scope"])
    for case, item in zip(data["cases"], preview["requests"]):
        source = MemorySource(scope=scope, **case["source"])
        payload = build_extraction_request(EXPECTED["model"], scope, source)
        payload.update(enable_thinking=False, max_completion_tokens=768)
        if item["case_id"] != case["case_id"] or payload != item["payload"]:
            raise ValueError("当前提示或来源与准备请求不同，停止执行")
    return data, preview


class S3Recorder(MemoryExtractor):
    """仅记录已验父发送层，三次封顶；不添加重试或语义裁判。"""

    def __init__(self, *, api_key, evidence_dir):
        super().__init__(api_key=api_key, model=EXPECTED["model"], base_url=EXPECTED["base_url"],
                         timeout=30.0, max_requests=3, max_completion_tokens=768)
        self.evidence_dir = Path(evidence_dir)
        self.current_case = None
        self.events = []

    async def _send(self, request):
        if len(self.events) >= 3 or self.request_count >= 3:
            raise RuntimeError("本次S3三次额度已用完")
        event = {"attempt": len(self.events) + 1, "case_id": self.current_case, "started_at": now()}
        self.events.append(event)
        with (self.evidence_dir / "attempts.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
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


async def run_plan(data, preview, extractor, *, config_summary):
    folder = extractor.evidence_dir
    if folder.exists() or extractor.request_count or extractor.events:
        raise ValueError("只允许全新证据目录和专用实例")
    folder.mkdir(parents=True, exist_ok=False)
    save_json(folder / "dataset-snapshot.json", data, extractor._api_key)
    save_json(folder / "request-preview.json", preview, extractor._api_key)
    report = {
        "status": "in_progress", "started_at": now(), "authorization": AUTHORIZATION,
        "fixture_version": data["version"], "limits": EXPECTED, "config": config_summary,
        "cases": [], "semantic_acceptance": None, "semantic_review": "pending_manual_review",
        "memory_database_writes": 0, "model_requests": 0,
    }
    scope = MemoryScope(**data["scope"])
    started = perf_counter()
    save_json(folder / "result.json", report, extractor._api_key)
    for case in data["cases"]:
        source = MemorySource(scope=scope, **case["source"])
        extractor.current_case = case["case_id"]
        row = {"case_id": case["case_id"], "source": asdict(source), "status": "started"}
        case_started = perf_counter()
        try:
            candidates = await extractor.extract(scope, source)
            groups = route_candidates(scope, candidates)
            if not all(candidate.source is source for candidate in candidates):
                raise ValueError("候选来源关联错误")
            row.update(status="parsed", candidates=[asdict(item) for item in candidates],
                       groups={route: [i for i, item in enumerate(candidates) if item in items]
                               for route, items in groups.items()})
        except asyncio.CancelledError:
            row.update(status="cancelled", error_type="CancelledError")
            raise
        except Exception as error:
            row.update(status="technical_error", error_type=type(error).__name__)
        finally:
            row["extraction_and_routing_seconds"] = perf_counter() - case_started
            report["cases"].append(row)
            report.update(model_requests=extractor.request_count, requests=deepcopy(extractor.request_records),
                          usage=usage_summary(extractor.request_records), execution_seconds=perf_counter() - started,
                          not_executed=[c["case_id"] for c in data["cases"][len(report["cases"]):]])
            passed = sum(item["status"] == "parsed" for item in report["cases"])
            report["technical_pass_count"] = passed
            report["status"] = ("technical_complete" if passed == 3 else "in_progress") if row["status"] == "parsed" else "technical_stopped"
            save_json(folder / "result.json", report, extractor._api_key)
            print(json.dumps({"case_id": row["case_id"], "status": row["status"],
                              "requests": extractor.request_count}, ensure_ascii=False), flush=True)
        if row["status"] != "parsed":
            break
    report.update(finished_at=now(), execution_seconds=perf_counter() - started)
    save_json(folder / "result.json", report, extractor._api_key)
    return redact(report, extractor._api_key)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-authorized-plan", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute_authorized_plan:
        print(json.dumps({"status": "not_executed", "real_model_calls": 0}))
        return 0
    started = perf_counter()
    try:
        data, preview = prepared_plan()
        if OUTPUT.exists():
            raise ValueError("证据目录已存在，不得重跑或覆盖")
        key, config = read_live_configuration(ROOT / ".env")
        extractor = S3Recorder(api_key=key, evidence_dir=OUTPUT)
        report = asyncio.run(run_plan(data, preview, extractor, config_summary=config))
        report["process_wall_seconds"] = perf_counter() - started
        save_json(OUTPUT / "result.json", report, key)
        print(json.dumps({"status": report["status"], "model_requests": report["model_requests"],
                          "technical_pass_count": report["technical_pass_count"], "usage": report["usage"]}, ensure_ascii=False))
        return 0 if report["status"] == "technical_complete" else 2
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({"status": "stopped", "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
