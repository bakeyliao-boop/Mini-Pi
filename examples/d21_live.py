"""D21真实试跑。默认准备协议，--execute-live 执行已准备的协议。"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from evals.d21_live import prepare_pilot, run_live_pilot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-file", type=Path, help="准备阶段使用已有Pi百炼auth.json，只读")
    parser.add_argument("--prepared-dir", type=Path, help="已准备的协议目录")
    parser.add_argument("--task", choices=("edit-history", "config-tail"), help="准备阶段的任务，默认为第一任务")
    parser.add_argument("--execute-live", action="store_true", help="显式执行真实付费请求，须先取得本轮授权")
    args = parser.parse_args()
    if args.execute_live:
        if args.prepared_dir is None or args.auth_file is not None or args.task is not None:
            parser.error("真实执行必须指定prepared-dir，任务和凭证来源沿用已准备协议")
        result = asyncio.run(run_live_pilot(args.prepared_dir))
        print(json.dumps({"real_model_requests": result["real_model_requests"], "cohort_complete": result["cohort_complete"],
                          "telemetry_complete": result["telemetry_complete"], "all_tasks_passed": result["all_tasks_passed"],
                          "result_path": str(args.prepared_dir / "result.json")}, ensure_ascii=False, indent=2))
        return 0 if result["pilot_observations_complete"] else 2
    if args.auth_file is None or args.prepared_dir is not None:
        parser.error("准备阶段需要auth-file；将生成新的协议目录，不发送请求")
    directory = Path(__file__).resolve().parents[1] / "local-learning/evidence/d21-live" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    result = prepare_pilot(directory, args.auth_file, task=args.task or "edit-history")
    print(json.dumps({"state": "prepared", "real_model_requests": 0, "plan": result["plan"],
                      "protocol_path": result["protocol_path"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
