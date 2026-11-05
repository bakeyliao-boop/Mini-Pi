"""D21真实入口的离线HTTP测试：仅临时测试凭证与合成服务响应。"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from evals.d21_live import prepare_pilot, run_live_pilot


TEST_KEY = "sk-offline-test-key"
TEST_SUMMARY = (
    "待办：只修改 edit-test.txt，把 world 改成 testing，保留其余字符和标点；"
    "不新增或删除文件。过程记录已读，目标文件尚未修改。"
)


class FakeBailian:
    """根据实际发来的工具反馈推进合成响应，不访问任何网络服务。"""

    def __init__(self, *, missing_usage=False, fail_first=False):
        self.missing_usage = missing_usage
        self.fail_first = fail_first
        self.calls = []

    async def __call__(self, url, key, payload, timeout):
        self.calls.append({"payload": deepcopy(payload), "timeout": timeout})
        if self.fail_first:
            raise OSError("synthetic transport failure")
        seen = {item.get("tool_call_id") for item in payload["messages"] if item["role"] == "tool"}
        if not payload.get("tools"):
            message = {"role": "assistant", "content": TEST_SUMMARY}
            reason = "stop"
        elif "fake-live-edit" in seen:
            message = {"role": "assistant", "content": "修改已完成，工具反馈成功。"}
            reason = "stop"
        elif "fake-live-read" in seen:
            message = self.tool_message("fake-live-edit", "edit_file", {
                "path": "edit-test.txt", "old_text": "world", "new_text": "testing",
            })
            reason = "tool_calls"
        else:
            message = self.tool_message("fake-live-read", "read_file", {"path": "edit-test.txt"})
            reason = "tool_calls"
        usage = None if self.missing_usage else {
            "prompt_tokens": 100 + len(self.calls), "completion_tokens": 5,
            "total_tokens": 105 + len(self.calls),
        }
        return {"model": payload["model"], "choices": [{"message": message, "finish_reason": reason}], "usage": usage}

    @staticmethod
    def tool_message(call_id, name, arguments):
        return {"role": "assistant", "content": "", "tool_calls": [{
            "id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }]}


def write_test_auth(directory):
    path = Path(directory) / "synthetic-auth.json"
    path.write_text(json.dumps({"bailian": {"type": "api_key", "key": TEST_KEY}}), encoding="utf-8")
    return path


def assert_logs_do_not_contain_key(test, directory):
    for path in Path(directory).rglob("*"):
        if path.is_file():
            test.assertNotIn(TEST_KEY.encode("utf-8"), path.read_bytes(), str(path))


class D21LivePilotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="d21-live-adapter-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.auth_file = write_test_auth(self.root)
        self.directory = self.root / "pilot"

    def prepare(self):
        return prepare_pilot(self.directory, self.auth_file)

    async def test_prepare_freezes_initial_files_without_http_or_credentials_in_logs(self):
        with patch("mini_pi.qwen_client.post_json_async", new_callable=AsyncMock) as post:
            protocol = self.prepare()
        post.assert_not_awaited()
        self.assertEqual(protocol["real_model_requests"], 0)
        self.assertEqual(protocol["plan"]["max_total_requests"], 10)
        self.assertEqual((Path(protocol["case"]["initial_directory"]) / "edit-test.txt").read_bytes(), b"Hello, world!")
        self.assertEqual(json.loads((self.directory / "state.json").read_text(encoding="utf-8"))["state"], "prepared")
        assert_logs_do_not_contain_key(self, self.directory)

    async def test_bounded_three_variants_include_summary_usage_and_cannot_rerun(self):
        protocol = self.prepare()
        fake = FakeBailian()
        with patch("mini_pi.qwen_client.post_json_async", new_callable=AsyncMock, side_effect=fake.__call__) as post:
            report = await run_live_pilot(self.directory)
            self.assertEqual(post.await_count, 10)
            with self.assertRaisesRegex(ValueError, "禁止自动重跑"):
                await run_live_pilot(self.directory)
            self.assertEqual(post.await_count, 10)
        self.assertTrue(report["cohort_complete"])
        self.assertTrue(report["telemetry_complete"])
        self.assertTrue(report["pilot_observations_complete"])
        self.assertTrue(report["all_tasks_passed"])
        self.assertFalse(report["effectiveness_verified"])
        self.assertEqual(report["real_model_requests"], protocol["plan"]["max_total_requests"])
        self.assertEqual([report["groups"][name]["real_model_requests"] for name in ("A", "B", "C")], [3, 3, 4])
        self.assertEqual(len(report["groups"]["C"]["provider_requests"]["summary"]), 1)
        records = [record for group in report["groups"].values()
                   for phase in ("answer", "summary") for record in group["provider_requests"][phase]]
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self.assertEqual(report["usage"][field], sum(record["usage"][field] for record in records))
            self.assertEqual(report["actual_usage"][field], report["usage"][field])
        for call in fake.calls:
            self.assertEqual(call["payload"]["model"], protocol["plan"]["model"])
            self.assertEqual(call["payload"]["max_completion_tokens"], protocol["plan"]["max_completion_tokens"])
            self.assertFalse(call["payload"]["enable_thinking"])
        for group in report["groups"].values():
            self.assertEqual(group["actual_content"], "Hello, testing!")
            self.assertEqual(group["case_verdict"], "passed")
        assert_logs_do_not_contain_key(self, self.directory)

    async def test_unverified_file_acceptance_keeps_pilot_observations_incomplete(self):
        self.prepare()
        fake = FakeBailian()
        with patch("mini_pi.qwen_client.post_json_async", new_callable=AsyncMock, side_effect=fake.__call__), \
             patch("evals.d21_acceptance.subprocess.run", side_effect=FileNotFoundError("git unavailable")):
            report = await run_live_pilot(self.directory)
        self.assertTrue(report["cohort_complete"])
        self.assertTrue(report["telemetry_complete"])
        self.assertFalse(report["task_scores_available"])
        self.assertFalse(report["pilot_observations_complete"])
        self.assertTrue(all(item["case_verdict"] == "unverified" for item in report["groups"].values()))

    async def test_transport_failure_stops_remaining_variants_without_retry(self):
        self.prepare()
        fake = FakeBailian(fail_first=True)
        with patch("mini_pi.qwen_client.post_json_async", new_callable=AsyncMock, side_effect=fake.__call__) as post:
            report = await run_live_pilot(self.directory)
        post.assert_awaited_once()
        self.assertEqual(report["real_model_requests"], 1)
        self.assertFalse(report["cohort_complete"])
        self.assertFalse(report["telemetry_complete"])
        self.assertIsNone(report["actual_usage"])
        for name in ("B", "C"):
            self.assertEqual(report["groups"][name]["execution_status"], "not_started")
            self.assertEqual(report["groups"][name]["case_verdict"], "unverified")
        self.assertIsNone(report["usage"]["total_tokens"])
        assert_logs_do_not_contain_key(self, self.directory)

    async def test_long_character_shape_stays_below_C_recompaction_trigger(self):
        protocol = self.prepare()

        class LongShapeBailian(FakeBailian):
            async def __call__(self, url, key, payload, timeout):
                data = await super().__call__(url, key, payload, timeout)
                message = data["choices"][0]["message"]
                # 仅构造1024字符的响应形状；不是供应商256 tokens能产生字符数的硬上限证明。
                content = message["content"]
                message["content"] = content + "x" * (1024 - len(content))
                return data

        fake = LongShapeBailian()
        with patch("mini_pi.qwen_client.post_json_async", new_callable=AsyncMock, side_effect=fake.__call__) as post:
            report = await run_live_pilot(self.directory)
        self.assertEqual(post.await_count, 10)
        self.assertTrue(report["all_tasks_passed"])
        c = report["groups"]["C"]
        self.assertEqual(c["run_status"], "finished")
        self.assertEqual(c["case_verdict"], "passed")
        self.assertEqual(c["compaction_records"], 1)
        self.assertEqual(len(c["provider_requests"]["summary"]), 1)
        self.assertEqual(len(c["provider_requests"]["answer"]), 3)
        self.assertEqual(len(c["answer_input_estimated_tokens"]), 3)
        self.assertTrue(all(value < protocol["plan"]["compaction_trigger_tokens"]
                            for value in c["answer_input_estimated_tokens"]), c["answer_input_estimated_tokens"])
        assert_logs_do_not_contain_key(self, self.directory)

    async def test_missing_service_usage_remains_unknown_without_extra_requests(self):
        self.prepare()
        fake = FakeBailian(missing_usage=True)
        with patch("mini_pi.qwen_client.post_json_async", new_callable=AsyncMock, side_effect=fake.__call__) as post:
            report = await run_live_pilot(self.directory)
        self.assertEqual(post.await_count, 10)
        self.assertEqual(report["real_model_requests"], 10)
        self.assertTrue(report["cohort_complete"])
        self.assertTrue(report["all_tasks_passed"])
        self.assertFalse(report["telemetry_complete"])
        self.assertFalse(report["pilot_observations_complete"])
        self.assertIsNone(report["actual_usage"])
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self.assertIsNone(report["usage"][field])
            self.assertIsNone(report["usage"]["known_subtotals"][field])
        assert_logs_do_not_contain_key(self, self.directory)

    async def test_already_started_directory_cannot_send_a_first_new_request(self):
        self.prepare()
        (self.directory / "state.json").write_text(json.dumps({"state": "started", "real_model_requests": 1}), encoding="utf-8")
        with patch("mini_pi.qwen_client.post_json_async", new_callable=AsyncMock) as post:
            with self.assertRaisesRegex(ValueError, "禁止自动重跑"):
                await run_live_pilot(self.directory)
        post.assert_not_awaited()

    async def test_transport_exception_cannot_write_fixture_key_into_logs(self):
        self.prepare()

        async def fail_with_fixture_key(url, key, payload, timeout):
            raise OSError("synthetic failure with credential " + TEST_KEY)

        with patch("mini_pi.qwen_client.post_json_async", new_callable=AsyncMock, side_effect=fail_with_fixture_key) as post:
            report = await run_live_pilot(self.directory)
        post.assert_awaited_once()
        self.assertEqual(report["real_model_requests"], 1)
        self.assertIn("[REDACTED]", report["groups"]["A"]["exception"]["message"])
        assert_logs_do_not_contain_key(self, self.directory)

    async def test_cancellation_cleans_current_request_and_does_not_start_later_groups(self):
        self.prepare()
        entered = asyncio.Event()
        cleaned = asyncio.Event()

        async def wait_for_cancellation(url, key, payload, timeout):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        with patch("mini_pi.qwen_client.post_json_async", new_callable=AsyncMock, side_effect=wait_for_cancellation) as post:
            task = asyncio.create_task(run_live_pilot(self.directory))
            try:
                async with asyncio.timeout(3):
                    await entered.wait()
                    task.cancel()
                    report = await task
            finally:
                if not task.done():
                    task.cancel()
                    await task
        self.assertTrue(cleaned.is_set())
        post.assert_awaited_once()
        self.assertEqual(report["real_model_requests"], 1)
        self.assertEqual(report["groups"]["A"]["run_status"], "cancelled")
        for name in ("B", "C"):
            self.assertEqual(report["groups"][name]["execution_status"], "not_started")
        assert_logs_do_not_contain_key(self, self.directory)


if __name__ == "__main__":
    unittest.main()
