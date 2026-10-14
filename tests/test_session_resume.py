"""D11：正常结束后加载并继续，保留上下文且不重复写入旧历史。"""

from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall
from mini_pi.session_store import SessionStore
from mini_pi.tools.read_file import ReadFileExecutor


class SessionResumeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_resume_", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "session.jsonl"
        self.reader = ReadFileExecutor(self.root)

    async def test_normal_resume_sees_previous_history_without_replay_or_duplicate_records(self):
        source = "def final_price(price, rate):\n    return price * rate\n"
        (self.root / "discount.py").write_text(source, encoding="utf-8")
        first_provider = MockProvider([
            Message("assistant", "先读取文件。", [
                ToolCall("call_001", "read_file", {"path": "discount.py"}),
            ]),
            Message("assistant", "读取完成，尚未修改代码。"),
        ])
        first = await run_loop(
            first_provider, self.reader, [Message("user", "读取 discount.py。")],
            [self.reader.definition], SessionStore(self.path, "run_A"),
        )
        original_bytes = self.path.read_bytes()
        resumed_store = SessionStore(self.path, "run_B")
        loaded = resumed_store.load()
        self.assertEqual(loaded.history, first.messages)
        new_user = Message("user", "继续解释之前读到的公式。")

        def answer(history, tools):
            self.assertEqual(history, loaded.history + [new_user])
            self.assertEqual(history[2].output, source)
            return Message("assistant", "该公式返回优惠金额，本次仅依据保存内容解释。")

        second_provider = MockProvider([answer])
        with patch.object(self.reader, "execute") as execute:
            second = await run_loop(
                second_provider, self.reader, loaded.history + [new_user],
                [self.reader.definition], resumed_store, already_saved=len(loaded.history),
            )
        execute.assert_not_awaited()
        self.assertTrue(self.path.read_bytes().startswith(original_bytes))
        final = resumed_store.load()
        self.assertEqual(final.history, second.messages)
        self.assertEqual(len(final.records), 10)
        new_records = [record for record in final.records if record["run_id"] == "run_B"]
        self.assertEqual([record["type"] for record in new_records], [
            "run_start", "message", "message", "run_end",
        ])
        self.assertEqual(new_records[1]["data"], asdict(new_user))
        self.assertEqual(sum(record["type"] == "tool_result" for record in final.records), 1)
        self.assertEqual(second.status, "finished")
        self.assertIsNone(second.task_passed)

    async def test_invalid_saved_count_stops_before_model_request_or_file_write(self):
        for saved_count in (-1, 2, True):
            with self.subTest(saved_count=saved_count):
                provider = MockProvider([Message("assistant", "不应请求模型。")])
                with self.assertRaises(ValueError):
                    await run_loop(
                        provider, self.reader, [Message("user", "新消息")],
                        [self.reader.definition], SessionStore(self.path), already_saved=saved_count,
                    )
                self.assertEqual(provider.requests, [])
                self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
