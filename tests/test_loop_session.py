"""D10：在实际循环中检查磁盘会话与模型上下文的职责分离。"""

from dataclasses import asdict
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall
from mini_pi.session_store import SessionStore
from mini_pi.tools.read_file import ReadFileExecutor


class LoopSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_loop_session_", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "session.jsonl"
        self.store = SessionStore(self.path, "run_A")
        self.reader = ReadFileExecutor(self.root)

    async def test_initial_messages_are_saved_before_first_request_without_run_event_in_context(self):
        user = Message("user", "说明读取工具的用途。")

        def answer(history, tools):
            entries = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([entry["type"] for entry in entries], ["run_start", "message"])
            self.assertEqual(entries[0]["data"]["status"], "running")
            self.assertEqual(entries[1]["data"]["content"], user.content)
            self.assertEqual([entry["run_id"] for entry in entries], ["run_A", "run_A"])
            self.assertEqual(history, [user])
            return Message("assistant", "读取工具返回指定文本文件的内容。")

        provider = MockProvider([answer])
        result = await run_loop(provider, self.reader, [user], [self.reader.definition], self.store)
        self.assertEqual(result.status, "finished")
        entries = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(entries[-1]["type"], "run_end")
        self.assertEqual(entries[-1]["data"], {
            "status": "finished", "task_passed": None, "error": None,
        })
        self.assertEqual(sum(entry["type"] == "run_end" for entry in entries), 1)

    async def test_requests_and_successful_and_failed_results_are_saved_in_history_order(self):
        source = "def final_price(price, rate):\n    return price * rate\n"
        (self.root / "discount.py").write_text(source, encoding="utf-8")
        user = Message("user", "读取两个文件。")
        request = Message("assistant", "依次读取。", [
            ToolCall("call_missing", "read_file", {"path": "missing.py"}),
            ToolCall("call_good", "read_file", {"path": "discount.py"}),
        ])

        def answer(history, tools):
            entries = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([entry["type"] for entry in entries], [
                "run_start", "message", "message", "tool_result", "tool_result",
            ])
            self.assertEqual([entry["data"] for entry in entries[1:]], [asdict(item) for item in history])
            self.assertIsNotNone(entries[3]["data"]["error"])
            self.assertEqual(entries[4]["data"]["output"], source)
            self.assertEqual([entry["data"]["tool_call_id"] for entry in entries[3:]], ["call_missing", "call_good"])
            return Message("assistant", "第一个不存在，第二个读取完成；本次未修复代码。")

        provider = MockProvider([request, answer])
        run = await run_loop(provider, self.reader, [user], [self.reader.definition], self.store)
        entries = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        items = [entry["data"] for entry in entries if entry["type"] in {"message", "tool_result"}]
        self.assertEqual(items, [asdict(item) for item in run.messages])
        self.assertTrue(all(entry["run_id"] == "run_A" for entry in entries))
        self.assertEqual(len(provider.requests), 2)

    async def test_service_config_is_not_persisted_or_included_in_model_history(self):
        sentinel = "d10-test-only-credential-marker"
        user = Message("user", "说明读取工具的用途。")
        provider = MockProvider([Message("assistant", "读取工具用于读取文本。")])
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": sentinel}):
            await run_loop(provider, self.reader, [user], [self.reader.definition], self.store)
        self.assertNotIn(sentinel, self.path.read_text(encoding="utf-8"))
        self.assertEqual(provider.requests[0], [user])


if __name__ == "__main__":
    unittest.main()
