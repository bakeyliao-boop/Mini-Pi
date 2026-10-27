"""MEM-04 独立 Context 组装的离线反例；不证明 provider 已收到资料。

助手准备测试。正式执行应等待学习者完成 build_context 核心；不调用模型、
不执行历史工具，也不在测试中提供替代核心实现。
"""

from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.memory.context import build_context
from mini_pi.memory.errors import MemoryContextError, MemoryPolicyError
from mini_pi.memory.models import MemoryDraft, MemoryHit, MemoryScope, MemorySource
from mini_pi.memory.selection import MemoryCandidate
from mini_pi.memory.store import MemoryStore
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore


QUERY_AT = "2026-10-26T10:00:00+08:00"
QUERY_AT_UTC = "2026-10-26T02:00:00.000000+00:00"
EARLY = "2026-01-01T00:00:00+08:00"
POLICY_ERRORS = (MemoryContextError, MemoryPolicyError)


class MemoryContextTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="memory-context-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scope = MemoryScope("user-a", "mini-pi-demo")
        self.store = MemoryStore(self.root / "memory.sqlite3")

    def source(self, source_id, text, *, scope=None, role="user"):
        return MemorySource(source_id, scope or self.scope, role, text, EARLY)

    def remember(self, key="example_language", text="后续尽量用 Python 举例。", *,
                 source_id="preference-1", valid_from=EARLY, conditions=()):
        source = self.source(source_id, text)
        draft = MemoryDraft(key, 0, len(text), valid_from,
                            conditions=conditions, content=text)
        return self.store.remember(self.scope, source, draft)

    def candidate(self, content, route="task_constraint", *, role="user", source_id="task-1"):
        source = self.source(source_id, content, role=role)
        return MemoryCandidate(source, content, route, "可信调用方已确认属于当前任务。")

    def recent(self):
        return [
            Message("system", "你是编程助手。"),
            Message("system", "使用工具前核对任务。"),
            Message("user", "修复 v2 折扣问题，保留原测试断言。"),
            Message("assistant", "运行原测试确认现状。", [
                ToolCall("test-v2", "run_tests", {"target": ["tests.test_discount"]}),
            ]),
            ToolResult("test-v2", "run_tests", "Ran 3 tests; FAILED (failures=1)", "测试失败"),
            Message("user", "继续定位失败原因。"),
        ]

    def build(self, hits=(), recent_messages=None, **kwargs):
        arguments = {"task_material": (), "at": QUERY_AT,
                     "conditions": (), "max_context_chars": 100_000}
        arguments.update(kwargs)
        return build_context(self.store, self.scope, hits,
                             self.recent() if recent_messages is None else recent_messages,
                             **arguments)

    def payload(self, messages):
        # 两条原 system 在前，资料只能成为其后的 user 消息。
        self.assertEqual([item.role for item in messages[:3]], ["system", "system", "user"])
        return json.loads(messages[2].content)

    def test_material_sources_and_memory_are_preserved_without_polluting_history_or_session(self):
        entry = self.remember()
        history = self.recent()
        snapshot = deepcopy(history)
        session = SessionStore(self.root / "session.jsonl", run_id="context-test")
        for item in history:
            session.append_item(item)
        saved_bytes = session.path.read_bytes()
        material = (
            self.candidate("保留原测试断言，不要通过改测试掩盖失败。"),
            self.candidate("v2 可能已通过，但尚未运行，需要核对。", "needs_review", source_id="guess"),
            self.candidate("v2 三项测试有一项失败。", role="tool", source_id="test-observation"),
        )

        messages = self.build([MemoryHit(entry, 0.9)], history, task_material=material)
        data = self.payload(messages)
        self.assertEqual(set(data), {"purpose", "query_at", "task_material", "memories"})
        self.assertIsInstance(data["purpose"], str)
        self.assertTrue(data["purpose"].strip())
        self.assertEqual(data["query_at"], QUERY_AT_UTC)
        self.assertEqual(data["task_material"], [
            {"content": item.content, "proposed_route": item.proposed_route,
             "reason": item.reason,
             "source": {"source_id": item.source.source_id, "role": item.source.role,
                        "recorded_at": item.source.recorded_at}}
            for item in material
        ])
        self.assertEqual(data["memories"], [{
            "memory_id": entry.memory_id, "content": entry.text,
            "version": entry.version, "state": entry.state,
            "valid_from": entry.draft.valid_from, "valid_to": entry.valid_to,
            "conditions": [],
            "source": {"source_id": entry.source.source_id, "role": entry.source.role,
                       "recorded_at": entry.source.recorded_at},
        }])
        self.assertEqual(messages[:2] + messages[3:], history)
        self.assertEqual(history, snapshot)
        self.assertEqual(session.path.read_bytes(), saved_bytes)
        # 改写请求副本的嵌套工具参数和消息，不应回写真实历史。
        messages[4].tool_calls[0].arguments["target"].append("other-test")
        messages[0].content = "仅修改请求副本"
        self.assertEqual(history, snapshot)
        self.assertEqual(session.path.read_bytes(), saved_bytes)

    def test_future_and_unmatched_conditions_are_filtered_before_injection(self):
        future = self.remember(valid_from="2026-11-01T00:00:00+08:00")
        weekend = self.remember("study_time", "周末晚上学习。", source_id="weekend",
                                conditions=(("day_type", "weekend"),))
        history = self.recent()
        messages = self.build([MemoryHit(future, 0.99), MemoryHit(weekend, 0.95)], history,
                              conditions=(("day_type", "weekday"),))
        self.assertEqual(messages, history)
        self.assertEqual(len(messages), len(history))

    def test_historical_v1_remains_usable_after_replace_without_requiring_latest(self):
        original = self.remember(text="晚上学习。")
        source = self.source("preference-2", "从十月二十日起改为早上学习。")
        draft = MemoryDraft(original.draft.key, 0, len(source.text),
                            "2026-10-20T00:00:00+08:00", content="早上学习。")
        self.store.replace(self.scope, source, draft, expected_version=1, operation_id="replace-2")
        with patch.object(self.store, "latest", side_effect=AssertionError("历史查询不能强制最高版本")):
            messages = self.build([MemoryHit(original, 0.9)], at="2026-10-19T12:00:00+08:00")
        evidence = self.payload(messages)["memories"]
        self.assertEqual(len(evidence), 1)
        self.assertEqual((evidence[0]["version"], evidence[0]["content"], evidence[0]["state"]),
                         (1, "晚上学习。", "superseded"))
        self.assertEqual(evidence[0]["valid_to"], "2026-10-19T16:00:00.000000+00:00")
        # 同一旧命中在版本有效期结束时不能继续使用。
        self.assertEqual(self.build([MemoryHit(original, 0.9)]), self.recent())

    def test_retracted_stale_hit_is_not_reintroduced_even_for_historical_query(self):
        entry = self.remember()
        source = self.source("withdraw-1", "撤回这个学习偏好。")
        self.store.retract(self.scope, source, entry.draft.key,
                           expected_version=1, operation_id="withdraw-operation")
        self.assertEqual(self.build([MemoryHit(entry, 0.99)]), self.recent())
        self.assertEqual(self.build([MemoryHit(entry, 0.99)], at="2026-10-01T00:00:00+08:00"),
                         self.recent())

    def test_missing_or_redefined_hit_fails_instead_of_becoming_empty_recall(self):
        entry = self.remember()
        changes = {
            "missing": None,
            "source": replace(entry, source=replace(entry.source, text="被改写的来源。")),
            "draft": replace(entry, draft=replace(entry.draft, content="被改写的记忆。")),
            "version": replace(entry, version=entry.version + 1),
            "written_at": replace(entry, written_at="2026-10-25T00:00:00.000000+00:00"),
        }
        for name, current in changes.items():
            with self.subTest(change=name):
                with patch.object(self.store, "get", return_value=current):
                    with self.assertRaises(MemoryContextError):
                        self.build([MemoryHit(entry, 0.9)])

    def test_database_failure_is_propagated_without_fallback_to_no_memory(self):
        entry = self.remember()
        failure = OSError("合成读取失败")
        with patch.object(self.store, "get", side_effect=failure) as read:
            with self.assertRaises(OSError) as caught:
                self.build([MemoryHit(entry, 0.9)])
        self.assertIs(caught.exception, failure)
        read.assert_called_once_with(self.scope, entry.memory_id)

    def test_foreign_user_or_project_cannot_supply_hits_or_current_task_material(self):
        entry = self.remember()
        for foreign_scope in (MemoryScope("user-b", self.scope.project_id),
                              MemoryScope(self.scope.user_id, "other-project")):
            with self.subTest(scope=foreign_scope):
                foreign_entry = replace(entry, scope=foreign_scope,
                                        source=replace(entry.source, scope=foreign_scope))
                with patch.object(self.store, "get", side_effect=AssertionError("错范围不能继续查主记录")):
                    with self.assertRaises(POLICY_ERRORS):
                        self.build([MemoryHit(foreign_entry, 1.0)])
                material = self.candidate("保留该项目原测试。")
                material = replace(material, source=replace(material.source, scope=foreign_scope))
                with self.assertRaises(POLICY_ERRORS):
                    self.build(task_material=(material,))

    def test_only_confirmed_task_or_review_routes_and_allowed_source_roles_enter_task_material(self):
        original = self.candidate("当前任务材料。")
        for route in ("long_term", "ignore", "withdrawal"):
            with self.subTest(route=route):
                with self.assertRaises(POLICY_ERRORS):
                    self.build(task_material=(replace(original, proposed_route=route),))
        for role in ("assistant", "system"):
            with self.subTest(role=role):
                bad = replace(original, source=replace(original.source, role=role))
                with self.assertRaises(POLICY_ERRORS):
                    self.build(task_material=(bad,))

    def test_tool_results_must_match_an_entire_contiguous_call_group(self):
        call_a = ToolCall("a", "read_file", {"path": "a.py"})
        call_b = ToolCall("b", "read_file", {"path": "b.py"})
        result_a = ToolResult("a", "read_file", "a内容")
        result_b = ToolResult("b", "read_file", "b内容")
        complete = [Message("user", "读取这两个文件。"),
                    Message("assistant", "", [call_a, call_b]), result_a, result_b,
                    Message("user", "继续。")]
        self.assertEqual(self.build(recent_messages=complete), complete)
        malformed = {
            "orphan": [result_a],
            "missing_result": [Message("assistant", "", [call_a, call_b]), result_a],
            "wrong_name": [Message("assistant", "", [call_a]), replace(result_a, tool_name="run_tests")],
            "duplicate_result": [Message("assistant", "", [call_a]), result_a, result_a],
            "duplicate_call_id": [Message("assistant", "", [call_a, call_a]), result_a],
            "interrupted_group": [Message("assistant", "", [call_a]), Message("user", "继续。"), result_a],
        }
        for name, history in malformed.items():
            with self.subTest(case=name):
                snapshot = deepcopy(history)
                with self.assertRaises(POLICY_ERRORS):
                    self.build(recent_messages=history)
                self.assertEqual(history, snapshot)

    def test_empty_sources_add_no_message_and_budget_counts_exact_serialized_request(self):
        history = self.recent()
        self.assertEqual(self.build(recent_messages=history), history)
        self.assertEqual(self.build(recent_messages=[]), [])
        material = (self.candidate("本次保留所有原断言。"),)
        messages = self.build(recent_messages=history, task_material=material)
        exact = len(json.dumps([asdict(item) for item in messages], ensure_ascii=False,
                               separators=(",", ":")))
        self.assertEqual(self.build(recent_messages=history, task_material=material,
                                    max_context_chars=exact), messages)
        with self.assertRaises(MemoryContextError):
            self.build(recent_messages=history, task_material=material, max_context_chars=exact - 1)
        self.assertEqual(history, self.recent())

    def test_malformed_batch_envelopes_are_rejected_before_reading_store(self):
        for arguments in ({"hits": iter(())}, {"recent_messages": "不是消息列表"},
                          {"task_material": iter(())}, {"at": "2026-10-26T10:00:00"},
                          {"max_context_chars": True}):
            with self.subTest(arguments=arguments):
                with patch.object(self.store, "get", side_effect=AssertionError("格式错误不能开始读取")):
                    with self.assertRaises(POLICY_ERRORS):
                        self.build(**arguments)


if __name__ == "__main__":
    unittest.main()
