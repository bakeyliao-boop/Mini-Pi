"""准备D21第二任务的实际输入及本地文件验收；没有真实API入口。"""

import asyncio
from datetime import datetime, timezone
import json
from uuid import uuid4

from evals.d21_preview import ROOT
from evals.d21_task2 import run_task2


def main():
    directory = ROOT / "local-learning/evidence/d21-task2" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    result = asyncio.run(run_task2(directory))
    print(json.dumps({"preparation_checks_passed": result["preparation_checks_passed"],
                      "groups": {name: {"file_verdict": item["case_verdict"], "run_status": item["run_status"]}
                                 for name, item in result["groups"].items()},
                      "real_model_requests": 0, "review": str(directory / "review.md")}, ensure_ascii=False, indent=2))
    return 0 if result["preparation_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
