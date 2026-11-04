"""D20：Pi 文件替换用例的工具级适配、独立验收与日志；不调用 LLM。"""

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from time import perf_counter
from uuid import uuid4

from evals.logs import save_json
from mini_pi.models import ToolCall
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy


def load_case(name="pi_edit_replace"):
    path = Path(__file__).parent / "cases" / (name + ".json")
    return json.loads(path.read_text(encoding="utf-8"))


def rebuild_patch(original, patch_text, directory):
    """在独立副本上应用真实返回的补丁，不根据 old/new 参数拼造结果。"""
    case = load_case()
    expected_headers = [f"--- a/{case['filename']}", f"+++ b/{case['filename']}"]
    headers = [line for line in patch_text.splitlines() if line.startswith(("--- ", "+++ "))]
    if headers != expected_headers:
        return {"status": "failed", "reason": "补丁没有且仅指向本例预期文件", "output": None}
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / case["filename"]
    target.write_bytes(original.encode("utf-8"))
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(key, None)
    env["GIT_CEILING_DIRECTORIES"] = str(directory.parent)  # 独立验证目录不沿用父仓库的路径解释。
    attempts = []
    try:
        for args in (("apply", "--check", "-"), ("apply", "-")):
            completed = subprocess.run(
                ["git", *args], cwd=directory, env=env, input=patch_text.encode("utf-8"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False,
            )
            attempts.append({"command": ["git", *args], "exit_code": completed.returncode,
                             "stdout": completed.stdout.decode("utf-8", errors="replace"),
                             "stderr": completed.stderr.decode("utf-8", errors="replace")})
            if completed.returncode != 0:
                return {"status": "failed", "attempts": attempts, "output": None}
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return {"status": "unverified", "reason": str(error), "attempts": attempts, "output": None}
    return {"status": "passed", "attempts": attempts, "output": target.read_bytes().decode("utf-8")}


def judge_edit_replace(tool_result, actual_content, patch_result):
    """原输入/预期不变；结构字段做显式映射，磁盘内容检查另行标记。"""
    case = load_case()
    output = tool_result.output if tool_result is not None else None
    text = output if isinstance(output, str) else ""
    checks = {}

    def add(name, passed, actual, expected, *, origin="mapped_upstream", status=None):
        checks[name] = {"status": status or ("passed" if passed else "failed"),
                        "actual": actual, "expected": expected, "origin": origin}

    add("operation_success", tool_result is not None and tool_result.error is None,
        tool_result.error if tool_result is not None else "no result", None)
    add("diff_present", output is not None, output is not None, True)
    add("diff_is_string", isinstance(output, str), type(output).__name__, "str")
    for name, expected in (
        ("diff_contains_new_text", case["new_text"]),
        ("patch_has_old_header", "--- "), ("patch_has_new_header", "+++ "),
        ("patch_has_hunk", "@@"),
        ("patch_has_old_line", "-" + case["initial_content"]),
        ("patch_has_new_line", "+" + case["expected_content"]),
    ):
        add(name, expected in text, expected in text, True)
    patch_status = patch_result["status"]
    add("patch_recreates_expected", patch_status == "passed" and patch_result["output"] == case["expected_content"],
        patch_result["output"], case["expected_content"],
        status="unverified" if patch_status == "unverified" else None)
    add("disk_file_contains_expected", actual_content == case["expected_content"],
        actual_content, case["expected_content"], origin="additional_mini_pi")
    statuses = {item["status"] for item in checks.values()}
    verdict = "failed" if "failed" in statuses else "unverified" if "unverified" in statuses else "passed"
    return {"case_verdict": verdict, "checks": checks}


def judge_missing_text(tool_result, actual_content):
    """本题要求正确报错；不能因存在 error 就直接判案例失败。"""
    case = load_case("pi_edit_missing_text")
    reason = tool_result.error if tool_result is not None else None
    output = tool_result.output if tool_result is not None else None
    checks = {
        "tool_reports_error": {"passed": tool_result is not None and reason is not None,
                               "actual": reason, "expected": "tool error", "origin": "mapped_upstream"},
        "error_reason_matches": {"passed": isinstance(reason, str) and case["expected_error"] in reason,
                                 "actual": reason, "expected": case["expected_error"], "origin": "mapped_upstream"},
        "disk_file_unchanged": {"passed": actual_content == case["initial_content"],
                                "actual": actual_content, "expected": case["initial_content"], "origin": "additional_mini_pi"},
        "no_success_patch": {"passed": tool_result is not None and output == "",
                             "actual": output, "expected": "", "origin": "additional_mini_pi"},
    }
    for item in checks.values():
        item["status"] = "passed" if item.pop("passed") else "failed"
    verdict = "passed" if all(item["status"] == "passed" for item in checks.values()) else "failed"
    return {"case_verdict": verdict, "checks": checks}


def judge_missing_file(tool_result, target, target_exists):
    """保留原例的路径及 ENOENT 要求，不能只接受任意文件报错。"""
    case = load_case("pi_edit_missing_file")
    reason = tool_result.error if tool_result is not None else None
    text = reason if isinstance(reason, str) else ""
    expected_path = str(Path(target).resolve())
    checks = {
        "tool_reports_error": (reason is not None, reason, "tool error", "mapped_upstream"),
        "error_reason_matches": (case["expected_error_reason"] in text, reason, case["expected_error_reason"], "mapped_upstream"),
        "error_contains_target_path": (expected_path in text, reason, expected_path, "mapped_upstream"),
        "error_code_matches": (case["expected_error_code"] in text, reason, case["expected_error_code"], "mapped_upstream"),
        "target_remains_absent": (not target_exists, target_exists, False, "additional_mini_pi"),
        "no_success_patch": (tool_result is not None and tool_result.output == "", tool_result.output if tool_result is not None else None, "", "additional_mini_pi"),
    }
    checks = {name: {"status": "passed" if passed else "failed", "actual": actual,
                     "expected": expected, "origin": origin}
              for name, (passed, actual, expected, origin) in checks.items()}
    verdict = "passed" if all(item["status"] == "passed" for item in checks.values()) else "failed"
    return {"case_verdict": verdict, "checks": checks}


def judge_multiple_matches(tool_result, actual_content):
    """次数必须准确；只有多处提示、错误次数或实际误改文件都不能通过。"""
    case = load_case("pi_edit_multiple_matches")
    reason = tool_result.error if tool_result is not None else None
    match = re.search(case["error_count_pattern"], reason) if isinstance(reason, str) else None
    occurrences = int(match.group(1)) if match is not None else None
    checks = {
        "tool_reports_error": (reason is not None, reason, "tool error", "mapped_upstream"),
        "error_reason_matches": (isinstance(reason, str) and case["expected_error_reason"] in reason,
                                 reason, case["expected_error_reason"], "mapped_upstream"),
        "occurrence_count_matches": (occurrences == case["expected_occurrences"], occurrences,
                                      case["expected_occurrences"], "mapped_upstream"),
        "disk_file_unchanged": (actual_content == case["initial_content"], actual_content,
                                case["initial_content"], "additional_mini_pi"),
        "no_success_patch": (tool_result is not None and tool_result.output == "",
                             tool_result.output if tool_result is not None else None, "", "additional_mini_pi"),
    }
    checks = {name: {"status": "passed" if passed else "failed", "actual": actual,
                     "expected": expected, "origin": origin}
              for name, (passed, actual, expected, origin) in checks.items()}
    verdict = "passed" if all(item["status"] == "passed" for item in checks.values()) else "failed"
    return {"case_verdict": verdict, "checks": checks}


async def run_edit_replace(output_dir):
    return await _run_edit_case(output_dir, "pi_edit_replace")


async def run_edit_missing_text(output_dir):
    return await _run_edit_case(output_dir, "pi_edit_missing_text")


async def run_edit_missing_file(output_dir):
    return await _run_edit_case(output_dir, "pi_edit_missing_file")


async def run_edit_multiple_matches(output_dir):
    return await _run_edit_case(output_dir, "pi_edit_multiple_matches")


async def _run_edit_case(output_dir, case_name):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    case = load_case(case_name)
    run_id = "d20-edit-" + uuid4().hex
    protocol = {"schema": "mini-pi-d20-edit/v1", "run_id": run_id,
                "case": case, "mode": "tool_unit_port", "model_requests": 0,
                "started_at_utc": datetime.now(timezone.utc).isoformat()}
    save_json(output_dir / "protocol.json", protocol)
    workspace = output_dir / "workspace"
    workspace.mkdir()
    target = workspace / case["filename"]
    if case["initial_content"] is not None:  # null 表示文件不存在，不能写入空文件代替。
        target.write_bytes(case["initial_content"].encode("utf-8"))
    before_exists = target.exists()
    before = target.read_bytes().decode("utf-8") if before_exists else None
    if before_exists:
        (output_dir / "before.txt").write_bytes(target.read_bytes())
    save_json(output_dir / "initial-state.json", {"target": str(target.resolve()),
                                                 "exists": before_exists, "content": before})
    call = ToolCall(case["tool_call_id"], "edit_file", {
        "path": case["filename"], "old_text": case["old_text"], "new_text": case["new_text"],
    })
    save_json(output_dir / "requests.json", [{"kind": "tool_call", "call": asdict(call)}])
    editor = EditFileExecutor(EditPolicy(workspace, [case["filename"]]))
    result = None
    exception = None
    status = "finished"
    started = perf_counter()
    try:
        result = await editor.execute(call)
    except asyncio.CancelledError:
        status = "cancelled"
        exception = {"type": "CancelledError", "message": "tool case cancelled after cleanup"}
    except Exception as error:
        status = "exception"
        exception = {"type": type(error).__name__, "message": str(error)}
    actual = target.read_bytes().decode("utf-8") if target.exists() else None
    if actual is not None:
        (output_dir / "after.txt").write_bytes(actual.encode("utf-8"))
    save_json(output_dir / "tool_result.json", asdict(result) if result is not None else None)
    if case["expectation"] == "missing_file":
        patch_result = {"status": "not_applicable", "reason": "目标不存在时预期报错，不要求成功补丁", "output": None}
        judgement = judge_missing_file(result, target, target.exists())
    elif case["expectation"] == "multiple_matches":
        patch_result = {"status": "not_applicable", "reason": "多处匹配时预期拒绝编辑，不要求成功补丁", "output": None}
        judgement = judge_multiple_matches(result, actual)
    elif case["expectation"] == "missing_old_text":
        patch_result = {"status": "not_applicable", "reason": "本题预期编辑报错，不要求返回成功补丁", "output": None}
        judgement = judge_missing_text(result, actual)
    else:
        patch_result = rebuild_patch(case["initial_content"], result.output if result is not None else "",
                                     output_dir / "patch-validation")
        judgement = judge_edit_replace(result, actual, patch_result)
    save_json(output_dir / "patch-check.json", patch_result)
    errors = [exception["message"]] if exception is not None else []
    if result is not None and result.error is not None:
        errors.append(result.error)
    report = {"schema": protocol["schema"], "case_id": case["id"], "run_id": run_id,
              "mode": "tool_unit_port", "native_pi_evaluation": False,
              "run_status": status, "exception": exception, "errors": errors,
              "elapsed_seconds": round(perf_counter() - started, 6),
              "model_requests": 0, "tool_calls": 1, "usage": None,
              "tool_outcome": "error" if result is not None and result.error is not None else "success" if result is not None else "exception",
              "expected_tool_outcome": "success" if case["expectation"] == "edit_success" else "error",
              "before_exists": before_exists, "after_exists": target.exists(),
              "before": before, "after": actual,
              "reconstructed_from_patch": patch_result["output"],
              "adaptation": case["adaptation"],
              **judgement}
    save_json(output_dir / "result.json", report)
    return report
