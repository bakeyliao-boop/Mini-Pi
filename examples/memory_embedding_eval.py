"""MEM-03 小型语义评测辅助脚本；默认只展示六案计划。

只有显式 --live 才读取工作区 .env 并发送请求，最多十二次，不自动重试。
前三案只用校准分数锁定一个阈值；校准失败立即停止，不调用 heldout。
后三案使用冻结阈值实际查询。gold 仅用于本地评分，不进入模型输入。
"""

import argparse
import asyncio
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mini_pi.memory.dashscope_embedding import DashScopeEmbedder
from mini_pi.memory.errors import MemoryEmbeddingError
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.store import MemoryStore


MANIFEST_PATH = Path(__file__).resolve().parent / "fixtures" / "memory_embedding_eval_v1.json"
VERSION = "mem03-semantic-v1"
MAX_HTTP_REQUESTS = 12
TOP_K = 2
AT = "2026-10-22T10:00:00+08:00"
_ID = re.compile(r"[A-Za-z0-9_-]+")
_REQUEST_FIELDS = (
    "model", "dimensions", "text_type", "text_count", "request_id",
    "total_tokens", "status", "elapsed_seconds",
)


def _checked_manifest(manifest: dict) -> dict:
    """只接受本轮六案格式，并取快照，避免 await 期间外部修改输入。"""
    if not isinstance(manifest, dict) or manifest.get("version") != VERSION:
        raise ValueError("评测数据版本必须为 mem03-semantic-v1")
    if type(manifest.get("top_k")) is not int or manifest["top_k"] != TOP_K:
        raise ValueError("本轮评测固定 top_k=2")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 6:
        raise ValueError("本轮评测必须包含六案")
    seen = set()
    splits = {"calibration": 0, "heldout": 0}
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("评测案例必须为对象")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not _ID.fullmatch(case_id) or case_id in seen:
            raise ValueError("案例 ID 必须合法且唯一")
        seen.add(case_id)
        split = case.get("split")
        if split not in splits:
            raise ValueError("案例分组只能为 calibration 或 heldout")
        splits[split] += 1
        query = case.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("案例问题必须为非空文本")
        memories = case.get("memories")
        if not isinstance(memories, list) or not 1 <= len(memories) <= 3:
            raise ValueError("每案必须包含一至三条候选记忆")
        memory_ids = set()
        for memory in memories:
            if not isinstance(memory, dict):
                raise ValueError("候选记忆必须为对象")
            memory_id = memory.get("id")
            if (
                not isinstance(memory_id, str) or not _ID.fullmatch(memory_id)
                or memory_id in memory_ids
            ):
                raise ValueError("同一案例中的候选 ID 必须合法且唯一")
            memory_ids.add(memory_id)
            text = memory.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("候选原文必须为非空文本")
        expected = case.get("expected_ids")
        if (
            not isinstance(expected, list)
            or any(not isinstance(value, str) for value in expected)
            or len(set(expected)) != len(expected)
            or not set(expected) <= memory_ids
        ):
            raise ValueError("gold 必须为不重复的候选 ID 子集")
    if splits != {"calibration": 3, "heldout": 3}:
        raise ValueError("calibration 和 heldout 必须各有三案")
    return deepcopy(manifest)


