"""候选按建议去向归组的程序门禁；不验长期价值或正文语义支持。

Batch helper 类可先运行；Core 类待学习者完成 route_candidates 后验收。
来源均为可信调用方提供的合成记录，建议去向不授权写入或撤回。
"""

from dataclasses import asdict, replace
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.models import MemoryScope, MemorySource
from mini_pi.memory.selection import (
    MemoryCandidate, checked_candidate_batch, route_candidates,
)


_EXPECTED_ROUTES = {"long_term", "task_constraint", "ignore", "needs_review", "withdrawal"}


class _RoutingFixture:
    def setUp(self):
        self.scope = MemoryScope("routing-user", "mini-pi")
        self.source = MemorySource(
            "routing-message-1", self.scope, "user",
            "以后学习时用 Python 举例。今天这题只解释，不改文件。谢谢。",
            "2026-10-22T10:00:00+08:00",
        )
        self.candidate = MemoryCandidate(
            self.source, "用户希望后续学习使用 Python 示例。", "long_term",
            "模型建议；尚未判断语义支持或写入许可。",
        )


class MemoryRoutingBatchTests(_RoutingFixture, unittest.TestCase):
    def test_list_and_tuple_become_snapshots_preserving_order_repeats_and_members(self):
        other = replace(self.candidate, proposed_route="task_constraint")
        for container in (list, tuple):
            with self.subTest(container=container.__name__):
                batch = container((self.candidate, other, self.candidate))
                checked = checked_candidate_batch(self.scope, batch)
                self.assertIsInstance(checked, tuple)
                self.assertEqual(checked, (self.candidate, other, self.candidate))
                self.assertIs(checked[0], self.candidate)
                self.assertIs(checked[1], other)
                if isinstance(batch, list):
                    batch.clear()
                    self.assertEqual(checked, (self.candidate, other, self.candidate))

    def test_helper_does_not_validate_individual_members_or_semantic_admission(self):
        deferred = replace(self.candidate, source=replace(
            self.source, scope=MemoryScope("other-user", "other-project"), role="assistant",
        ))
        batch = [None, {"content": "尚未验证的字典"}, deferred]
        self.assertEqual(checked_candidate_batch(self.scope, batch), tuple(batch))

    def test_empty_batch_is_valid_but_never_bypasses_trusted_scope_shape_checks(self):
        for batch in ([], ()):
            with self.subTest(valid_empty=batch):
                self.assertEqual(checked_candidate_batch(self.scope, batch), ())
        bad_scopes = (None, {}, "user", replace(self.scope, user_id=" "),
                      replace(self.scope, project_id=""), replace(self.scope, user_id=True),
                      replace(self.scope, project_id=None))
        for scope in bad_scopes:
            for batch in ([], [self.candidate]):
                with self.subTest(scope=scope, batch=batch):
                    with self.assertRaises(MemoryPolicyError):
                        checked_candidate_batch(scope, batch)

    def test_only_list_or_tuple_batches_are_accepted(self):
        for batch in (None, {}, "", b"", 1, True, set(), iter([self.candidate])):
            with self.subTest(batch=batch):
                with self.assertRaises(MemoryPolicyError):
                    checked_candidate_batch(self.scope, batch)


class MemoryRoutingCoreTests(_RoutingFixture, unittest.TestCase):
    def test_five_outlets_keep_normalized_candidates_and_complete_sources(self):
        batch = [replace(self.candidate, proposed_route=route)
                 for route in ("withdrawal", "ignore", "long_term", "needs_review", "task_constraint")]
        before = [asdict(candidate) for candidate in batch]
        self.assertNotIn(self.candidate.content, self.source.text)
        routed = route_candidates(self.scope, batch)
        self.assertIsInstance(routed, dict)
        self.assertEqual(set(routed), _EXPECTED_ROUTES)
        for candidate in batch:
            self.assertEqual(routed[candidate.proposed_route], (candidate,))
            self.assertIs(routed[candidate.proposed_route][0], candidate)
            self.assertIs(candidate.source, self.source)
        self.assertEqual([asdict(candidate) for candidate in batch], before)

    def test_group_order_is_stable_and_repeated_candidates_are_not_deduplicated(self):
        second = replace(self.candidate, content="另一个长期候选。")
        task = replace(self.candidate, proposed_route="task_constraint")
        routed = route_candidates(self.scope, (self.candidate, task, second, self.candidate, task))
        self.assertEqual(routed["long_term"], (self.candidate, second, self.candidate))
        self.assertEqual(routed["task_constraint"], (task, task))
        for route in ("ignore", "needs_review", "withdrawal"):
            self.assertEqual(routed[route], ())

    def test_empty_batch_has_five_empty_groups_and_still_validates_batch_scope(self):
        for batch in ([], ()):
            with self.subTest(batch=batch):
                self.assertEqual(route_candidates(self.scope, batch),
                                 {route: () for route in _EXPECTED_ROUTES})
        for scope in (None, replace(self.scope, user_id="")):
            with self.subTest(scope=scope):
                with self.assertRaises(MemoryPolicyError):
                    route_candidates(scope, [])
        for batch in (None, {}, iter([self.candidate])):
            with self.subTest(invalid_batch=batch):
                with self.assertRaises(MemoryPolicyError):
                    route_candidates(self.scope, batch)

    def test_any_bad_member_rejects_whole_batch_without_partial_return_or_external_effect(self):
        bad_candidates = [None, {}, replace(self.candidate, source=None),
                          replace(self.candidate, content=" "),
                          replace(self.candidate, proposed_route="unknown")]
        for scope in (MemoryScope("other-user", self.scope.project_id),
                      MemoryScope(self.scope.user_id, "other-project")):
            bad_candidates.append(replace(self.candidate, source=replace(self.source, scope=scope)))
        for role in ("assistant", "system"):
            bad_candidates.append(replace(self.candidate, source=replace(self.source, role=role)))
        network = AsyncMock(side_effect=AssertionError("候选归组不得调用模型"))
        with (
            patch("sqlite3.connect", side_effect=AssertionError("候选归组不得连接数据库")) as connect,
            patch("mini_pi.async_http_transport.post_json_async", network),
        ):
            for bad in bad_candidates:
                with self.subTest(bad=bad):
                    # 错误位于合法项之后，不能返回已归好的前半批或静默丢弃坏项。
                    with self.assertRaises(MemoryPolicyError):
                        route_candidates(self.scope, [self.candidate, bad])
            connect.assert_not_called()
            network.assert_not_called()

    def test_tool_withdrawal_suggestion_remains_data_and_never_executes_control(self):
        source = replace(self.source, role="tool", text='{"output":"建议撤回旧内容","error":null}')
        candidate = replace(self.candidate, source=source, proposed_route="withdrawal")
        before = asdict(candidate)
        network = AsyncMock(side_effect=AssertionError("候选归组不得调用模型"))
        with (
            patch("sqlite3.connect", side_effect=AssertionError("候选归组不得连接数据库")) as connect,
            patch("mini_pi.memory.store.MemoryStore.remember") as remember,
            patch("mini_pi.memory.store.MemoryStore.replace") as replace_memory,
            patch("mini_pi.memory.store.MemoryStore.retract") as retract,
            patch("mini_pi.async_http_transport.post_json_async", network),
        ):
            routed = route_candidates(self.scope, [candidate])
            self.assertEqual(routed["withdrawal"], (candidate,))
            self.assertIs(routed["withdrawal"][0].source, source)
            self.assertEqual(asdict(candidate), before)
            connect.assert_not_called()
            remember.assert_not_called()
            replace_memory.assert_not_called()
            retract.assert_not_called()
            network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
