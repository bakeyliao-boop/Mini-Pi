"""D13-A：响应转换保留停止原因，内部元信息不作为 API 消息字段发送。

转换函数尚未接参数时前两项应失败；不在测试中替换核心实现。
"""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.loop import run_loop
from mini_pi.models import Message
from mini_pi.qwen_client import QwenProvider
from mini_pi.qwen_provider import message_to_api, parse_assistant_message
from mini_pi.session_store import SessionStore
from mini_pi.tools.read_file import ReadFileExecutor


class QwenStopReasonTests(unittest.TestCase):
    def test_length_keeps_valid_call_identity_and_reason_without_mutating_input(self):
        raw = {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "edit_001", "type": "function", "function": {
                "name": "edit_file",
                "arguments": '{"path":"sample.py","old_text":"1","new_text":"2"}',
            }}],
        }
        before = deepcopy(raw)
        message = parse_assistant_message(raw, stop_reason="length")
        self.assertEqual(message.stop_reason, "length")
        self.assertIsNone(message.error_message)
        self.assertEqual(message.tool_calls[0].id, "edit_001")
        self.assertEqual(message.tool_calls[0].arguments["path"], "sample.py")
        self.assertEqual(raw, before)

    def test_error_keeps_reason_and_explanation(self):
        message = parse_assistant_message(
            {"role": "assistant", "content": "保留已有文字。"},
            stop_reason="error", error_message="受控服务错误",
        )
        self.assertEqual(message.stop_reason, "error")
        self.assertEqual(message.error_message, "受控服务错误")
        self.assertEqual(message.content, "保留已有文字。")
        self.assertEqual(message.tool_calls, [])

    def test_internal_stop_metadata_is_not_sent_as_api_message_fields(self):
        message = Message("assistant", "部分回复。", stop_reason="length", error_message="内部说明")
        self.assertEqual(message_to_api(message), {"role": "assistant", "content": "部分回复。"})


class StopReasonRoundTripTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_stop_reason_", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = SessionStore(self.root / "session.jsonl")

    async def test_normal_provider_reason_reaches_loop_record_and_loaded_history(self):
        provider = QwenProvider(api_key="synthetic-test-placeholder")
        reader = ReadFileExecutor(self.root)
        raw = {"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "完成。",
        }}]}
        with patch("mini_pi.qwen_client.post_json_async", return_value=raw), patch.object(
            reader, "execute", wraps=reader.execute,
        ) as execute:
            result = await run_loop(provider, reader, [Message("user", "回答。")], [], self.store)
        self.assertEqual(result.status, "finished")
        self.assertEqual(result.messages[-1].stop_reason, "stop")
        loaded = self.store.load()
        self.assertEqual(loaded.history, result.messages)
        self.assertEqual(loaded.history[-1].stop_reason, "stop")
        rows = [row for row in loaded.records if row["type"] == "message"]
        self.assertEqual(rows[-1]["data"]["stop_reason"], "stop")
        execute.assert_not_awaited()

    async def test_saved_error_metadata_is_restored_without_record_mutation(self):
        original = Message("assistant", "已有回复。", stop_reason="error", error_message="受控错误说明")
        self.store.append_item(original)
        before = self.store.path.read_bytes()
        loaded = self.store.load()
        self.assertEqual(loaded.history, [original])
        self.assertEqual(loaded.history[0].error_message, "受控错误说明")
        self.assertEqual(self.store.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
