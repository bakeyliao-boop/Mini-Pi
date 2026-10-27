"""MEM-W来源门禁反例；不把来源合格当作语义支持或分流许可。

Source均为可信调用方提供的合成记录；不模拟模型自行声明可信Source。
本文件待学习者替换旧核心接口后运行，不能据这些文字夹具判断任意语义。
"""

from dataclasses import asdict, replace
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.models import MemoryScope, MemorySource
from mini_pi.memory.selection import MemoryCandidate, validate_candidate_source


class MemoryCandidateSourceTests(unittest.TestCase):
    def setUp(self):
        self.scope = MemoryScope("user-A", "project-Pi")
        self.source = MemorySource(
            "trusted-record-1", self.scope, "user", "  我平时写 Python 程序。\n",
            "2026-10-22T10:00:00+08:00",
        )
        self.candidate = MemoryCandidate(
            self.source, "用户日常使用 Python 编程。", "long_term",
            "建议内容仍需后续语义与写入决策。",
        )

    def test_matching_trusted_user_or_tool_source_returns_none_and_preserves_source(self):
        for role in ("user", "tool"):
            with self.subTest(role=role):
                source = replace(self.source, role=role)
                candidate = replace(self.candidate, source=source)
                before = asdict(candidate)
                self.assertIsNone(validate_candidate_source(self.scope, candidate))
                self.assertEqual(asdict(candidate), before)
                self.assertIs(candidate.source, source)

    def test_foreign_user_or_project_source_is_rejected(self):
        scopes = (
            MemoryScope("other-user", self.scope.project_id),
            MemoryScope(self.scope.user_id, "other-project"),
        )
        for source_scope in scopes:
            with self.subTest(source_scope=source_scope):
                candidate = replace(self.candidate, source=replace(self.source, scope=source_scope))
                with self.assertRaises(MemoryPolicyError):
                    validate_candidate_source(self.scope, candidate)

    def test_assistant_and_system_sources_are_rejected(self):
        for role in ("assistant", "system"):
            with self.subTest(role=role):
                candidate = replace(self.candidate, source=replace(self.source, role=role))
                with self.assertRaises(MemoryPolicyError):
                    validate_candidate_source(self.scope, candidate)

    def test_format_guard_rejects_bad_content_and_containers_before_source_use(self):
        candidates = [None, {}, replace(self.candidate, source=None)]
        candidates.extend(replace(self.candidate, content=value)
                          for value in ("", " \n\t", None, ["不是字符串"], True))
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                with self.assertRaises(MemoryPolicyError):
                    validate_candidate_source(self.scope, candidate)

    def test_normalized_content_need_not_be_a_quote_and_original_source_is_retained(self):
        self.assertNotEqual(self.candidate.content, self.source.text)
        self.assertNotIn(self.candidate.content, self.source.text)
        original = asdict(self.source)
        self.assertIsNone(validate_candidate_source(self.scope, self.candidate))
        self.assertEqual(asdict(self.candidate.source), original)
        self.assertEqual(self.candidate.content, "用户日常使用 Python 编程。")

    def test_source_gate_does_not_claim_to_detect_negation_reversal(self):
        source = replace(self.source, text="我不喜欢 Python。")
        candidate = replace(self.candidate, source=source, content="用户喜欢 Python。")
        # 仅此夹具说明来源门禁职责；通过不表示该content受支持、可长期保存。
        self.assertIsNone(validate_candidate_source(self.scope, candidate))
        self.assertEqual(candidate.source.text, "我不喜欢 Python。")
        self.assertEqual(candidate.content, "用户喜欢 Python。")

    def test_all_route_suggestions_remain_data_without_database_or_model_calls(self):
        network = AsyncMock(side_effect=AssertionError("来源核对不得调用模型"))
        with (
            patch("sqlite3.connect", side_effect=AssertionError("来源核对不得写库")) as connect,
            patch("mini_pi.async_http_transport.post_json_async", network),
        ):
            for route in ("long_term", "task_constraint", "ignore", "needs_review", "withdrawal"):
                with self.subTest(route=route):
                    candidate = replace(self.candidate, proposed_route=route)
                    self.assertIsNone(validate_candidate_source(self.scope, candidate))
                    self.assertEqual(candidate.proposed_route, route)
            connect.assert_not_called()
            network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
