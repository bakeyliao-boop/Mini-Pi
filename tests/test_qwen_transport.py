"""发送辅助代码的离线测试；所有网络入口均模拟，不使用真实凭证。"""

from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.error import HTTPError

from mini_pi.http_transport import post_json
from mini_pi.loop import run_loop
from mini_pi.models import Message, ToolDefinition, ToolResult
from mini_pi.qwen_client import QwenProvider
from mini_pi.qwen_provider import parse_response
from mini_pi.tools.read_file import ReadFileExecutor


class QwenTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # 手敲切换尚未完成时也禁止测试意外访问真实服务。
        legacy = patch("mini_pi.qwen_client.post_json", create=True,
                       side_effect=AssertionError("Qwen 尚未切换异步 HTTP 入口"))
        legacy.start()
        self.addCleanup(legacy.stop)

    def response(self):
        return {
            "model": "qwen3.8-flash",
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "完成。"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
        }

    def test_missing_credentials_fail_before_network(self):
        with patch.dict(os.environ, {}, clear=True), patch("mini_pi.qwen_client.post_json_async") as send:
            with self.assertRaisesRegex(ValueError, "DASHSCOPE_API_KEY"):
                QwenProvider()
            send.assert_not_called()

    async def test_send_records_response_usage_without_credential_or_request_mutation(self):
        provider = QwenProvider(api_key="fake-credential", max_completion_tokens=1024)
        request = {"model": provider.model, "messages": [{"role": "user", "content": "你好。"}], "stream": False}
        original = deepcopy(request)
        response = self.response()
        with patch("mini_pi.qwen_client.post_json_async", return_value=response) as send:
            actual = await provider._send(request)
        self.assertEqual(actual, response)
        self.assertEqual(request, original)
        self.assertEqual(send.call_count, 1)
        sent = send.call_args.args[2]
        self.assertEqual(sent["max_completion_tokens"], 1024)
        self.assertIs(sent["enable_thinking"], False)
        record = provider.request_records[0]
        self.assertEqual(record["returned_model"], response["model"])
        self.assertEqual(record["usage"], response["usage"])
        self.assertEqual(record["finish_reason"], "stop")
        self.assertEqual(record["status"], "received")
        self.assertGreaterEqual(record["elapsed_seconds"], 0)
        self.assertNotIn("fake-credential", json.dumps(provider.request_records))

    async def test_request_limit_prevents_another_send(self):
        provider = QwenProvider(api_key="fake-credential", max_requests=1)
        with patch("mini_pi.qwen_client.post_json_async", return_value=self.response()) as send:
            await provider._send({"model": provider.model, "messages": []})
            with self.assertRaisesRegex(RuntimeError, "请求次数上限"):
                await provider._send({"model": provider.model, "messages": []})
        self.assertEqual(send.call_count, 1)
        self.assertEqual(len(provider.request_records), 1)

    async def test_send_failure_is_recorded_without_automatic_retry(self):
        provider = QwenProvider(api_key="fake-credential")
        with patch("mini_pi.qwen_client.post_json_async", side_effect=RuntimeError("模型请求失败：HTTP 401")) as send:
            with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
                await provider._send({"model": provider.model, "messages": []})
        self.assertEqual(send.call_count, 1)
        self.assertEqual(provider.request_records[0]["status"], "request_error")
        self.assertIsNone(provider.request_records[0]["usage"])

    def test_http_error_does_not_expose_raw_response_body(self):
        endpoint = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        error = HTTPError(endpoint, 401, "Unauthorized", None, BytesIO(b"private response body"))
        with patch("mini_pi.http_transport.build_opener") as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaisesRegex(RuntimeError, "HTTP 401") as caught:
                post_json(endpoint, "fake-credential", {"model": "qwen3.8-flash"})
        self.assertNotIn("private response body", str(caught.exception))
        self.assertNotIn("fake-credential", str(caught.exception))
        self.assertEqual(opener.return_value.open.call_count, 1)

    async def test_generate_returns_unified_message_from_service_response(self):
        provider = QwenProvider(api_key="fake-credential")
        with patch("mini_pi.qwen_client.post_json_async", return_value=self.response()):
            message = await provider.generate([Message("user", "你好。")], [])
        self.assertEqual(message, Message("assistant", "完成。", stop_reason="stop"))
        self.assertEqual(provider.request_records[0]["request_body"]["messages"], [{"role": "user", "content": "你好。"}])

    async def test_truncated_response_is_parsed_but_never_executed(self):
        provider = QwenProvider(api_key="fake-credential")
        response = self.response()
        response["choices"][0] = {
            "finish_reason": "length",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_001",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path":"discount.py"}'},
                }],
            },
        }
        executor = Mock()
        executor.execute = AsyncMock()
        tool = ToolDefinition("read_file", "读取文件。", {"type": "object"})
        with patch("mini_pi.qwen_client.post_json_async", return_value=response), patch(
            "mini_pi.qwen_client.parse_response", wraps=parse_response,
        ) as parse:
            result = await run_loop(
                provider, executor, [Message("user", "读取文件。")], [tool], max_model_turns=1,
            )
        self.assertEqual(result.status, "budget_exhausted")
        parse.assert_called_once_with(response)
        executor.execute.assert_not_awaited()
        self.assertEqual(result.messages[1].stop_reason, "length")
        feedback = [item for item in result.messages if isinstance(item, ToolResult)]
        self.assertEqual([item.tool_call_id for item in feedback], ["call_001"])
        self.assertTrue(feedback[0].error)

    async def test_provider_joins_existing_loop_with_real_file_and_mocked_http(self):
        test_parent = Path(__file__).resolve().parent
        provider = QwenProvider(api_key="fake-credential")
        source = "def final_price(price, discount_rate):\n    return price * discount_rate\n"
        with TemporaryDirectory(prefix="_qwen_loop_", dir=test_parent) as directory:
            root = Path(directory).resolve()
            root.relative_to(test_parent)
            (root / "discount.py").write_text(source, encoding="utf-8")
            executor = ReadFileExecutor(root)
            sent_requests = []

            def respond(endpoint, api_key, payload, timeout):
                sent_requests.append(deepcopy(payload))
                response = self.response()
                if len(sent_requests) == 1:
                    response["choices"][0] = {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": "call_001",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": '{"path":"discount.py"}'},
                            }],
                        },
                    }
                else:
                    self.assertEqual([message["role"] for message in payload["messages"]], ["user", "assistant", "tool"])
                    self.assertEqual(payload["messages"][2]["tool_call_id"], "call_001")
                    self.assertEqual(json.loads(payload["messages"][2]["content"]), {"output": source, "error": None})
                    response["choices"][0]["message"]["content"] = "读取到：\n" + source
                return response

            with patch("mini_pi.qwen_client.post_json_async", side_effect=respond) as send:
                run = await run_loop(provider, executor, [Message("user", "读取文件。")], [executor.definition])
        self.assertEqual(send.call_count, 2)
        self.assertEqual(len(run.messages), 4)
        self.assertIsInstance(run.messages[2], ToolResult)
        self.assertEqual(run.messages[2].output, source)
        self.assertEqual(run.messages[3].content, "读取到：\n" + source)
        self.assertEqual(run.status, "finished")
        self.assertIsNone(run.task_passed)


if __name__ == "__main__":
    unittest.main()
