"""助手准备：MEM-03 真实 embedding 连通性样例；默认仅预览。

在仓库根目录运行 python examples/memory_embedding_smoke.py 查看具体计划。
显式加 --live 后才读取指定 .env 并请求阿里；最多两次发送、不自动重试。
仅使用本文件合成文本和临时 SQLite，不读取真实 Session 或现有记忆库。
本样例不校准阈值，不据相似度排序宣称语义效果验收通过。
"""

import argparse
import asyncio
from dataclasses import asdict
import json
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


MAX_HTTP_REQUESTS = 2
QUERY = "我平时用哪种编程语言？"
DOCUMENTS = (
    ("language", "我主要使用 Python 编写脚本。"),
    ("study_time", "我习惯周末晚上学习。"),
)
AT = "2026-10-22T10:00:00+08:00"


def preview_plan() -> dict:
    """只创建合成计划；不读配置、不建库、不联网。"""
    return {
        "mode": "preview", "scenario": "MEM-03 embedding connectivity",
        "model": "text-embedding-v4", "dimensions": 1024,
        "query": QUERY,
        "documents": [{"key": key, "text": text} for key, text in DOCUMENTS],
        "max_http_requests": MAX_HTTP_REQUESTS, "sent_text_count": 3,
        "top_k": 2, "min_score": -1.0,
        "semantic_acceptance": False, "threshold_calibrated": False,
        "cost_cny": None,
        "note": "仅验证临时SQLite→search→embedding接口→证据返回；费用待账单核对。",
    }


class _SmokeEmbedder(DashScopeEmbedder):
    """仅用于此样例的发送次数上限；不改变正式适配器或生命周期语义。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._send_attempts = 0

    async def _send_batch(self, payload: dict, count: int, text_type: str):
        if self._send_attempts >= MAX_HTTP_REQUESTS:
            raise MemoryEmbeddingError("连通性样例已达到两次发送上限，停止请求")
        self._send_attempts += 1
        return await super()._send_batch(payload, count, text_type)


async def run_smoke(embedder: DashScopeEmbedder) -> dict:
    """使用注入的适配器执行实际记忆链路；本函数不读取凭据文件。"""
    if embedder.spec.model_id != "text-embedding-v4" or embedder.spec.dimensions != 1024:
        raise MemoryEmbeddingError("本次连通计划固定 text-embedding-v4 / 1024维")
    if embedder.request_records:
        raise MemoryEmbeddingError("连通样例需要未发送过请求的适配器")
    started = perf_counter()
    with TemporaryDirectory(prefix="mini_pi_embedding_smoke_") as directory:
        preparation_started = perf_counter()
        scope = MemoryScope("synthetic_smoke_user", "synthetic_smoke_project")
        store = MemoryStore(Path(directory) / "memory.sqlite3")
        entries = []
        for key, text in DOCUMENTS:
            source = MemorySource("synthetic-" + key, scope, "user", text, AT)
            entries.append(store.remember(
                scope, source, MemoryDraft(key, 0, len(text), AT),
            ))
        preparation_seconds = perf_counter() - preparation_started
        search_started = perf_counter()
        # -1 保留全部合法候选，只观察实际分数；不是已校准的生产阈值。
        hits = await store.search(
            scope, QUERY, at=AT, embedder=embedder, top_k=2, min_score=-1.0,
        )
        search_seconds = perf_counter() - search_started
        if {hit.entry.memory_id for hit in hits} != {entry.memory_id for entry in entries}:
            raise MemoryEmbeddingError("连通样例未完整返回两条合成证据")
        records = list(embedder.request_records)
        if (
            len(records) != 2
            or [record["text_type"] for record in records] != ["query", "document"]
            or [record["text_count"] for record in records] != [1, 2]
            or any(record["status"] != "validated" for record in records)
        ):
            raise MemoryEmbeddingError("连通样例实际请求轨迹不符合已展示计划")
        report = {
            "status": "passed", "acceptance": "connectivity_and_shape",
            "semantic_acceptance": False, "threshold_calibrated": False,
            "plan": preview_plan(), "model_spec": asdict(embedder.spec),
            "hits": [{
                "key": hit.entry.draft.key, "text": hit.entry.text,
                "score": hit.score, "version": hit.entry.version,
                "source_id": hit.entry.source.source_id,
            } for hit in hits],
            "requests": records, "preparation_seconds": preparation_seconds,
            "search_seconds": search_seconds, "cost_cny": None,
        }
    # 临时库完成清理后才返回；总耗时包括准备、检索和临时文件收尾。
    report["elapsed_seconds"] = perf_counter() - started
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="明确执行真实API请求")
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--output", type=Path, help="真实执行结果JSON路径")
    args = parser.parse_args(argv)
    if not args.live:
        print(json.dumps(preview_plan(), ensure_ascii=False, indent=2))
        return 0
    embedder = None
    try:
        embedder = _SmokeEmbedder.from_env(env_file=args.env_file)
        report = asyncio.run(run_smoke(embedder))
        exit_code = 0
    except (Exception, KeyboardInterrupt) as error:
        # 不输出原始异常body/headers/凭据，只提取可核对的HTTP状态码。
        match = re.search(r"HTTP (\d{3})", str(error))
        report = {
            "status": "failed", "semantic_acceptance": False,
            "plan": preview_plan(), "error_type": type(error).__name__,
            "http_status": int(match.group(1)) if match else None,
            "requests": list(embedder.request_records) if embedder else [],
            "cost_cny": None, "note": "未自动重试；失败或取消不代表零费用。",
        }
        exit_code = 1
    output = args.output or (
        REPO_ROOT / "local-learning/evidence" / ("mem03-embedding-live-" + uuid4().hex[:8])
        / "result.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "result_file": str(output)}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
