"""保存的合成Session→提取→五组→计划，可显式验收临时库写入和重试。

仅使用临时JSONL和内存响应，不读取凭据、不调用真实API、不执行历史工具。
Scope由可信教学脚本明确提供，JSONL本身不证明用户身份。
"""

import asyncio
import argparse
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mini_pi.memory.extraction_client import MemoryExtractor
from mini_pi.memory.execution import execute_plans
from mini_pi.memory.models import MemoryScope
from mini_pi.memory.planning import plan_candidate
from mini_pi.memory.retrieval import is_usable
from mini_pi.memory.store import MemoryStore
from mini_pi.models import Message, ToolCall
from mini_pi.session_store import SessionStore


SYNTHETIC_KEY = "synthetic-session-demo-never-use-live"
SYNTHETIC_MODEL = "offline-session-fixed-response"
USER_TEXT = (
    "从2026年11月1日起，后续讲解请尽量用 Python 举例。"
    "这次修复必须保留原测试断言，不要改测试掩盖问题。"
    "我猜v2测试应该通过了，但还没有运行。发布按前面那个方案来。谢谢。"
)
TOOL_DATA = {
    "tool_call_id": "synthetic-discount-call", "tool_name": "run_tests",
    "output": "mini-pi-demo项目v2：python -m unittest tests.test_discount；Ran 3 tests; FAILED (failures=1)",
    "error": "合成测试失败观察，并非本示例执行了业务测试",
    "project": "mini-pi-demo", "version": "v2", "exit_code": 1,
}


def write_demo_session(path: Path) -> dict[str, int]:
    """用现有SessionStore保存结构有效的合成历史；仅写文件，不执行其中调用。"""
    store = SessionStore(path, run_id="synthetic-session-run")
    store.append_entry("run_start", {"status": "running"})
    store.append_item(Message("user", USER_TEXT))
    store.append_item(Message("assistant", "记录本次测试观察。", [
        ToolCall("synthetic-discount-call", "run_tests", {}),
    ]))
    store.append_entry("tool_result", deepcopy(TOOL_DATA))
    store.append_entry("run_end", {"status": "finished", "task_passed": False})
    return {"run_start": 0, "user": 1, "assistant": 2, "tool": 3, "run_end": 4}


def fixed_response(role: str) -> dict:
    """事先写好的三字段响应；模拟模型返回，不能作为真实提取准确率证据。"""
    if role == "user":
        items = [
            {"content": "从2026年11月1日起，后续讲解尽量使用 Python 示例。",
             "proposed_route": "long_term", "reason": "合成案例中明确的后续讲解偏好。"},
            {"content": "本次修复必须保留原测试断言，不能改测试掩盖问题。",
             "proposed_route": "task_constraint", "reason": "合成案例中明确的本次任务要求。"},
            {"content": "用户猜测v2测试应该通过，但实际尚未运行。",
             "proposed_route": "needs_review", "reason": "通过结果仍是猜测，缺少运行证据。"},
            {"content": "用户希望发布沿用前面的方案，但本条材料没有方案细节，需要核对。",
             "proposed_route": "needs_review", "reason": "缺少所指内容，不判断用户是否早已确定。"},
            {"content": "用户表达感谢。", "proposed_route": "ignore", "reason": "单独致谢不形成长期写入计划。"},
        ]
    elif role == "tool":
        items = [{
            "content": "mini-pi-demo项目v2本次运行discount测试3项，其中1项失败，exit_code=1。",
            "proposed_route": "task_constraint", "reason": "限原任务使用的执行观察，不改写成用户要求或已匹配当前任务。",
        }]
    else:
        raise ValueError("固定演示只接用户或工具来源")
    return {"model": SYNTHETIC_MODEL, "choices": [{
        "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(items, ensure_ascii=False)},
    }]}


class FixedResponseExtractor(MemoryExtractor):
    """沿用请求和解析核心，只把发送换成内存固定响应。"""

    def __init__(self):
        super().__init__(api_key=SYNTHETIC_KEY, model=SYNTHETIC_MODEL,
                         base_url="https://synthetic.invalid/v1", max_requests=2)
        self.sent_requests = []

    async def _send(self, request):
        if self.request_count >= self.max_requests:
            raise RuntimeError("固定演示次数已用完")
        self.request_count += 1
        self.sent_requests.append(deepcopy(request))
        material = json.loads(request["messages"][1]["content"])
        return fixed_response(material["role"])


def describe_groups(groups):
    return {route: [{"content": item.content, "reason": item.reason,
                     "source_id": item.source.source_id, "source_role": item.source.role}
                    for item in candidates] for route, candidates in groups.items()}


