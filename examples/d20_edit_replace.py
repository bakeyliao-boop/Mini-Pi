"""D20：执行 Pi 来源的固定文件编辑用例，不调用 LLM。"""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from evals.pi_edit_replace import run_edit_replace


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = Path(__file__).resolve().parents[1] / "local-learning" / "evidence" / "d20-edit-replace"
    directory = root / (stamp + "-" + uuid4().hex[:10])
    result = asyncio.run(run_edit_replace(directory))
    print(json.dumps({"mode": result["mode"], "run_status": result["run_status"],
                      "case_verdict": result["case_verdict"], "before": result["before"],
                      "after": result["after"], "reconstructed_from_patch": result["reconstructed_from_patch"],
                      "model_requests": 0, "errors": result["errors"], "log_directory": str(directory)},
                     ensure_ascii=False, indent=2))
    return {"passed": 0, "failed": 1, "unverified": 2}[result["case_verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
