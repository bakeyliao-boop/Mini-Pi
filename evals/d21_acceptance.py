"""D21辅助验收：独立核对真实文件与实际返回的完整编辑补丁链。"""

import os
from pathlib import Path, PurePosixPath
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def snapshot_files(directory):
    directory = Path(directory)
    return {path.relative_to(directory).as_posix(): path.read_bytes()
            for path in directory.rglob("*") if path.is_file()}


def _normalized_target(path):
    if "\\" in path or ":" in path:
        return None
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts:
        return None
    return value.as_posix()


def _patch_strip_level(patch_text, target):
    if not isinstance(patch_text, str):
        return None
    lines = patch_text.splitlines()
    if len(lines) < 2 or not lines[0].startswith("--- a/") or not lines[1].startswith("+++ b/"):
        return None
    paths = [lines[0][6:], lines[1][6:]]
    if any(_normalized_target(path) != target for path in paths):
        return None
    levels = []
    for path in paths:
        dots = 0
        while path.startswith("./"):
            dots += 1
            path = path[2:]
        levels.append(1 + dots)  # Git原生剥离a/或b/，并剥离等价路径的前导./。
    return levels[0] if levels[0] == levels[1] else None


def rebuild_patch_chain(initial_bytes, target_name, edits, verification_dir):
    if not edits:
        return {"status": "failed", "reason": "没有实际成功编辑的工具结果", "attempts": [], "output": None}
    strip_levels = [_patch_strip_level(item.output, target_name) for item in edits]
    if any(level is None for level in strip_levels):
        return {"status": "failed", "reason": "编辑补丁缺失或补丁头未指向目标文件", "attempts": [], "output": None}
    directory = Path(verification_dir).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / target_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(initial_bytes)
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(key, None)
    env["GIT_CEILING_DIRECTORIES"] = str(directory.parent)
    attempts = []
    try:
        for index, (edit, strip_level) in enumerate(zip(edits, strip_levels)):
            # numstat在不写文件时核对实际路径；不把hunk中类似补丁头的正文误判为文件名。
            strip_argument = f"-p{strip_level}"
            for arguments in (("apply", "--numstat", strip_argument, "-"),
                              ("apply", "--check", strip_argument, "-"), ("apply", strip_argument, "-")):
                completed = subprocess.run(
                    ["git", "-c", "core.autocrlf=false", *arguments], cwd=directory, env=env, input=edit.output.encode("utf-8"),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False,
                )
                stdout = completed.stdout.decode("utf-8", errors="replace")
                attempts.append({"edit_index": index, "tool_call_id": edit.tool_call_id,
                                 "command": ["git", "-c", "core.autocrlf=false", *arguments], "exit_code": completed.returncode,
                                 "stdout": stdout, "stderr": completed.stderr.decode("utf-8", errors="replace")})
                if completed.returncode != 0:
                    return {"status": "failed", "reason": "返回的补丁链不能依次应用", "attempts": attempts, "output": None}
                if "--numstat" in arguments:
                    names = [line.split("\t", 2)[2] for line in stdout.splitlines() if line.count("\t") >= 2]
                    if not names or any(_normalized_target(name) != target_name for name in names):
                        return {"status": "failed", "reason": "补丁含有非目标文件的修改", "attempts": attempts, "output": None}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"status": "unverified", "reason": str(error), "attempts": attempts, "output": None}
    return {"status": "passed", "attempts": attempts, "output": target.read_bytes().decode("utf-8", errors="replace")}


def judge_workspace(workspace, case, tool_results, verification_dir):
    workspace = Path(workspace).resolve()
    verification_dir = Path(verification_dir).resolve()
    if verification_dir == workspace or verification_dir.is_relative_to(workspace):
        raise ValueError("补丁复核目录必须位于任务工作目录之外")
    initial = snapshot_files(ROOT / case["initial_directory"])
    actual = snapshot_files(workspace)
    target = case["target_file"]
    expected = case["expected_content"].encode("utf-8")
    content = actual.get(target)
    actual_content = content.decode("utf-8", errors="replace") if content is not None else None
    edits = [item for item in tool_results if item.tool_name == "edit_file" and item.error is None]
    chain = rebuild_patch_chain(initial[target], target, edits, verification_dir)
    checks = {
        "disk_target_matches_expected": {"status": "passed" if content == expected else "failed",
                                          "actual": actual_content, "expected": case["expected_content"]},
        "file_set_unchanged": {"status": "passed" if set(initial) == set(actual) else "failed",
                               "actual": sorted(actual), "expected": sorted(initial)},
        "other_initial_files_unchanged": {"status": "passed" if all(actual.get(name) == data for name, data in initial.items() if name != target) else "failed"},
        "successful_edit_evidence_exists": {"status": "passed" if edits else "failed", "actual": len(edits), "expected": "> 0"},
        "patch_chain_recreates_expected_and_actual": {
            "status": "unverified" if chain["status"] == "unverified" else
                      "passed" if chain["status"] == "passed" and chain["output"] == case["expected_content"] and chain["output"] == actual_content else "failed",
            "actual": chain["output"], "expected": case["expected_content"],
        },
    }
    statuses = {item["status"] for item in checks.values()}
    verdict = "failed" if "failed" in statuses else "unverified" if "unverified" in statuses else "passed"
    return {"case_verdict": verdict, "checks": checks, "patch_chain": chain, "actual_content": actual_content}
