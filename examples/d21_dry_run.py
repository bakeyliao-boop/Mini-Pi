"""D21：执行三组完整离线演练及口头成功对照；不请求真实模型。"""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from evals.d21_dry_run import run_dry_run


def main():
    directory = Path(__file__).resolve().parents[1] / "local-learning/evidence/d21-dry-run" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    report = asyncio.run(run_dry_run(directory))
    print(json.dumps({"dry_run_checks_passed": report["dry_run_checks_passed"],
                      "groups": {name: {"run_status": item["run_status"], "case_verdict": item["case_verdict"],
                                        "actual_content": item["actual_content"], "answer_script_calls": item["answer_script_calls"],
                                        "summary_script_calls": item["summary_script_calls"]} for name, item in report["groups"].items()},
                      "claim_only_control": report["claim_only_control"]["case_verdict"] if report["claim_only_control"] else None,
                      "real_model_requests": 0, "review": str(directory / "review.md")}, ensure_ascii=False, indent=2))
    return 0 if report["dry_run_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
