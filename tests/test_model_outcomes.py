"""D13-A 行为反例：模型错误的结束记录、截断反馈及完整重试。

仅替换 HTTP 返回，不替换响应转换、循环、执行器或记录层。
临时文件是真实文件；执行次数、配对结果、下一请求和落盘共同验收。
"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.loop import run_loop
from mini_pi.models import Message, ToolResult
from mini_pi.qwen_client import QwenProvider
from mini_pi.session_recovery import find_pending_calls
from mini_pi.session_store import SessionStore
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy
from mini_pi.tools.read_file import ReadFileExecutor
from mini_pi.tools.tool_router import ToolRouter


def response(reason="stop", calls=None, text="本次回答完成。"):
    return {"model": "test-model", "choices": [{
        "finish_reason": reason,
        "message": {"role": "assistant", "content": text, "tool_calls": calls or []},
    }]}


def raw_call(call_id, name, arguments):
    return {"id": call_id, "type": "function", "function": {
        "name": name,
        "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
    }}


class ModelOutcomeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_model_outcomes_", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / "sample.py"
        self.before = b"value = 1\n"
        self.after = b"value = 2\n"
        self.target.write_bytes(self.before)
        self.reader = ReadFileExecutor(self.root)
        self.editor = EditFileExecutor(EditPolicy(self.root, ["sample.py"]))
        self.router = ToolRouter({"read_file": self.reader, "edit_file": self.editor})
        self.tools = [self.reader.definition, self.editor.definition]
        self.store = SessionStore(self.root / "session.jsonl", "outcome_run")
        self.provider = QwenProvider(api_key="synthetic-test-placeholder")
        self.sent = []
        self.file_at_send = []
        self.observation = {}
        self.result = None
        self.raised = None

    def edit(self, call_id="edit_001", *, incomplete=False):
        arguments = '{"path":"sample.py","old_text":' if incomplete else {
            "path": "sample.py", "old_text": "value = 1", "new_text": "value = 2",
        }
        return raw_call(call_id, "edit_file", arguments)

    def read(self, call_id="read_001"):
        return raw_call(call_id, "read_file", {"path": "sample.py"})

    async def run_script(self, steps, *, budget=None):
        async def send(url, key, payload, timeout):
            index = len(self.sent)
            self.sent.append(deepcopy(payload))
            self.file_at_send.append(self.target.read_bytes())
            if index >= len(steps):
                raise AssertionError("出现预期之外的模型请求")
            step = steps[index]
            if isinstance(step, Exception):
                raise step
            return deepcopy(step)

        with patch("mini_pi.qwen_client.post_json_async", side_effect=send), patch.object(
            self.router, "execute", wraps=self.router.execute,
        ) as execute:
            try:
                async with asyncio.timeout(2):
                    self.result = await run_loop(
                        self.provider, self.router, [Message("user", "处理测试文件。")],
                        self.tools, self.store, max_model_turns=budget,
                    )
            except Exception as error:
                # 保留当前行为，让预期契约以断言失败呈现，而非未分类测试异常。
                self.raised = error
            self.executed = [item.args[0].id for item in execute.await_args_list]
        self.loaded = self.store.load()
        self.ends = [row["data"] for row in self.loaded.records if row["type"] == "run_end"]
        self.feedback = [item for item in self.loaded.history if isinstance(item, ToolResult)]
        self.observation = {
            "uncaught_exception_type": type(self.raised).__name__ if self.raised else None,
            "uncaught_exception": str(self.raised) if self.raised else None,
            "returned_status": self.result.status if self.result else None,
            "run_end_statuses": [row["status"] for row in self.ends],
            "model_requests": len(self.sent), "executed_call_ids": self.executed,
            "saved_feedback": [{"id": item.tool_call_id, "error": item.error} for item in self.feedback],
            "file_changed": self.target.read_bytes() != self.before,
            "file_at_each_request": [data.decode("utf-8") for data in self.file_at_send],
        }

    def assert_outcome(self, status):
        self.observation["expected_status"] = status
        self.assertIsNone(self.raised, f"应形成 {status} 结果，当前直接抛出 {self.raised!r}")
        self.assertIsNotNone(self.result)
        self.assertEqual(self.result.status, status)
        self.assertEqual(len(self.ends), 1)
        self.assertEqual(self.ends[0]["status"], status)
        self.assertEqual(self.ends[0].get("error"), self.result.error)
        self.assertIsNone(self.result.task_passed)
        self.assertEqual(self.loaded.history, self.result.messages)

    def assert_rejected_feedback(self):
        rejected = [item for item in self.feedback if item.tool_call_id in {"edit_001", "read_001"}]
        self.assertEqual([item.tool_call_id for item in rejected], ["edit_001", "read_001"])
        self.assertTrue(all(item.error for item in rejected))
        self.assertEqual(find_pending_calls(self.loaded), [])

    async def test_normal_answer_finishes_and_records_once(self):
        await self.run_script([response()])
        self.assert_outcome("finished")
        self.assertEqual(self.executed, [])
        self.assertEqual(self.target.read_bytes(), self.before)

    async def test_normal_tool_call_changes_real_file_and_returns_feedback(self):
        await self.run_script([response("tool_calls", [self.edit()]), response()])
        self.assert_outcome("finished")
        self.assertEqual(self.executed, ["edit_001"])
        self.assertEqual(self.target.read_bytes(), self.after)
        self.assertIsNone(self.feedback[0].error)

    async def test_transport_error_returns_error_and_saves_single_end(self):
        await self.run_script([RuntimeError("受控模型连接失败")])
        self.assert_outcome("error")
        self.assertTrue(self.result.error)
        self.assertEqual(self.executed, [])
        self.assertEqual(self.target.read_bytes(), self.before)

    async def test_provider_error_reason_stops_without_executing_its_tool_calls(self):
        await self.run_script([response("content_filter", [self.edit()])])
        self.assert_outcome("error")
        self.assertIn("content_filter", self.result.error)
        stopped = self.loaded.history[-1]
        self.assertEqual(stopped.stop_reason, "error")
        self.assertEqual(stopped.error_message, self.result.error)
        self.assertEqual([call.id for call in stopped.tool_calls], ["edit_001"])
        self.assertEqual(self.executed, [])
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertEqual(len(self.sent), 1)

    async def check_truncated_retry(self, *, incomplete):
        await self.run_script([
            response("length", [self.edit(incomplete=incomplete), self.read()]),
            response("tool_calls", [self.edit("edit_002")]),
            response(),
        ])
        self.assert_outcome("finished")
        self.assertEqual(self.executed, ["edit_002"], "整个截断批次不得进入执行器")
        self.assertEqual(len(self.sent), 3)
        self.assertEqual(self.file_at_send, [self.before, self.before, self.after])
        self.assertEqual(self.target.read_bytes(), self.after)
        self.assert_rejected_feedback()
        truncated_message = self.loaded.history[1]
        original_arguments = self.edit(incomplete=incomplete)["function"]["arguments"]
        self.assertEqual(truncated_message.stop_reason, "length")
        self.assertEqual(truncated_message.tool_calls[0].raw_arguments, original_arguments)
        if incomplete:
            self.assertIsNone(truncated_message.tool_calls[0].arguments)
        assistant_history = [item for item in self.sent[1]["messages"] if item["role"] == "assistant"]
        self.assertEqual(assistant_history[0]["tool_calls"][0]["function"]["arguments"], original_arguments)
        tool_messages = [item for item in self.sent[1]["messages"] if item["role"] == "tool"]
        self.assertEqual([item["tool_call_id"] for item in tool_messages], ["edit_001", "read_001"])
        self.assertTrue(all(json.loads(item["content"])["error"] for item in tool_messages))
        self.assertEqual([item.tool_call_id for item in self.feedback], ["edit_001", "read_001", "edit_002"])

    async def test_length_with_valid_json_rejects_all_calls_then_allows_complete_retry(self):
        await self.check_truncated_retry(incomplete=False)

    async def test_length_with_incomplete_json_keeps_ids_and_allows_complete_retry(self):
        await self.check_truncated_retry(incomplete=True)

    async def test_truncated_batch_feedback_is_saved_but_new_request_obeys_budget(self):
        await self.run_script([response("length", [self.edit(), self.read()])], budget=1)
        self.assert_outcome("budget_exhausted")
        self.assert_rejected_feedback()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.executed, [])
        self.assertEqual(self.target.read_bytes(), self.before)

    async def test_text_only_length_keeps_reason_without_forcing_retry(self):
        await self.run_script([response("length", text="尚未写完的文字")])
        self.assert_outcome("finished")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.executed, [])
        assistant = self.loaded.history[-1]
        self.assertEqual(getattr(assistant, "stop_reason", None), "length")
        rows = [row for row in self.loaded.records if row["type"] == "message"]
        self.assertEqual(rows[-1]["data"].get("stop_reason"), "length")

    async def test_completed_tool_result_survives_later_model_error(self):
        await self.run_script([
            response("tool_calls", [self.read()]), RuntimeError("下一轮模型连接失败"),
        ])
        self.assert_outcome("error")
        self.assertEqual(self.executed, ["read_001"])
        self.assertEqual([item.tool_call_id for item in self.feedback], ["read_001"])
        self.assertEqual(self.feedback[0].output, self.before.decode("utf-8"))
        self.assertEqual(len(self.sent), 2)

    async def test_active_cancellation_remains_cancelled(self):
        started = asyncio.Event()
        cleaned = []

        async def waiting_send(*args, **kwargs):
            started.set()
            try:
                await asyncio.Future()
            finally:
                cleaned.append(True)

        with patch("mini_pi.qwen_client.post_json_async", side_effect=waiting_send):
            task = asyncio.create_task(run_loop(
                self.provider, self.router, [Message("user", "等待时取消。")], self.tools, self.store,
            ))
            try:
                await asyncio.wait_for(started.wait(), 2)
                task.cancel()
                result = await asyncio.wait_for(task, 2)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        loaded = self.store.load()
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(cleaned, [True])
        self.assertEqual([row["data"]["status"] for row in loaded.records if row["type"] == "run_end"], ["cancelled"])
        self.assertEqual(self.target.read_bytes(), self.before)


if __name__ == "__main__":
    unittest.main()
