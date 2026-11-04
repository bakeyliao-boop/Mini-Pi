"""D20：Pi 旧文字出现多次样例；拒绝编辑并报告实际次数，不调用 LLM。"""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from evals.pi_edit_replace import run_edit_multiple_matches


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = Path(__file__).resolve().parents[1] / "local-learning/evidence/d20-edit-multiple-matches"
    directory = root / (stamp + "-" + uuid4().hex[:10])
    result = asyncio.run(run_edit_multiple_matches(directory))
    print(json.dumps({"run_status": result["run_status"], "tool_outcome": result["tool_outcome"],
                      "case_verdict": result["case_verdict"], "errors": result["errors"],
                      "failed_checks": [name for name, check in result["checks"].items() if check["status"] == "failed"],
                      "before": result["before"], "after": result["after"],
                      "model_requests": 0, "log_directory": str(directory)}, ensure_ascii=False, indent=2))
    return {"passed": 0, "failed": 1, "unverified": 2}[result["case_verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