def load_manifest(path: str | Path | None = None) -> dict:
    """只读取评测 fixture；不读取凭据。"""
    try:
        manifest = json.loads(Path(path or MANIFEST_PATH).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("无法读取有效的评测数据 JSON") from None
    return _checked_manifest(manifest)


def preview_plan(manifest: dict | None = None) -> dict:
    checked = load_manifest() if manifest is None else _checked_manifest(manifest)
    return {
        "mode": "preview", "dataset_version": checked["version"],
        "model": "text-embedding-v4", "dimensions": 1024, "top_k": TOP_K,
        "max_http_requests": MAX_HTTP_REQUESTS,
        "calibration_max_http_requests": 6, "heldout_max_http_requests": 6,
        "calibration_failure_stops_heldout": True,
        "threshold_selection": "calibration_only_widest_feasible_interval_midpoint",
        "cases": checked["cases"], "semantic_acceptance": False,
        "pilot_only": True, "cost_cny": None,
        "note": "gold仅用于本地评分；三案校准通过后冻结阈值，再运行三案heldout。",
    }


class _EvalEmbedder(DashScopeEmbedder):
    """本 CLI 专用发送上限；独立计数，不依赖已完成的 request_records。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._send_attempts = 0

    async def _send_batch(self, payload: dict, count: int, text_type: str):
        if self._send_attempts >= MAX_HTTP_REQUESTS:
            raise MemoryEmbeddingError("评测已达到十二次发送上限，停止请求")
        self._send_attempts += 1
        return await super()._send_batch(payload, count, text_type)


async def collect_case(
    embedder: DashScopeEmbedder, case: dict, *, threshold: float, top_k: int,
    timings: dict | None = None,
) -> dict:
    """真实临时 SQLite / search；gold 不参与入库、query 或 embedding 输入。"""
    timings = {} if timings is None else timings
    timings.update(preparation_seconds=0.0, search_seconds=0.0)
    started = perf_counter()
    with TemporaryDirectory(prefix="mini_pi_embedding_eval_") as directory:
        preparation_started = perf_counter()
        try:
            scope = MemoryScope("synthetic_eval_user", "synthetic_eval_" + case["id"])
            store = MemoryStore(Path(directory) / "memory.sqlite3")
            for memory in case["memories"]:
                source = MemorySource(
                    "synthetic-" + case["id"] + "-" + memory["id"],
                    scope, "user", memory["text"], AT,
                )
                store.remember(
                    scope, source, MemoryDraft(memory["id"], 0, len(source.text), AT),
                )
        finally:
            timings["preparation_seconds"] = perf_counter() - preparation_started
        search_started = perf_counter()
        try:
            hits = await store.search(
                scope, case["query"], at=AT, embedder=embedder,
                top_k=top_k, min_score=threshold,
            )
        finally:
            timings["search_seconds"] = perf_counter() - search_started
        evidence = [{
            "id": hit.entry.draft.key, "text": hit.entry.text, "score": hit.score,
            "source_id": hit.entry.source.source_id, "version": hit.entry.version,
        } for hit in hits]
        if threshold == -1.0 and top_k == len(case["memories"]):
            if {hit["id"] for hit in evidence} != {memory["id"] for memory in case["memories"]}:
                raise MemoryEmbeddingError("校准采集未完整返回合法候选，不能当作语义空结果")
    return {
        "id": case["id"], "split": case["split"], "hits": evidence,
        "preparation_seconds": timings["preparation_seconds"],
        "search_seconds": timings["search_seconds"],
        "elapsed_seconds": perf_counter() - started,
    }


def _select(hits: list[dict], threshold: float, top_k: int) -> list[dict]:
    # hits 已由实际 search 稳定降序返回；这里只复演既有阈值和限量。
    return [hit for hit in hits if hit["score"] >= threshold][:top_k]


def choose_threshold(calibration_results: list[dict], manifest: dict) -> float | None:
    """只使用 calibration 的分数与 gold，固定 top_k=2，不读取 heldout 分数。"""
    checked = _checked_manifest(manifest)
    gold = {
        case["id"]: set(case["expected_ids"])
        for case in checked["cases"] if case["split"] == "calibration"
    }
    if (
        len(calibration_results) != 3
        or {result["id"] for result in calibration_results} != set(gold)
    ):
        raise ValueError("阈值选择必须且只能使用三案 calibration 结果")
    boundaries = {-1.0, 1.0}
    for result in calibration_results:
        for hit in result["hits"]:
            score = hit["score"]
            if (
                isinstance(score, bool) or not isinstance(score, (int, float))
                or not math.isfinite(score) or not -1.0 <= score <= 1.0
            ):
                raise ValueError("校准分数必须为范围内的有限数值")
            boundaries.add(float(score))
    ordered = sorted(boundaries)
    candidates = [(0.0, -1.0), (0.0, 1.0)]
    candidates.extend(
        (right - left, (left + right) / 2)
        for left, right in zip(ordered, ordered[1:])
    )
    # 最大宽度优先；宽度相同则阈值较高者优先。边界点宽度为零。
    for _, threshold in sorted(candidates, reverse=True):
        if all(
            {hit["id"] for hit in _select(result["hits"], threshold, TOP_K)} == gold[result["id"]]
            for result in calibration_results
        ):
            return threshold
    return None


def _case_result(raw: dict, expected_ids: list[str], selected: list[dict] | None) -> dict:
    result = dict(raw)
    result["expected_ids"] = list(expected_ids)
    result["selection_evaluated"] = selected is not None
    result["selected_hits"] = selected
    result["actual_ids"] = None if selected is None else [hit["id"] for hit in selected]
    result["missing_ids"] = None if selected is None else sorted(set(expected_ids) - set(result["actual_ids"]))
    result["extra_ids"] = None if selected is None else sorted(set(result["actual_ids"]) - set(expected_ids))
    result["passed"] = selected is not None and not result["missing_ids"] and not result["extra_ids"]
    return result


def _request_snapshot(embedder) -> list[dict]:
    records = getattr(embedder, "request_records", ())
    return [{name: record.get(name) for name in _REQUEST_FIELDS} for record in records]


def _empty_report() -> dict:
    return {
        "status": "technical_error", "dataset_version": VERSION,
        "model": "text-embedding-v4", "dimensions": 1024, "top_k": TOP_K,
        "threshold": None, "calibration": [], "heldout": [], "requests": [],
        "semantic_acceptance": False, "pilot_only": True, "cost_cny": None,
        "preparation_seconds": 0.0, "search_seconds": 0.0, "elapsed_seconds": 0.0,
    }


def _technical_error(report: dict, error: BaseException):
    report["status"] = "technical_error"
    report["semantic_acceptance"] = False
    report["error_type"] = type(error).__name__
    match = re.search(r"HTTP (\d{3})", str(error))
    report["http_status"] = int(match.group(1)) if match else None


async def run_eval(embedder: DashScopeEmbedder, manifest: dict) -> dict:
    """校准失败停 heldout；heldout 失败继续收集；技术错误停；取消原样传播。"""
    report = _empty_report()
    started = perf_counter()

    async def collect(case, threshold, top_k):
        timings = {}
        try:
            return await collect_case(
                embedder, case, threshold=threshold, top_k=top_k, timings=timings,
            )
        finally:
            report["preparation_seconds"] += timings.get("preparation_seconds", 0.0)
            report["search_seconds"] += timings.get("search_seconds", 0.0)

    try:
        checked = _checked_manifest(manifest)
        if embedder.spec.model_id != "text-embedding-v4" or embedder.spec.dimensions != 1024:
            raise MemoryEmbeddingError("本轮评测固定 text-embedding-v4 / 1024维")
        if embedder.request_records:
            raise MemoryEmbeddingError("评测需要未发送过请求的适配器")
        calibration = [case for case in checked["cases"] if case["split"] == "calibration"]
        heldout = [case for case in checked["cases"] if case["split"] == "heldout"]
        for case in calibration:
            raw = await collect(case, -1.0, len(case["memories"]))
            report["calibration"].append(_case_result(raw, case["expected_ids"], None))
        threshold = choose_threshold(report["calibration"], checked)
        if threshold is None:
            report["status"] = "calibration_failed"
            return report
        report["threshold"] = threshold  # heldout 开始前冻结；后续不再修改。
        report["calibration"] = [
            _case_result(raw, case["expected_ids"], _select(raw["hits"], threshold, TOP_K))
            for raw, case in zip(report["calibration"], calibration, strict=True)
        ]
        for case in heldout:
            raw = await collect(case, threshold, TOP_K)
            report["heldout"].append(_case_result(raw, case["expected_ids"], raw["hits"]))
        accepted = all(case["passed"] for case in report["calibration"] + report["heldout"])
        report["status"] = "passed" if accepted else "heldout_failed"
        report["semantic_acceptance"] = accepted
    except asyncio.CancelledError:
        raise
    except Exception as error:
        _technical_error(report, error)
    finally:
        report["requests"] = _request_snapshot(embedder)
        report["elapsed_seconds"] = perf_counter() - started
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="明确执行最多十二次真实API请求")
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--output", type=Path, help="真实执行结果JSON路径")
    args = parser.parse_args(argv)
    embedder = None
    try:
        manifest = load_manifest()
        if not args.live:
            print(json.dumps(preview_plan(manifest), ensure_ascii=False, indent=2))
            return 0
        embedder = _EvalEmbedder.from_env(env_file=args.env_file)
        report = asyncio.run(run_eval(embedder, manifest))
    except (Exception, KeyboardInterrupt) as error:
        report = _empty_report()
        _technical_error(report, error)
        report["requests"] = _request_snapshot(embedder) if embedder else []
    if not args.live:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    output = args.output or (
        REPO_ROOT / "local-learning/evidence" / ("mem03-embedding-eval-" + uuid4().hex[:8]) / "result.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "result_file": str(output)}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
