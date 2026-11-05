"""D21：离线核对三组首个输入；不请求真实模型，不执行文件修改。"""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from evals.d21_preview import run_preview


def main():
    root = Path(__file__).resolve().parents[1] / "local-learning/evidence/d21-preview"
    directory = root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    result = asyncio.run(run_preview(directory))
    print(json.dumps({"preview_checks_passed": result["preview_checks_passed"],
                      "groups": {name: {"request_estimated_tokens": group["answer_input_estimate"]["estimated_input_tokens"],
                                        "read_chars": group["read_result_chars_in_answer"],
                                        "scripted_summary_calls": group["scripted_summary_calls"]} for name, group in result["groups"].items()},
                      "real_model_requests": 0, "task_evaluated": False,
                      "input_review": str(directory / "input-review.md")}, ensure_ascii=False, indent=2))
    return 0 if result["preview_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
