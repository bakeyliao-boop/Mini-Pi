"""候选到只读计划的固定案例；不替代真实提取、字段支持或意图核验。

字段与 action 均由合成调用方明确提供；更新重试直接执行原计划。
核心仍占位时只检查语法和测试发现，不预先记程序行为通过。
"""

from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.memory.errors import MemoryConflict, MemoryPolicyError
from mini_pi.memory.execution import execute_plans
from mini_pi.memory.models import MemoryDraft, MemoryEntry, MemoryScope, MemorySource
from mini_pi.memory.planning import RememberPlan, ReplacePlan, plan_candidate
from mini_pi.memory.selection import MemoryCandidate, route_candidates
from mini_pi.memory.store import MemoryStore


class CandidatePlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_memory_candidate_planning_")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "memory" / "state.sqlite3"
        self.scope = MemoryScope("candidate-planning-user", "mini-pi")
        self.source = MemorySource(
            "candidate-planning-source-1", self.scope, "user",
            "从2026年11月1日起，周末学习请用 Python 举例。今天只解释，不改文件。谢谢。",
            "2026-10-23T02:00:00.000000+00:00",
        )
        self.candidate = MemoryCandidate(
            self.source, "用户要求2026年11月1日起周末学习使用 Python 示例。", "long_term",
            "固定候选，字段与写入意图由调用方明确提供。",
        )
        self.fields = dict(key="example_language", kind="semantic",
                           conditions=(("timezone", "Asia/Shanghai"), ("period", "weekend")),
                           valid_from="2026-11-01T00:00:00+08:00")
        self.draft = MemoryDraft(
            self.fields["key"], 0, len(self.source.text), self.fields["valid_from"],
            kind=self.fields["kind"], conditions=self.fields["conditions"], content=self.candidate.content,
        )
        self.source2 = replace(
            self.source, source_id="candidate-planning-source-2",
            text="从2026年12月1日起，周末学习明确改用 TypeScript 示例。",
            recorded_at="2026-10-24T02:00:00.000000+00:00",
        )
        self.candidate2 = replace(self.candidate, source=self.source2,
                                  content="用户要求2026年12月1日起周末学习改用 TypeScript 示例。")
        self.fields2 = {**self.fields, "valid_from": "2026-12-01T00:00:00+08:00"}
        self.draft2 = replace(self.draft, end=len(self.source2.text), valid_from=self.fields2["valid_from"],
                              content=self.candidate2.content)
        self.store = MemoryStore(self.path)

    @contextmanager
    def no_writes(self):
        with ExitStack() as stack:
            spies = [stack.enter_context(patch.object(
                self.store, name, side_effect=AssertionError("规划入口不得执行持久变更"),
            )) for name in ("remember", "replace", "retract")]
            spies.append(stack.enter_context(patch.object(
                self.store._backend, "transaction", side_effect=AssertionError("规划不得开启写事务"),
            )))
            network = AsyncMock(side_effect=AssertionError("固定规划案例不得请求模型"))
            stack.enter_context(patch("mini_pi.async_http_transport.post_json_async", network))
            yield
            for spy in spies:
                spy.assert_not_called()
            network.assert_not_called()

    @contextmanager
    def no_store_queries(self):
        with (self.no_writes(),
              patch.object(self.store, "get", side_effect=AssertionError("非法输入不得读取候选")) as get,
              patch.object(self.store, "latest", side_effect=AssertionError("非法输入不得读取系列")) as latest):
            yield
            get.assert_not_called()
            latest.assert_not_called()

    def test_fresh_remember_returns_complete_readonly_plan_without_creating_database(self):
        with (self.no_writes(),
              patch("sqlite3.connect", side_effect=AssertionError("缺库不得创建连接")) as connect):
            plan = plan_candidate(self.store, self.scope, self.candidate, action="remember", **self.fields)
            connect.assert_not_called()
        self.assertIsInstance(plan, RememberPlan)
        self.assertEqual((plan.scope, plan.source, plan.draft.content),
                         (self.scope, self.source, self.candidate.content))
        self.assertEqual((plan.draft.key, plan.draft.kind, plan.draft.start, plan.draft.end),
                         (self.fields["key"], "semantic", 0, len(self.source.text)))
        self.assertEqual(plan.draft.conditions, (("period", "weekend"), ("timezone", "Asia/Shanghai")))
        self.assertEqual(plan.draft.valid_from, "2026-10-31T16:00:00.000000+00:00")
        self.assertFalse(self.path.parent.exists())

    def test_remember_retry_keeps_superseded_and_retracted_entry_without_latest_or_write(self):
        first = self.store.remember(self.scope, self.source, self.draft)
        self.store.replace(self.scope, self.source2, self.draft2,
                           expected_version=1, operation_id="seed-future-v2")
        for state in ("superseded", "retracted"):
            if state == "retracted":
                control = replace(self.source, source_id="seed-control", text="撤回周末学习示例语言偏好。")
                self.store.retract(self.scope, control, self.draft.key, conditions=self.draft.conditions,
                                   expected_version=2, operation_id="seed-withdraw")
            with self.subTest(state=state):
                before = self.path.read_bytes()
                with (self.no_writes(),
                      patch.object(self.store, "latest", side_effect=AssertionError("命中旧候选不读latest")) as latest):
                    found = plan_candidate(self.store, self.scope, self.candidate, action="remember", **self.fields)
                    latest.assert_not_called()
                self.assertIsInstance(found, MemoryEntry)
                self.assertEqual((found.memory_id, found.version, found.state), (first.memory_id, 1, state))
                self.assertEqual(self.path.read_bytes(), before)

    def test_new_source_in_existing_series_does_not_implicitly_plan_replace(self):
        first = self.store.remember(self.scope, self.source, self.draft)
        before = self.path.read_bytes()
        with self.no_writes():
            with self.assertRaises(MemoryConflict):
                plan_candidate(self.store, self.scope, self.candidate2, action="remember", **self.fields2)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.store.latest(self.scope, self.draft.key, conditions=self.draft.conditions), first)

    def test_invalid_action_or_operation_id_is_rejected_before_any_store_query(self):
        cases = [(action, None) for action in ("upsert", "", None, [], {})]
        cases.extend(("remember", operation_id) for operation_id in ("unexpected", "", False, []))
        cases.extend(("replace", operation_id) for operation_id in (None, "", " \n", 42))
        with self.no_store_queries():
            for action, operation_id in cases:
                with self.subTest(action=action, operation_id=operation_id):
                    with self.assertRaises(MemoryPolicyError):
                        plan_candidate(self.store, self.scope, self.candidate, action=action,
                                       operation_id=operation_id, **self.fields)
        self.assertFalse(self.path.parent.exists())

    def test_first_replace_plan_executes_and_original_plan_replays_after_v3(self):
        self.store.remember(self.scope, self.source, self.draft)
        before = self.path.read_bytes()
        with self.no_writes():
            plan = plan_candidate(self.store, self.scope, self.candidate2, action="replace",
                                  operation_id="candidate-update", **self.fields2)
        self.assertIsInstance(plan, ReplacePlan)
        self.assertEqual((plan.expected_version, plan.operation_id, plan.source, plan.draft.content),
                         (1, "candidate-update", self.source2, self.candidate2.content))
        self.assertEqual(self.path.read_bytes(), before)
        second, = execute_plans(self.store, self.scope, [plan])
        source3 = replace(self.source2, source_id="candidate-planning-source-3",
                          text="从2027年1月1日起，周末学习改用 Rust 示例。")
        draft3 = replace(self.draft2, end=len(source3.text), valid_from="2027-01-01T00:00:00+08:00",
                         content="用户要求2027年1月1日起周末学习改用 Rust 示例。")
        self.store.replace(self.scope, source3, draft3, expected_version=2, operation_id="later-v3")
        before = self.path.read_bytes()
        with patch.object(self.store, "latest", side_effect=AssertionError("重试直接执行原计划")) as latest:
            replay, = execute_plans(self.store, self.scope, [plan])
            latest.assert_not_called()
        self.assertEqual((replay.memory_id, replay.version, replay.state),
                         (second.memory_id, 2, "superseded"))
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_route_scope_or_fields_is_rejected_before_store_query(self):
        candidates = [replace(self.candidate, proposed_route=route)
                      for route in ("task_constraint", "ignore", "needs_review", "withdrawal")]
        candidates.extend((
            replace(self.candidate, source=replace(
                self.source, scope=MemoryScope("other-user", self.scope.project_id),
            )),
            replace(self.candidate, source=replace(self.source, role="assistant")),
        ))
        with self.no_store_queries():
            for candidate in candidates:
                with self.subTest(candidate=candidate):
                    with self.assertRaises(MemoryPolicyError):
                        plan_candidate(self.store, self.scope, candidate, action="remember", **self.fields)
            with self.assertRaises(MemoryPolicyError):
                plan_candidate(self.store, self.scope, self.candidate, action="remember",
                               **{**self.fields, "key": ""})
        self.assertFalse(self.path.parent.exists())

    def test_five_routes_are_preserved_and_two_readonly_plans_are_rejected_before_execution(self):
        source = replace(self.source, text=(
            "从2026年11月1日起，周末用 Python 举例。从现在起，后续回答尽量简洁。"
            "今天只解释。我猜测试通过了。请撤回旧输出格式偏好。谢谢。"
        ))
        language = replace(self.candidate, source=source)
        style = replace(self.candidate, source=source, content="用户希望从现在起后续回答尽量简洁。")
        others = [replace(language, proposed_route=route, content=content) for route, content in (
            ("task_constraint", "今天只解释。"), ("needs_review", "测试通过尚属猜测。"),
            ("withdrawal", "撤回旧输出格式偏好仍需独立控制流程。"), ("ignore", "礼貌致谢。"),
        )]
        routed = route_candidates(self.scope, [language, style, *others])
        snapshot = dict(routed)
        self.assertEqual(routed["long_term"], (language, style))
        for candidate in others:
            self.assertEqual(routed[candidate.proposed_route], (candidate,))
        style_fields = dict(key="response_style", kind="semantic", conditions=(), valid_from=source.recorded_at)
        with (self.no_writes(),
              patch("sqlite3.connect", side_effect=AssertionError("只读缺库规划或批次拒绝不得开库")) as connect):
            plans = [plan_candidate(self.store, self.scope, language, action="remember", **self.fields),
                     plan_candidate(self.store, self.scope, style, action="remember", **style_fields)]
            self.assertTrue(all(isinstance(plan, RememberPlan) for plan in plans))
            self.assertFalse(self.path.parent.exists())
            with self.assertRaises(MemoryPolicyError):
                execute_plans(self.store, self.scope, plans)
            connect.assert_not_called()
        self.assertEqual(routed, snapshot)
        self.assertFalse(self.path.parent.exists())


if __name__ == "__main__":
    unittest.main()
