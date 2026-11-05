"""D21第二任务的真实入口集成测试，服务响应由假百炼提供。"""

import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from evals.d21_live import prepare_pilot, run_live_pilot
from tests.test_d21_live import FakeBailian, assert_logs_do_not_contain_key, write_test_auth


FREE_FORM_SUMMARY = "发布记录批准值为qa-east-7。Update the channel in app.conf and preserve the remaining lines."
MISSING_VALUE_REPLY = "重读后仍缺少批准值，保留原配置。"
APPROVED_VALUE = "qa-east-7"
INITIAL = "name=mini-pi\nchannel=preview\nretries=2\n"


class FakeTask2Bailian:
    def __init__(self, summary):
        self.summary = summary

    async def __call__(self, url, key, payload, timeout):
        feedback = {message["tool_call_id"]: message["content"] for message in payload["messages"]
                    if message["role"] == "tool"}
        tool_message = FakeBailian.tool_message
        if not payload.get("tools"):
            message = {"role": "assistant", "content": self.summary}
        elif "task2-live-verify" in feedback:
            verified = json.loads(feedback["task2-live-verify"])
            reply = "已复核配置。\n" + verified["output"] if verified["error"] is None else "复核读取失败。"
            message = {"role": "assistant", "content": reply}
        elif "task2-live-edit" in feedback:
            message = tool_message("task2-live-verify", "read_file", {"path": "app.conf"})
        elif "task2-live-read" not in feedback:
            message = tool_message("task2-live-read", "read_file", {"path": "app.conf"})
        else:
            text = "\n".join(message.get("content") or "" for message in payload["messages"])
            channel = re.search(r"(?<![a-z0-9-])qa-east-[0-9]+(?![a-z0-9-])", text)
            if channel:
                message = tool_message("task2-live-edit", "edit_file", {
                    "path": "app.conf", "old_text": "channel=preview", "new_text": "channel=" + channel[0],
                })
            elif "task2-live-reread" not in feedback:
                message = tool_message("task2-live-reread", "read_file", {"path": "release-notes.txt"})
            else:
                message = {"role": "assistant", "content": MISSING_VALUE_REPLY}
        return {
            "model": payload["model"],
            "choices": [{"message": message, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105},
        }


class D21Task2LiveTests(unittest.IsolatedAsyncioTestCase):
    async def run_fake_pilot(self, summary):
        temp = TemporaryDirectory(prefix="d21-task2-live-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        directory = root / "pilot"
        auth = write_test_auth(root)
        fake = FakeTask2Bailian(summary)
        with patch("mini_pi.qwen_client.post_json_async", new_callable=AsyncMock, side_effect=fake.__call__) as post:
            protocol = prepare_pilot(directory, auth, task="config-tail")
            post.assert_not_awaited()
            report = await run_live_pilot(directory)
        assert_logs_do_not_contain_key(self, directory)
        return protocol, report, post.await_count

    async def test_free_form_summary_retains_value_and_reread_cannot_recover_clipped_value(self):
        protocol, report, sends = await self.run_fake_pilot(FREE_FORM_SUMMARY)
        plan = protocol["plan"]
        self.assertEqual(protocol["case"]["id"], "d21-config-tail-2")
        self.assertEqual(plan["answer_requests_per_variant"], 4)
        self.assertEqual(plan["summary_requests_in_C"], 1)
        self.assertEqual(plan["max_total_requests"], 13)
        self.assertEqual(sends, 12)
        self.assertEqual(report["real_model_requests"], sends)
        self.assertEqual(report["usage"]["total_tokens"], sends * 105)
        self.assertTrue(report["pilot_observations_complete"])
        self.assertFalse(report["all_tasks_passed"])

        a, b, c = (report["groups"][name] for name in ("A", "B", "C"))
        expected = INITIAL.replace("preview", APPROVED_VALUE)
        for group in (a, c):
            self.assertEqual(group["run_status"], "finished")
            self.assertEqual(group["case_verdict"], "passed")
            self.assertEqual((Path(group["workspace"]) / "app.conf").read_bytes(), expected.encode("utf-8"))
            self.assertIn(APPROVED_VALUE, group["final_reply"])
            self.assertTrue(group["first_answer_has_approved_value"])
        self.assertEqual(b["run_status"], "finished")
        self.assertEqual(b["case_verdict"], "failed")
        self.assertEqual((Path(b["workspace"]) / "app.conf").read_bytes(), INITIAL.encode("utf-8"))
        self.assertEqual([row["tool_name"] for row in b["tool_results"]], ["read_file", "read_file"])
        self.assertEqual(b["final_reply"], MISSING_VALUE_REPLY)
        self.assertFalse(b["first_answer_has_approved_value"])
        self.assertEqual(c["summary_text"], FREE_FORM_SUMMARY)
        self.assertTrue(c["summary_has_approved_value"])
        self.assertTrue(c["summary_source_has_full_read"])
        for group in (a, b):
            self.assertIsNone(group["summary_text"])
            self.assertIsNone(group["summary_has_approved_value"])
            self.assertIsNone(group["summary_source_has_full_read"])

    async def test_longer_wrong_value_does_not_count_as_approved_value(self):
        wrong_value = "qa-east-70"
        wrong_summary = FREE_FORM_SUMMARY.replace(APPROVED_VALUE, wrong_value)
        _, report, sends = await self.run_fake_pilot(wrong_summary)
        c = report["groups"]["C"]
        self.assertEqual(sends, 12)
        self.assertEqual(c["run_status"], "finished")
        self.assertEqual(c["summary_text"], wrong_summary)
        self.assertTrue(c["summary_source_has_full_read"])
        self.assertFalse(c["summary_has_approved_value"])
        self.assertFalse(c["first_answer_has_approved_value"])
        self.assertIn(wrong_value, c["final_reply"])
        self.assertEqual(c["case_verdict"], "failed")
        self.assertEqual(c["actual_content"], INITIAL.replace("preview", wrong_value))


if __name__ == "__main__":
    unittest.main()
