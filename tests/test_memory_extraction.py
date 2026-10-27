"""解码后条目绑定可信来源；只验格式/来源，不证明正文语义或授予写权限。

固定条目不是模型提取效果证据。否定、强度、条件等保真另用标注集评测，
这里不实现通用语义核验器，也不处理 JSON 字符串、HTTP 或模型终态。
"""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.extraction import parse_candidate_items
from mini_pi.memory.models import MemoryScope, MemorySource
from mini_pi.memory.selection import MemoryCandidate, route_candidates


class CandidateExtractionTests(unittest.TestCase):
    def setUp(self):
        self.scope = MemoryScope("extraction-user", "mini-pi")
        self.source = MemorySource(
            "extraction-current-source", self.scope, "user",
            "以后讲解请尽量用 Python 举例。今天这题只解释，不改文件。"
            "我猜测试应该通过了。请撤回旧输出格式偏好。谢谢。",
            "2026-10-23T10:00:00+08:00",
        )
        self.item = {
            "content": "  用户希望后续讲解尽量使用 Python 示例。\n",
            "proposed_route": "long_term",
            "reason": "固定案例中有明确的后续讲解偏好，尚须后续核对。",
        }

    @contextmanager
    def no_external_calls(self):
        network = AsyncMock(side_effect=AssertionError("解析已解码条目不得请求模型"))
        with (patch("sqlite3.connect", side_effect=AssertionError("候选解析不得开库")) as connect,
              patch("mini_pi.async_http_transport.post_json_async", network)):
            yield
            connect.assert_not_called()
            network.assert_not_called()

    def test_normalized_text_order_and_duplicates_keep_same_complete_source_without_io(self):
        task = {"content": "本题只解释，不修改文件。", "proposed_route": "task_constraint",
                "reason": "本次任务限制。"}
        raw_items = [self.item, task, self.item]
        before = (asdict(self.scope), asdict(self.source), deepcopy(raw_items))
        with self.no_external_calls():
            parsed = parse_candidate_items(self.scope, self.source, raw_items)
        self.assertIsInstance(parsed, tuple)
        self.assertEqual(len(parsed), 3)
        self.assertTrue(all(isinstance(candidate, MemoryCandidate) for candidate in parsed))
        self.assertEqual([(candidate.content, candidate.proposed_route, candidate.reason) for candidate in parsed],
                         [(item["content"], item["proposed_route"], item["reason"]) for item in raw_items])
        self.assertNotIn(parsed[0].content, self.source.text)
        for candidate in parsed:
            self.assertIs(candidate.source, self.source)
            self.assertEqual(candidate.source.recorded_at, "2026-10-23T10:00:00+08:00")
        self.assertEqual((asdict(self.scope), asdict(self.source), raw_items), before)
        original_content = parsed[0].content
        raw_items[0]["content"] = "调用后更改原字典。"
        self.assertEqual((parsed[0].content, parsed[2].content), (original_content, original_content))

    def test_empty_list_is_valid_but_never_bypasses_scope_source_or_role_admission(self):
        cases = [
            (None, self.source), ({}, self.source), (replace(self.scope, user_id=""), self.source),
            (self.scope, None), (self.scope, {}),
            (self.scope, replace(self.source, scope=None)),
            (self.scope, replace(self.source, source_id=" ")),
            (self.scope, replace(self.source, text=" \n")),
            (self.scope, replace(self.source, recorded_at="2026-10-23T10:00:00")),
            (self.scope, replace(self.source, scope=MemoryScope("other-user", self.scope.project_id))),
            (self.scope, replace(self.source, role="assistant")),
        ]
        with self.no_external_calls():
            self.assertEqual(parse_candidate_items(self.scope, self.source, []), ())
            for scope, source in cases:
                with self.subTest(scope=scope, source=source):
                    with self.assertRaises(MemoryPolicyError):
                        parse_candidate_items(scope, source, [])

    def test_nonlist_rows_missing_or_extra_fields_and_model_identity_fields_are_rejected(self):
        batches = [None, (), {}, "[]", iter([self.item]), [None], [[]], ["item"]]
        batches.extend([{key: value for key, value in self.item.items() if key != field}]
                       for field in ("content", "proposed_route", "reason"))
        batches.extend([{**self.item, key: value}] for key, value in (
            ("extra", "unexpected"), ("source_id", "model-declared-source"),
            ("source", {"source_id": "model-declared-source"}),
            ("scope", {"user_id": "other-user", "project_id": "other-project"}),
        ))
        with self.no_external_calls():
            for batch in batches:
                with self.subTest(batch=batch):
                    with self.assertRaises(MemoryPolicyError):
                        parse_candidate_items(self.scope, self.source, batch)

    def test_invalid_scalar_or_unknown_route_in_later_item_rejects_the_whole_batch(self):
        changes = [
            {"content": None}, {"content": " \n"}, {"content": False}, {"content": []},
            {"reason": ""}, {"reason": None}, {"reason": {}},
            {"proposed_route": "unknown"}, {"proposed_route": None}, {"proposed_route": []},
        ]
        with self.no_external_calls():
            for change in changes:
                with self.subTest(change=change):
                    raw_items = [dict(self.item), {**self.item, **change}]
                    before = deepcopy(raw_items)
                    with self.assertRaises(MemoryPolicyError):
                        parse_candidate_items(self.scope, self.source, raw_items)
                    self.assertEqual(raw_items, before)

    def test_source_scope_and_role_gate_rejects_foreign_or_disallowed_sources_and_accepts_tool(self):
        sources = [
            replace(self.source, scope=MemoryScope("other-user", self.scope.project_id)),
            replace(self.source, scope=MemoryScope(self.scope.user_id, "other-project")),
        ]
        sources.extend(replace(self.source, role=role) for role in ("assistant", "system", "developer", "user "))
        tool = replace(self.source, role="tool", source_id="synthetic-tool-source",
                       text='{"tool_call_id":"synthetic-call","output":"2 passed","error":null}')
        observed = {"content": "合成工具案例观察到2项测试通过。", "proposed_route": "needs_review",
                    "reason": "本例仅解析工具观察候选，项目依据与用途尚待核对。"}
        with self.no_external_calls():
            for source in sources:
                with self.subTest(source=source):
                    with self.assertRaises(MemoryPolicyError):
                        parse_candidate_items(self.scope, source, [self.item])
            parsed, = parse_candidate_items(self.scope, tool, [observed])
            self.assertIs(parsed.source, tool)
            self.assertEqual(parsed.source.text, tool.text)

    def test_five_route_suggestions_bind_source_and_group_without_authorizing_writes(self):
        """归组只保留建议；结构和来源合格不表示语义支持或允许写入。"""
        raw_items = [
            dict(self.item),
            {"content": "本题只解释，不修改文件。", "proposed_route": "task_constraint", "reason": "当前任务限制。"},
            {"content": "礼貌致谢。", "proposed_route": "ignore", "reason": "无长期内容。"},
            {"content": "测试通过尚属猜测。", "proposed_route": "needs_review", "reason": "没有工具实证。"},
            {"content": "撤回旧输出格式偏好。", "proposed_route": "withdrawal", "reason": "仅建议，待独立控制流程。"},
        ]
        before = (asdict(self.source), deepcopy(raw_items))
        with (self.no_external_calls(),
              patch("mini_pi.memory.store.MemoryStore.remember") as remember,
              patch("mini_pi.memory.store.MemoryStore.replace") as update,
              patch("mini_pi.memory.store.MemoryStore.retract") as retract):
            parsed = parse_candidate_items(self.scope, self.source, raw_items)
            routed = route_candidates(self.scope, parsed)
            for candidate in parsed:
                self.assertEqual(routed[candidate.proposed_route], (candidate,))
                self.assertIs(candidate.source, self.source)
            remember.assert_not_called()
            update.assert_not_called()
            retract.assert_not_called()
        self.assertEqual(set(routed), {"long_term", "task_constraint", "ignore", "needs_review", "withdrawal"})
        self.assertEqual((asdict(self.source), raw_items), before)


if __name__ == "__main__":
    unittest.main()