async def run_demo(*, execute: bool = False):
    with TemporaryDirectory(prefix="mini-pi-session-demo-") as directory:
        scope = MemoryScope("demo-user", "mini-pi-demo")  # 调用方明确范围，不从JSONL推断认证。
        path = Path(directory) / "saved-session.jsonl"
        indices = write_demo_session(path)  # 先实际保存，再从指定记录提取。
        session_before = path.read_bytes()  # 核对提取和写入没有改动原会话。
        extractor = FixedResponseExtractor()
        user_groups = await extractor.extract_session(scope, path, indices["user"])  # 新核心：读保存记录，复用提取并归组。
        tool_groups = await extractor.extract_session(scope, path, indices["tool"])  # 只读取历史结果，不重新执行历史工具。

        if len(user_groups["long_term"]) != 1:
            raise ValueError("固定示例应只有事先核对过的一条长期偏好")
        candidate = user_groups["long_term"][0]
        database = Path(directory) / "memory" / "state.sqlite3"
        store = MemoryStore(database)  # 仅登记临时路径，尚未创建数据库。
        fields = dict(action="remember", key="explanation_language", kind="semantic",
                      conditions=(), valid_from="2026-11-01T00:00:00+08:00")  # 原文明示日期，调用方明确采用Asia/Shanghai。
        plan = plan_candidate(  # 演示调用方已核对正文后，明确补齐字段；不是模型自行授权。
            store, scope, candidate, **fields,
        )
        if database.parent.exists():
            raise AssertionError("只读演示不应创建记忆目录或SQLite文件")
        report = {
            "mode": "offline_fixed_response_demo", "real_model_calls": 0,
            "scope_supplied_by_caller": asdict(scope),
            "sources": {"user": asdict(candidate.source), "tool": asdict(tool_groups["task_constraint"][0].source)},
            "user_groups": describe_groups(user_groups), "tool_groups": describe_groups(tool_groups),
            "readonly_plan": {"type": type(plan).__name__, "draft": asdict(plan.draft)},
            "executed_plans": 0, "memory_database_created": False,
            "note": "固定响应仅验证文件读取与接线；不证明模型语义、当前任务匹配或MEM-04消费。临时Session随演示结束清理。",
        }
        if execute:  # 只有显式选择执行模式，才操作这个临时合成数据库。
            def row_counts():
                with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
                    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                            for table in ("sources", "entries", "operation_receipts")}  # 表名仅来自本地固定列表。

            first, = execute_plans(store, scope, (plan,))  # 首次明确执行，复用已验收remember。
            first_counts = row_counts()
            repeated, = execute_plans(store, scope, (plan,))  # 原计划原样重试，不重新提取或生成生效时间。
            repeated_counts = row_counts()
            retry = plan_candidate(store, scope, candidate, **fields)  # 同一Source及字段重新规划，直接得到原Entry。
            passed_through, = execute_plans(store, scope, (retry,))  # 已存Entry只透传，不再次变更。
            reopened = MemoryStore(database).get(scope, first.memory_id)  # 新Store从磁盘读回，不复用内存结果。
            final_counts = row_counts()
            if not (first == repeated == retry == passed_through == reopened):
                raise AssertionError("原计划重试、同候选规划和磁盘读回必须得到同一版本")
            if not (first_counts == repeated_counts == final_counts == {"sources": 1, "entries": 1, "operation_receipts": 0}):
                raise AssertionError("只能落下一条明确长期偏好，重试不得增加记录")
            if first.source != candidate.source or first.draft != plan.draft or first.version != 1:
                raise AssertionError("写入必须保留完整来源、已确认字段和首次版本")
            usable_before = is_usable(reopened, scope, conditions=(), at="2026-10-26T10:00:00+08:00")
            usable_from = is_usable(reopened, scope, conditions=(), at=fields["valid_from"])
            if usable_before or not usable_from:
                raise AssertionError("已写入不代表未来偏好已经生效")
            report.update({
                "mode": "offline_fixed_response_temporary_write_demo",
                "executed_plans": 2, "memory_database_created": True,
                "temporary_write": {
                    "entry": asdict(reopened), "text": reopened.text,
                    "counts_after_first": first_counts, "counts_after_original_plan_retry": repeated_counts,
                    "counts_after_replanning": final_counts, "retry_plan_type": type(retry).__name__,
                    "same_entry_and_version": True, "fresh_store_readback_matches": True,
                    "usable_before_valid_from": usable_before, "usable_at_valid_from": usable_from,
                    "nonempty_routes_not_written": ["task_constraint", "needs_review", "ignore"],
                    "withdrawal_exercised": False,
                },
                "note": "仅固定响应与临时SQLite接线验收；只有可信调用方明确选定的一条偏好写入。未验证真实提取泛化、当前任务关联或MEM-04消费；临时文件随后清理。",
            })
        if path.read_bytes() != session_before:
            raise AssertionError("原Session不得被派生候选或长期记忆写入改动")
        report["original_session_unchanged"] = True
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="显式执行临时SQLite写入及重试验收")
    asyncio.run(run_demo(execute=parser.parse_args().execute))
