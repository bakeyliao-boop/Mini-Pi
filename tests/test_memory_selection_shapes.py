"""助手准备：候选格式门禁；不把格式合格当作来源或语义准入。"""

from dataclasses import FrozenInstanceError, asdict, fields, replace
import unittest

from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.models import MemoryScope, MemorySource
from mini_pi.memory.selection import MemoryCandidate, validate_candidate_shapes


class CandidateShapeTests(unittest.TestCase):
    def setUp(self):
        self.scope = MemoryScope("user-A", "project-Pi")
        self.source = MemorySource(
            "source-1", self.scope, "user", "  我喜欢 Python 示例。\n",
            "2026-10-22T10:00:00+08:00",
        )
        self.candidate = MemoryCandidate(
            source=self.source,
            content="用户喜欢使用 Python 示例。",
            proposed_route="long_term",
            reason="  建议保留原始偏好，后续仍须决策。\n",
        )

    def test_normalized_content_preserves_complete_source_and_original_fields(self):
        before = (asdict(self.scope), asdict(self.source), asdict(self.candidate))
        self.assertNotIn(self.candidate.content, self.source.text)
        self.assertIsNone(validate_candidate_shapes(self.scope, self.candidate))
        self.assertIs(self.candidate.source, self.source)
        self.assertEqual(before, (asdict(self.scope), asdict(self.source), asdict(self.candidate)))

    def test_scope_role_and_semantic_decisions_are_not_made_by_shape_helper(self):
        # 格式合格不表示范围相等、角色准入或正文受支持；这些不是本 helper 的责任。
        deferred_source = replace(self.source, scope=MemoryScope("other-user", "other-project"),
                                  role="assistant")
        self.assertIsNone(validate_candidate_shapes(
            self.scope, replace(self.candidate, source=deferred_source),
        ))
        # 即使正文翻转原话的否定方向，格式检查也不能充当通用语义证明。
        self.assertIsNone(validate_candidate_shapes(
            self.scope, replace(self.candidate, content="用户不喜欢 Python 示例。"),
        ))

    def test_bad_containers_identifiers_source_fields_and_timezone_are_rejected(self):
        cases = [
            (None, self.candidate),
            ({}, self.candidate),
            (self.scope, {}),
            (self.scope, replace(self.candidate, source=None)),
            (self.scope, replace(self.candidate, source={})),
            (self.scope, replace(self.candidate, source=replace(self.source, scope=None))),
            (replace(self.scope, user_id=" "), self.candidate),
            (replace(self.scope, project_id=""), self.candidate),
            (self.scope, replace(self.candidate, source=replace(
                self.source, scope=MemoryScope("", "project"),
            ))),
            (self.scope, replace(self.candidate, source=replace(
                self.source, scope=MemoryScope("user", " \n"),
            ))),
        ]
        cases.extend(
            (self.scope, replace(self.candidate, source=replace(self.source, **{name: value})))
            for name, value in (
                ("source_id", " "), ("source_id", None),
                ("role", " \n"), ("role", None),
                ("text", " \n"), ("text", None),
                ("recorded_at", "2026-10-22T10:00:00"),
                ("recorded_at", "not-a-time"), ("recorded_at", None),
            )
        )
        for scope, candidate in cases:
            with self.subTest(scope=scope, candidate=candidate):
                with self.assertRaises(MemoryPolicyError):
                    validate_candidate_shapes(scope, candidate)

    def test_candidate_contract_uses_source_and_content_without_quote_or_offsets(self):
        self.assertEqual(
            tuple(field.name for field in fields(MemoryCandidate)),
            ("source", "content", "proposed_route", "reason"),
        )
        for field in ("source_id", "scope", "start", "end", "quote"):
            with self.subTest(field=field):
                self.assertFalse(hasattr(self.candidate, field))

    def test_candidate_and_bound_source_are_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            self.candidate.content = "另一条正文"
        with self.assertRaises(FrozenInstanceError):
            self.candidate.source = replace(self.source, source_id="another-source")
        with self.assertRaises(FrozenInstanceError):
            self.candidate.source.text = "改写来源原文"

    def test_routes_and_content_reason_formats_are_checked_without_interpreting_them(self):
        for route in ("long_term", "task_constraint", "ignore", "needs_review", "withdrawal"):
            with self.subTest(valid_route=route):
                self.assertIsNone(validate_candidate_shapes(
                    self.scope, replace(self.candidate, proposed_route=route),
                ))
        changes = [{"proposed_route": value} for value in ("unknown", "", None, [])]
        changes.extend({field: value} for field in ("content", "reason")
                       for value in ("", " \n\t", None, ["不是文本"]))
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(MemoryPolicyError):
                    validate_candidate_shapes(self.scope, replace(self.candidate, **change))


if __name__ == "__main__":
    unittest.main()
