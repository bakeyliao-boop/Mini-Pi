"""D20：集中运行工具样例、复核可选历史 smoke 记录，并验证判定对照；不请求真实模型。"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from evals.logs import save_json
from evals.pi_edit_replace import (
    run_edit_missing_file, run_edit_missing_text, run_edit_multiple_matches, run_edit_replace,
)
from evals.pi_smoke import judge_smoke, load_case, run_offline_smoke


def recheck_smoke(path):
    """根据保存的实际观测重新判定，不沿用旧 passed 标签或补造缺失用量。"""
    result = {"case_id": load_case()["id"], "execution": "historical_smoke_recheck",
              "source_result": str(Path(path).resolve()) if path is not None else None,
              "new_real_model_requests": 0}
    try:
        if path is None:
            raise ValueError("未提供历史真实 smoke 记录；本入口不会自动调用真实模型")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data["case_id"] != result["case_id"] or data["mode"] != "live_bailian":
            raise ValueError("记录不是本例的历史百炼真实调用")
        judgement = judge_smoke(data["output"], data["errors"], data["expected_identity"],
                                data.get("observed_identity"), data.get("usage"))
        result.update(source_run_id=data["run_id"], source_run_status=data["run_status"],
                      source_recorded_verdict=data.get("case_verdict"), source_usage=data.get("usage"),
                      output=data["output"], **judgement)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        result.update(case_verdict="unverified", checks={}, reason=str(error))
    return result


async def run_checks(directory, smoke_evidence=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    report = {"schema": "mini-pi-d20-checks/v1", "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "run_status": "running", "native_pi_evaluation": False,
              "new_real_model_requests": 0, "cases": [recheck_smoke(smoke_evidence)], "controls": []}
    save_json(directory / "protocol.json", {
        "source_commit": "7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333",
        "mode": "current_tool_runs_and_historical_smoke_recheck",
        "new_real_model_requests": 0, "smoke_evidence": report["cases"][0]["source_result"],
        "controls": {"Paris_scripted": "unverified", "London_scripted": "failed", "provider_exception": "failed"},
        "note": "历史真实观测复核与本次工具执行分开；每个工具样例只调用一次，每次使用新工作目录。",
    })
    try:
        for name, runner in (("edit-replace", run_edit_replace), ("edit-missing-text", run_edit_missing_text),
                             ("edit-missing-file", run_edit_missing_file), ("edit-multiple-matches", run_edit_multiple_matches)):
            output = directory / name
            result = await runner(output)
            report["cases"].append({"case_id": result["case_id"], "execution": "current_tool_run",
                                    "run_status": result["run_status"], "tool_outcome": result["tool_outcome"],
                                    "case_verdict": result["case_verdict"], "result_path": str((output / "result.json").resolve())})
            if result["run_status"] == "cancelled":
                raise asyncio.CancelledError
        for name, answer, error, expected in (("Paris_scripted", "Paris", None, "unverified"),
                                              ("London_scripted", "London", None, "failed"),
                                              ("provider_exception", "", "D20 injected provider error", "failed")):
            output = directory / name
            result = await run_offline_smoke(output, answer=answer, simulated_error=error)
            report["controls"].append({"name": name, "run_status": result["run_status"],
                                       "expected_verdict": expected, "actual_verdict": result["case_verdict"],
                                       "as_expected": result["case_verdict"] == expected,
                                       "result_path": str((output / "result.json").resolve())})
            if result["run_status"] == "cancelled":
                raise asyncio.CancelledError
        report["run_status"] = "finished"
    except asyncio.CancelledError:
        report["run_status"] = "cancelled"  # 单例执行器先完成既有收尾，取消后不启动下一例。
    except Exception as error:
        report.update(run_status="exception", error={"type": type(error).__name__, "message": str(error)})
    statuses = [item["case_verdict"] for item in report["cases"]]
    report["counts"] = {status: statuses.count(status) for status in ("passed", "failed", "unverified")}
    report["controls_as_expected"] = len(report["controls"]) == 3 and all(item["as_expected"] for item in report["controls"])
    report["all_selected_cases_passed"] = len(statuses) == 5 and all(status == "passed" for status in statuses)
    report["suite_verdict"] = (
        "failed" if report["run_status"] != "finished" or "failed" in statuses or not report["controls_as_expected"]
        else "passed" if report["all_selected_cases_passed"] else "unverified"
    )
    save_json(directory / "result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-evidence", type=Path, help="已有真实 smoke 的 result.json；缺失时保留未验证，不自动调用模型")
    options = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = Path(__file__).resolve().parents[1] / "local-learning/evidence/d20-checks" / (stamp + "-" + uuid4().hex[:10])
    report = asyncio.run(run_checks(directory, options.smoke_evidence))
    print(json.dumps({"run_status": report["run_status"], "suite_verdict": report["suite_verdict"],
                      "counts": report["counts"], "controls_as_expected": report["controls_as_expected"],
                      "new_real_model_requests": 0, "result_path": str(directory / "result.json")}, ensure_ascii=False, indent=2))
    return {"passed": 0, "failed": 1, "unverified": 2}[report["suite_verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
