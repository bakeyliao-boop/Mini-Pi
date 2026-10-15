"""助手准备：D12 模型请求预算的执行边界；计数与门禁待学习者手敲。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore
from mini_pi.tools.read_file import ReadFileExecutor


class LoopBudgetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_budget_", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "sample.txt").write_text("预算测试的实际读取内容", encoding="utf-8")
        self.reader = ReadFileExecutor(self.root)
        self.path = self.root / "session.jsonl"
        self.initial = [Message("user", "读取文件并说明内容。")]

    def request(self, call_id):
        return Message("assistant", "继续读取。", [
            ToolCall(call_id, "read_file", {"path": "sample.txt"}),
        ])

    async def test_invalid_budget_stops_before_any_side_effect(self):
        for value in (0, -1, True, 1.5, "2"):
            with self.subTest(value=value):
                provider = MockProvider([Message("assistant", "不应请求模型。")])
                with patch.object(self.reader, "execute", wraps=self.reader.execute) as execute:
                    with self.assertRaisesRegex(ValueError, "max_model_turns"):
                        await run_loop(
                            provider, self.reader, self.initial, [self.reader.definition],
                            SessionStore(self.path, "run_A"), max_model_turns=value,
                        )
                    execute.assert_not_called()
                self.assertEqual(provider.requests, [])
                self.assertFalse(self.path.exists())

    async def test_budget_two_stops_before_third_request_and_preserves_results(self):
        provider = MockProvider([
            self.request("read_001"), self.request("read_002"),
            Message("assistant", "第三次请求不应发生。"),
        ])
        store = SessionStore(self.path, "run_A")
        with patch.object(self.reader, "execute", wraps=self.reader.execute) as execute:
            result = await run_loop(
                provider, self.reader, self.initial, [self.reader.definition],
                store, max_model_turns=2,
            )
            self.assertEqual(execute.call_count, 2)

        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(result.status, "budget_exhausted")
        self.assertIsNone(result.task_passed)
        results = [item for item in result.messages if isinstance(item, ToolResult)]
        self.assertEqual([item.tool_call_id for item in results], ["read_001", "read_002"])
        self.assertTrue(all(item.error is None for item in results))
        loaded = store.load()
        self.assertEqual(loaded.history, result.messages)
        ends = [record for record in loaded.records if record["type"] == "run_end"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]["data"]["status"], "budget_exhausted")
        self.assertIsNone(ends[0]["data"]["task_passed"])
        self.assertEqual(self.initial, [Message("user", "读取文件并说明内容。")])

    async def test_final_response_on_last_allowed_turn_finishes_normally(self):
        provider = MockProvider([
            self.request("read_001"), Message("assistant", "读取完成。"),
        ])
        result = await run_loop(
            provider, self.reader, self.initial, [self.reader.definition],
            max_model_turns=2,
        )
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(result.status, "finished")
        self.assertEqual(result.messages[-1].content, "读取完成。")

    async def test_one_model_turn_can_complete_multiple_tool_calls(self):
        provider = MockProvider([
            Message("assistant", "同一响应提出两个读取。", [
                ToolCall("read_001", "read_file", {"path": "sample.txt"}),
                ToolCall("read_002", "read_file", {"path": "sample.txt"}),
            ]),
            Message("assistant", "第二次请求不应发生。"),
        ])
        with patch.object(self.reader, "execute", wraps=self.reader.execute) as execute:
            result = await run_loop(
                provider, self.reader, self.initial, [self.reader.definition],
                max_model_turns=1,
            )
            self.assertEqual(execute.call_count, 2)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(result.status, "budget_exhausted")
        self.assertEqual(sum(isinstance(item, ToolResult) for item in result.messages), 2)


if __name__ == "__main__":
    unittest.main()
