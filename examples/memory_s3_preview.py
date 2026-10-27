"""S3三案的发送前请求预览：没有live路径，不读凭据、发请求、开库或写Session。"""

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_pi.memory.extraction_client import build_extraction_request
from mini_pi.memory.models import MemoryScope, MemorySource


FIXTURE = ROOT / "examples/fixtures/memory_s3_acceptance_v2.json"


def main():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    config = data["proposed_run_config"]
    scope = MemoryScope(**data["scope"])  # 范围由可信教学脚本提供，不让模型自报身份。
    requests = []
    for case in data["cases"]:
        source = MemorySource(scope=scope, **case["source"])
        payload = build_extraction_request(config["model"], scope, source)  # 复用现有组装核心，只提供原消息。
        payload["enable_thinking"] = config["enable_thinking"]  # 预览实际发送层会附加的参数。
        payload["max_completion_tokens"] = config["max_completion_tokens"]
        requests.append({"case_id": case["case_id"], "payload": payload})
    print(json.dumps({
        "mode": "preview_only", "real_model_calls": 0, "new_live_authorization": None,
        "fixture_version": data["version"], "proposed_run_config": config, "requests": requests,
        "note": "仅预览现有组装器产生的拟定请求；标注不进入messages。此脚本没有发送入口，不代表模型语义已通过。",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
