"""v2.1独立变体请求预览；只有预览入口，不读凭据或发送请求。"""

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_pi.memory.extraction_client import build_extraction_request
from mini_pi.memory.models import MemoryScope, MemorySource


FIXTURE = ROOT / "examples/fixtures/memory_overlap_acceptance_v21.json"
PROPOSAL = {
    "model": "qwen3.8-flash", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "region": "华北2（北京）", "max_requests": 6, "max_completion_tokens": 768,
    "timeout_seconds": 30, "enable_thinking": False, "stream": False, "serial": True,
    "automatic_retries": 0, "extra_judge_api_calls": 0,
}


def main():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    scope = MemoryScope(**data["scope"])
    requests = []
    for case in data["cases"]:
        source = MemorySource(scope=scope, **case["source"])
        payload = build_extraction_request(PROPOSAL["model"], scope, source)
        payload.update(enable_thinking=False, max_completion_tokens=768)
        requests.append({"case_id": case["case_id"], "payload": payload})
    print(json.dumps({
        "mode": "preview_only", "real_model_calls": 0, "new_live_authorization": None,
        "fixture_version": data["version"], "proposed_run_config": PROPOSAL,
        "required_units": sum(len(case["required_units"]) for case in data["cases"]),
        "requests": requests,
        "note": "system含已批准的规则及3个教学例子，user仅各案原Source；本地gold不发送。6次为待确认提案，不继承旧额度。",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
