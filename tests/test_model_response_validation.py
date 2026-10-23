"""D13-A 复盘反例：外部响应格式错误须在进入循环前规范为模型错误。

仅替换 HTTP 输入。观察真实临时文件、工具调用、JSONL 和调用方结果；
内部断言异常作为独立对照，避免后续用无差别 except Exception 掩盖程序问题。
"""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.loop import run_loop
from mini_pi.models import Message
from mini_pi.qwen_client import QwenProvider
from mini_pi.session_store import SessionStore
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy


class ModelResponseValidationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_response_format_", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / "sample.py"
        self.target.write_bytes(b"value = 1\n")
        self.editor = EditFileExecutor(EditPolicy(self.root, ["sample.py"]))
        self.store = SessionStore(self.root / "session.jsonl")
        self.provider = QwenProvider(api_key="synthetic-test-placeholder")
        self.observation = {}

    def normal(self):
        return {"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "正常回答。",
        }}]}

    async def observe(self, first_response):
        self.result = None
        self.raised = None
        with patch("mini_pi.qwen_client.post_json_async", side_effect=[first_response, self.normal()]) as send, patch.object(
            self.editor, "execute", wraps=self.editor.execute,
        ) as execute:
            try:
                self.result = await run_loop(
                    self.provider, self.editor, [Message("user", "检查本次响应。")],
                    [self.editor.definition], self.store,
                )
            except Exception as error:
                self.raised = error
            self.executed = [item.args[0].id for item in execute.await_args_list]
            self.requests = send.await_count
        self.records = [json.loads(line) for line in self.store.path.read_text(encoding="utf-8").splitlines()]
        self.loaded = None
        self.load_error = None
        try:
            self.loaded = self.store.load()
        except Exception as error:
            self.load_error = error
        self.ends = [row["data"]["status"] for row in self.records if row["type"] == "run_end"]
        self.observation = {
            "returned_status": self.result.status if self.result else None,
            "uncaught_exception_type": type(self.raised).__name__ if self.raised else None,
            "run_end_statuses": self.ends, "model_requests": self.requests,
            "executed_call_ids": self.executed,
            "file_changed": self.target.read_bytes() != b"value = 1\n",
            "saved_history_loadable": self.loaded is not None,
            "load_error": str(self.load_error) if self.load_error else None,
        }

    async def assert_format_error(self, response):
        await self.observe(response)
        self.observation["expected_status"] = "error"
        self.assertIsNone(self.raised, f"外部响应格式错误应转成 error 消息，当前抛出 {self.raised!r}")
        self.assertIsNotNone(self.result)
        self.assertEqual(self.result.status, "error")
        self.assertTrue(self.result.error)
        self.assertEqual(self.ends, ["error"])
        self.assertEqual(self.requests, 1)
        self.assertEqual(self.executed, [])
        self.assertEqual(self.target.read_bytes(), b"value = 1\n")
        self.assertIsNone(self.load_error, "不能先把损坏消息写入历史")
        self.assertEqual(self.loaded.history, self.result.messages)

    async def test_missing_choices_is_recorded_as_model_error(self):
        await self.assert_format_error({})

    async def test_empty_choices_is_recorded_as_model_error(self):
        await self.assert_format_error({"choices": []})

    async def test_non_assistant_response_is_recorded_as_model_error(self):
        response = self.normal()
        response["choices"][0]["message"]["role"] = "user"
        await self.assert_format_error(response)

    async def test_invalid_content_is_rejected_before_tool_or_history_write(self):
        response = self.normal()
        response["choices"][0]["finish_reason"] = "tool_calls"
        response["choices"][0]["message"] = {
            "role": "assistant", "content": {"invalid": "object"},
            "tool_calls": [{"id": "edit_001", "type": "function", "function": {
                "name": "edit_file", "arguments": json.dumps({
                    "path": "sample.py", "old_text": "value = 1", "new_text": "value = 2",
                }),
            }}],
        }
        await self.assert_format_error(response)

    async def test_internal_assertion_is_not_reported_as_success(self):
        marker = AssertionError("内部程序断言对照")
        await self.observe(marker)
        self.assertIs(self.raised, marker)
        self.assertIsNone(self.result)
        self.assertNotIn("finished", self.ends)
        self.assertEqual(self.executed, [])
        self.assertEqual(self.target.read_bytes(), b"value = 1\n")

    async def test_missing_finish_reason_is_recorded_as_model_error(self):
        response = self.normal()
        del response["choices"][0]["finish_reason"]
        await self.assert_format_error(response)

    async def test_missing_message_is_recorded_as_model_error(self):
        response = self.normal()
        del response["choices"][0]["message"]
        await self.assert_format_error(response)

    async def test_invalid_call_container_is_recorded_as_model_error(self):
        response = self.normal()
        response["choices"][0]["message"]["tool_calls"] = {}
        await self.assert_format_error(response)

    async def test_duplicate_edit_ids_reject_entire_response(self):
        response = self.normal()
        response["choices"][0]["finish_reason"] = "tool_calls"
        call = {"id": "edit_001", "type": "function", "function": {
            "name": "edit_file", "arguments": json.dumps({
                "path": "sample.py", "old_text": "value = 1", "new_text": "value = 2",
            }),
        }}
        response["choices"][0]["message"]["tool_calls"] = [call, deepcopy(call)]
        await self.assert_format_error(response)

    async def test_malformed_call_after_valid_edit_rejects_entire_response(self):
        response = self.normal()
        response["choices"][0]["finish_reason"] = "tool_calls"
        response["choices"][0]["message"]["tool_calls"] = [
            {"id": "edit_001", "type": "function", "function": {
                "name": "edit_file", "arguments": json.dumps({
                    "path": "sample.py", "old_text": "value = 1", "new_text": "value = 2",
                }),
            }},
            {"id": "edit_002", "type": "function", "function": {
                "name": "edit_file", "arguments": '{"path":',
            }},
        ]
        await self.assert_format_error(response)

    async def test_non_object_arguments_are_recorded_as_model_error(self):
        response = self.normal()
        response["choices"][0]["finish_reason"] = "tool_calls"
        response["choices"][0]["message"]["tool_calls"] = [
            {"id": "edit_001", "type": "function", "function": {
                "name": "edit_file", "arguments": "[]",
            }},
        ]
        await self.assert_format_error(response)


if __name__ == "__main__":
    unittest.main()
