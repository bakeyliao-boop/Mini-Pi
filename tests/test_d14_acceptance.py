"""验收器需正确识别真实API的嵌套工具反馈，且不能误认其他消息。"""

import json
import unittest

from examples.d14_acceptance import request_contains_passing_test_feedback


class D14EvidenceTests(unittest.TestCase):
    def record(self, call_id="tests", outcome="tests_passed", exit_code=0, error=None):
        content = json.dumps({"output": json.dumps({"outcome": outcome, "exit_code": exit_code}), "error": error})
        return [{"request_body": {"messages": [{"role": "tool", "tool_call_id": call_id, "content": content}]}}]

    def test_nested_escaped_json_is_seen_in_request(self):
        self.assertTrue(request_contains_passing_test_feedback(self.record(), {"tests"}))

    def test_other_tool_id_or_assistant_claim_is_not_test_feedback(self):
        self.assertFalse(request_contains_passing_test_feedback(self.record(call_id="read"), {"tests"}))
        records = self.record()
        records[0]["request_body"]["messages"][0]["role"] = "assistant"
        self.assertFalse(request_contains_passing_test_feedback(records, {"tests"}))

    def test_failed_or_errored_feedback_is_not_passing(self):
        for records in (self.record(outcome="tests_failed", exit_code=1), self.record(exit_code=1), self.record(error="工具失败")):
            self.assertFalse(request_contains_passing_test_feedback(records, {"tests"}))

    def test_malformed_or_missing_feedback_is_not_seen(self):
        self.assertFalse(request_contains_passing_test_feedback([], {"tests"}))
        for content in ("bad-json", "[]", '{"output":"bad-json","error":null}', '{"output":"[]","error":null}'):
            records = self.record()
            records[0]["request_body"]["messages"][0]["content"] = content
            self.assertFalse(request_contains_passing_test_feedback(records, {"tests"}))
