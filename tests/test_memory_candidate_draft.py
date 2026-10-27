"""候选与明确字段装配为 Draft；固定建议不代表真实提取或语义支持验收。

Source、key、kind、conditions、valid_from 均由合成案例明确提供。
构造阶段不写库；只有显式执行计划后才允许持久变更。
"""

from contextlib import contextmanager
from dataclasses import asdict, replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.execution import execute_plans
from mini_pi.memory.models import MemoryDraft, MemoryEntry, MemoryScope, MemorySource
from mini_pi.memory.planning import RememberPlan, plan_remember_or_retry
from mini_pi.memory.selection import MemoryCandidate, draft_from_candidate, route_candidates
from mini_pi.memory.store import MemoryStore


class CandidateDraftTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_memory_candidate_draft_")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "memory" / "state.sqlite3"
        self.scope = MemoryScope("candidate-draft-user", "mini-pi")
        self.source = MemorySource(
            "candidate-draft-source", self.scope, "user",
            "从2026年11月1日起，周末学习请用 Python 举例。今天这题只解释，不改文件。"
            "我猜测试应该通过了。谢谢。",
            "2026-10-23T02:00:00.000000+00:00",
        )
        self.candidate = MemoryCandidate(
            self.source, "用户要求2026年11月1日起周末学习使用 Python 示例。", "long_term",
            "固定候选建议；调用前须由上层核对正文及字段依据。",
        )
        self.fields = {
            "key": "example_language", "kind": "semantic",
            "conditions": (("timezone", "Asia/Shanghai"), ("period", "weekend")),
            "valid_from": "2026-11-01T00:00:00+08:00",
        }

    @contextmanager
    def no_external_io(self):
        network = AsyncMock(side_effect=AssertionError("Draft 装配不得请求模型"))
        with (patch("sqlite3.connect", side_effect=AssertionError("Draft 装配不得开库")) as connect,
              patch("mini_pi.async_http_transport.post_json_async", network)):
            yield
            connect.assert_not_called()
            network.assert_not_called()

    def test_explicit_future_fields_keep_complete_source_and_normalized_content_without_io(self):
        before = (asdict(self.scope), asdict(self.candidate), dict(self.fields))
        self.assertNotIn(self.candidate.content, self.source.text)
        with self.no_external_io():
            draft = draft_from_candidate(self.scope, self.candidate, **self.fields)
        self.assertIsInstance(draft, MemoryDraft)
        self.assertEqual((draft.key, draft.kind, draft.conditions),
                         (self.fields["key"], self.fields["kind"], self.fields["conditions"]))
        self.assertEqual((draft.start, draft.end), (0, len(self.source.text)))
        self.assertEqual(draft.content, self.candidate.content)
        self.assertEqual(draft.valid_from, self.fields["valid_from"])
        self.assertNotEqual(draft.valid_from, self.source.recorded_at)
        self.assertIs(self.candidate.source, self.source)
        self.assertEqual((asdict(self.scope), asdict(self.candidate), self.fields), before)
        self.assertFalse(self.path.parent.exists())

    def test_all_four_non_long_term_routes_are_rejected_without_io(self):
        with self.no_external_io():
            for route in ("task_constraint", "ignore", "needs_review", "withdrawal"):
                with self.subTest(route=route):
                    candidate = replace(self.candidate, proposed_route=route)
                    with self.assertRaises(MemoryPolicyError):
                        draft_from_candidate(self.scope, candidate, **self.fields)

    def test_foreign_scope_and_disallowed_source_roles_are_rejected(self):
        sources = [replace(self.source, scope=MemoryScope("other-user", self.scope.project_id)),
                   replace(self.source, scope=MemoryScope(self.scope.user_id, "other-project"))]
        sources.extend(replace(self.source, role=role) for role in ("assistant", "system"))
        with self.no_external_io():
            for source in sources:
                with self.subTest(source=source):
                    with self.assertRaises(MemoryPolicyError):
                        draft_from_candidate(self.scope, replace(self.candidate, source=source), **self.fields)

    def test_tool_observation_accepts_only_episodic_draft(self):
        raw = json.dumps({"tool_call_id": "synthetic-call", "tool_name": "run_tests",
                          "output": "2 passed", "error": None, "revision": "synthetic-revision"},
                         ensure_ascii=False)
        source = replace(self.source, source_id="synthetic-tool-source", role="tool", text=raw)
        candidate = replace(self.candidate, source=source, content="合成工具案例观察到2项测试通过。")
        fields = dict(key="test_observation", kind="episodic",
                      conditions=(("revision", "synthetic-revision"),), valid_from=source.recorded_at)
        with self.no_external_io():
            draft = draft_from_candidate(self.scope, candidate, **fields)
            self.assertEqual((draft.kind, draft.content, draft.start, draft.end),
                             ("episodic", candidate.content, 0, len(raw)))
            self.assertEqual(candidate.source.text, raw)
            for kind in ("semantic", "procedural"):
                with self.subTest(kind=kind):
                    with self.assertRaises(MemoryPolicyError):
                        draft_from_candidate(self.scope, candidate, **{**fields, "kind": kind})

    def test_invalid_or_omitted_explicit_metadata_is_rejected(self):
        changes = (
            {"key": " "}, {"key": None}, {"kind": "preference"},
            {"conditions": []}, {"conditions": (("period", ""),)},
            {"conditions": (("period", "weekend"), ("period", "weekday"))},
            {"valid_from": "2026-11-01T00:00:00"}, {"valid_from": "not-a-time"}, {"valid_from": None},
        )
        with self.no_external_io():
            for change in changes:
                with self.subTest(change=change):
                    with self.assertRaises(MemoryPolicyError):
                        draft_from_candidate(self.scope, self.candidate, **{**self.fields, **change})
            for field in ("key", "kind", "conditions", "valid_from"):
                with self.subTest(omitted=field):
                    fields = {key: value for key, value in self.fields.items() if key != field}
                    with self.assertRaises(TypeError):
                        draft_from_candidate(self.scope, self.candidate, **fields)
        self.assertFalse(self.path.parent.exists())

    def test_fixed_four_routes_build_one_plan_execute_explicitly_and_retry_without_new_write(self):
        candidates = [
            self.candidate,
            replace(self.candidate, content="本题只解释，不修改文件。", proposed_route="task_constraint"),
            replace(self.candidate, content="测试通过只是猜测，尚无实际结果。", proposed_route="needs_review"),
            replace(self.candidate, content="礼貌致谢。", proposed_route="ignore"),
        ]
        network = AsyncMock(side_effect=AssertionError("固定案例不得请求模型"))
        store = MemoryStore(self.path)
        with patch("mini_pi.async_http_transport.post_json_async", network):
            routed = route_candidates(self.scope, candidates)
            self.assertEqual(routed["long_term"], (self.candidate,))
            for route in ("task_constraint", "needs_review", "ignore"):
                self.assertEqual(len(routed[route]), 1)
            self.assertEqual(routed["withdrawal"], ())
            self.assertFalse(self.path.parent.exists())
            candidate = routed["long_term"][0]
            draft = draft_from_candidate(self.scope, candidate, **self.fields)
            self.assertFalse(self.path.parent.exists())
            plan = plan_remember_or_retry(store, self.scope, candidate.source, draft)
            self.assertIsInstance(plan, RememberPlan)
            self.assertFalse(self.path.parent.exists())
            saved, = execute_plans(store, self.scope, [plan])
            self.assertTrue(self.path.exists())
            self.assertEqual((saved.version, saved.source, saved.text),
                             (1, self.source, candidate.content))
            self.assertEqual(MemoryStore(self.path).get(self.scope, saved.memory_id), saved)
            before = self.path.read_bytes()
            with patch.object(store._backend, "transaction", side_effect=AssertionError("同候选重试不得新写入")) as write:
                retry = plan_remember_or_retry(store, self.scope, candidate.source, draft)
                self.assertIsInstance(retry, MemoryEntry)
                returned, = execute_plans(store, self.scope, [retry])
                self.assertIs(returned, retry)
                self.assertEqual(returned, saved)
                write.assert_not_called()
            self.assertEqual(self.path.read_bytes(), before)
            network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
