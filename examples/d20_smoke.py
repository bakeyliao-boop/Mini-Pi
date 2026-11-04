"""D20 smoke 日志入口：默认离线；--mode live 显式执行一次百炼调用。"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from evals.pi_smoke import run_live_smoke, run_offline_smoke, verdict_exit_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--answer", help="预设的模拟模型回答，仅用于离线")
    parser.add_argument("--simulated-error", help="模拟调用异常，用于核对失败日志")
    parser.add_argument("--auth-file", type=Path, help="现有 Pi auth.json，仅用于显式真实调用")
    parser.add_argument("--model", default="qwen3.8-flash")
    options = parser.parse_args()
    if options.mode == "live" and (options.answer is not None or options.simulated_error is not None):
        parser.error("真实模式不能使用预设回答或模拟错误")
    if options.mode == "offline" and options.auth_file is not None:
        parser.error("离线模式不读取真实凭证")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(__file__).resolve().parents[1] / "local-learning" / "evidence" / "d20-smoke"
    output_dir = folder / (stamp + "-" + uuid4().hex[:10])
    if options.mode == "live":
        report = asyncio.run(run_live_smoke(output_dir, auth_file=options.auth_file, model=options.model))
    else:
        report = asyncio.run(run_offline_smoke(
            output_dir, answer=options.answer if options.answer is not None else "Paris",
            simulated_error=options.simulated_error, expected_model=options.model,
        ))
    print(json.dumps({"mode": report["mode"], "run_status": report["run_status"],
                      "case_verdict": report["case_verdict"], "output": report["output"],
                      "errors": report["errors"], "usage": report["usage"],
                      "model_requests": report["model_requests"], "log_directory": str(output_dir)},
                     ensure_ascii=False, indent=2))
    return verdict_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
