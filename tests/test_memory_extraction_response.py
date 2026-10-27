"""非流式提取响应的格式/终态门禁；全部合成，不证明真实提取效果。"""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
import json
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.extraction import parse_extraction_response
from mini_pi.memory.models import MemoryScope, MemorySource


class ExtractionResponseTests(unittest.TestCase):
    def setUp(self):
        self.scope = MemoryScope("response-user", "mini-pi")
        self.source = MemorySource(
            "response-source", self.scope, "user",
            "以后请尽量用 Python 举例。今天只解释，不改文件。",
            "2026-10-23T10:00:00+08:00",
        )
        first = {"content": "  用户希望后续尽量使用 Python 示例。\n",
                 "proposed_route": "long_term", "reason": "固定案例的长期建议。"}
        self.items = [first, {"content": "本题只解释，不改文件。",
                             "proposed_route": "task_constraint", "reason": "本次任务限制。"}, first]
        self.response = {"id": "synthetic-response", "error": None, "choices": [{
            "finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(self.items, ensure_ascii=False),
            },
        }]}

    def with_content(self, content):
        response = deepcopy(self.response)
        response["choices"][0]["message"]["content"] = content
        return response

    @contextmanager
    def no_external_calls(self):
        network = AsyncMock(side_effect=AssertionError("响应解析不得请求模型"))
        with (patch("sqlite3.connect", side_effect=AssertionError("响应解析不得开库")) as connect,
              patch("mini_pi.async_http_transport.post_json_async", network),
              patch("mini_pi.memory.store.MemoryStore.remember") as remember,
              patch("mini_pi.memory.store.MemoryStore.replace") as update,
              patch("mini_pi.memory.store.MemoryStore.retract") as retract):
            yield
            for call in (connect, network, remember, update, retract):
                call.assert_not_called()

    def test_stop_response_preserves_candidates_source_order_and_all_inputs(self):
        before = (asdict(self.scope), asdict(self.source), deepcopy(self.response))
        with self.no_external_calls():
            parsed = parse_extraction_response(self.scope, self.source, self.response)
        self.assertIsInstance(parsed, tuple)
        self.assertEqual([(item.content, item.proposed_route, item.reason) for item in parsed],
                         [(item["content"], item["proposed_route"], item["reason"]) for item in self.items])
        self.assertNotIn(parsed[0].content, self.source.text)
        self.assertTrue(all(item.source is self.source for item in parsed))
        self.assertEqual((asdict(self.scope), asdict(self.source), self.response), before)

    def test_empty_json_array_is_valid_but_source_admission_is_still_required(self):
        response = self.with_content("[]")
        cases = [(None, self.source),
                 (self.scope, replace(self.source, scope=MemoryScope("other-user", self.scope.project_id))),
                 (self.scope, replace(self.source, role="assistant"))]
        with self.no_external_calls():
            self.assertEqual(parse_extraction_response(self.scope, self.source, response), ())
            for scope, source in cases:
                with self.subTest(scope=scope, source=source):
                    with self.assertRaises(MemoryPolicyError):
                        parse_extraction_response(scope, source, response)

    def test_nonstop_or_nonassistant_response_rejects_before_candidate_parsing(self):
        responses = []
        for finish in (None, "length", "tool_calls", "function_call", "content_filter", "unknown"):
            response = self.with_content("[]")
            response["choices"][0]["finish_reason"] = finish
            responses.append(response)
        for role in (None, "user", "tool", "assistant "):
            response = self.with_content("[]")
            response["choices"][0]["message"]["role"] = role
            responses.append(response)
        with (self.no_external_calls(),
              patch("mini_pi.memory.extraction.parse_candidate_items",
                    side_effect=AssertionError("不合格终态不得解析候选")) as downstream):
            for response in responses:
                with self.subTest(response=response):
                    with self.assertRaises(MemoryPolicyError):
                        parse_extraction_response(self.scope, self.source, response)
            downstream.assert_not_called()

    def test_invalid_envelope_error_choices_message_or_content_is_rejected(self):
        responses = [None, [], {}]
        choice = self.response["choices"][0]
        for choices in (None, [], [choice, deepcopy(choice)], [None], [{}], (choice,)):
            responses.append({**self.response, "choices": choices})
        for error in ({}, False, "synthetic service error"):
            responses.append({**self.response, "error": error})
        for message in (None, [], {}):
            responses.append({**self.response, "choices": [{"finish_reason": "stop", "message": message}]})
        responses.extend(self.with_content(value) for value in ("", " \n", None, 42, {}))
        with (self.no_external_calls(),
              patch("mini_pi.memory.extraction.parse_candidate_items",
                    side_effect=AssertionError("坏外壳不得进入候选解析")) as downstream):
            for response in responses:
                with self.subTest(response=response):
                    with self.assertRaises(MemoryPolicyError):
                        parse_extraction_response(self.scope, self.source, response)
            downstream.assert_not_called()

    def test_tool_function_and_refusal_fields_allow_only_the_declared_empty_forms(self):
        allowed = ({}, {"tool_calls": None, "function_call": None, "refusal": None},
                   {"tool_calls": [], "refusal": ""})
        rejected = (("tool_calls", [{"id": "synthetic-call"}]), ("tool_calls", {}), ("tool_calls", False),
                    ("function_call", {}), ("function_call", False),
                    ("refusal", "synthetic refusal"), ("refusal", False), ("refusal", []))
        with self.no_external_calls():
            for fields in allowed:
                with self.subTest(allowed=fields):
                    response = self.with_content("[]")
                    response["choices"][0]["message"].update(fields)
                    self.assertEqual(parse_extraction_response(self.scope, self.source, response), ())
            with patch("mini_pi.memory.extraction.parse_candidate_items",
                       side_effect=AssertionError("工具或拒答响应不得解析候选")) as downstream:
                for field, value in rejected:
                    with self.subTest(field=field, value=value):
                        response = self.with_content("[]")
                        response["choices"][0]["message"][field] = value
                        with self.assertRaises(MemoryPolicyError):
                            parse_extraction_response(self.scope, self.source, response)
                downstream.assert_not_called()

    def test_malformed_nonstandard_json_fences_extra_text_and_recursion_are_rejected(self):
        duplicate = '[{"content":"first","content":"second","proposed_route":"long_term","reason":"r"}]'
        bodies = ["{", "```json\n[]\n```", "[] trailing text", duplicate]
        bodies.extend('[{"content":"text","proposed_route":"long_term","reason":' + value + '}]'
                      for value in ("NaN", "Infinity", "-Infinity"))
        with (self.no_external_calls(),
              patch("mini_pi.memory.extraction.parse_candidate_items",
                    side_effect=AssertionError("无效JSON不得进入候选解析")) as downstream):
            for index, body in enumerate(bodies):
                with self.subTest(case=index):
                    with self.assertRaises(MemoryPolicyError):
                        parse_extraction_response(self.scope, self.source, self.with_content(body))
            # Python版本的JSON解码深度不同；直接注入解码器异常来验错误传播契约。
            failure = RecursionError("controlled decoder depth failure")
            with patch("mini_pi.memory.extraction.json.loads", side_effect=failure):
                with self.assertRaises(MemoryPolicyError) as caught:
                    parse_extraction_response(self.scope, self.source, self.with_content("[]"))
            self.assertIs(caught.exception.__cause__, failure)
            downstream.assert_not_called()

    def test_downstream_policy_validation_and_failure_identity_are_preserved(self):
        bad_payloads = [
            [{**self.items[0], "proposed_route": "unknown"}],
            [{**self.items[0], "scope": {"user_id": "model-identity"}}],
            [self.items[0], {**self.items[0], "reason": None}],
            {"candidates": []},
            [[0]],
        ]
        with self.no_external_calls():
            for payload in bad_payloads:
                with self.subTest(payload=payload):
                    with self.assertRaises(MemoryPolicyError):
                        parse_extraction_response(self.scope, self.source,
                                                  self.with_content(json.dumps(payload, ensure_ascii=False)))
            foreign = replace(self.source, scope=MemoryScope(self.scope.user_id, "other-project"))
            with self.assertRaises(MemoryPolicyError):
                parse_extraction_response(self.scope, foreign, self.response)
            failure = MemoryPolicyError("controlled downstream failure")
            with patch("mini_pi.memory.extraction.parse_candidate_items", side_effect=failure) as downstream:
                with self.assertRaises(MemoryPolicyError) as caught:
                    parse_extraction_response(self.scope, self.source, self.response)
                self.assertIs(caught.exception, failure)
                downstream.assert_called_once_with(self.scope, self.source, self.items)


if __name__ == "__main__":
    unittest.main()
