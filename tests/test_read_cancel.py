"""D12：读取进行中取消的边界，模拟模型配合真实临时文件与读取工作。

受控读取打开文件、读到首字符后暂停。主流程可先报告取消，随后完成的
读取不得追加结果、改写运行记录或触发下一工具。后台句柄不声称已立刻关闭。
本组不覆盖取消已请求但工具尚未启动的门禁，也不覆盖目录扫描。
"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_recovery import find_pending_calls
from mini_pi.session_store import SessionStore
from mini_pi.tools.read_file import ReadFileExecutor


class ReadCancelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.temp = TemporaryDirectory(prefix="_read_cancel_", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.first = self.root / "first.txt"
        self.second = self.root / "second.txt"
        self.first.write_bytes(b"first file\n")
        self.second.write_bytes(b"second file\n")
        self.editor = ReadFileExecutor(self.root)
        self.store = SessionStore(self.root / "session.jsonl")
        self.initial = [Message("user", "读取两个测试文件。")]
        self.started = asyncio.Event()
        self.release = Event()
        self.read_finished = Event()
        self.handles = []
        self.read_calls = []
        calls = [
            ToolCall("read_001", "read_file", {"path": "first.txt"}),
            ToolCall("read_002", "read_file", {"path": "second.txt"}),
        ]
        self.provider = MockProvider([
            Message("assistant", "依次读取两个文件。", calls),
            Message("assistant", "两个结果都已收到。"),
        ])
        native_read = Path.read_text

        def controlled_read(path, *args, **kwargs):
            if path.parent != self.root or path.name not in {"first.txt", "second.txt"}:
                return native_read(path, *args, **kwargs)
            self.read_calls.append(path.name)
            try:
                with path.open("r", encoding=kwargs.get("encoding", "utf-8")) as file:
                    self.handles.append(file)
                    first_character = file.read(1)
                    self.loop.call_soon_threadsafe(self.started.set)
                    if not self.release.wait(4):
                        raise RuntimeError("测试读取工作等待放行超时")
                    return first_character + file.read()
            finally:
                self.read_finished.set()

        reader_patch = patch.object(Path, "read_text", new=controlled_read)
        reader_patch.start()
        self.addCleanup(reader_patch.stop)

    async def _cleanup_task(self, task):
        self.release.set()
        if not task.done():
            task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        self.assertIn(task, done, "测试清理时主流程仍未结束")
        try:
            task.result()
        except (asyncio.CancelledError, Exception):
            pass
        if self.read_calls:
            self.assertTrue(await asyncio.to_thread(self.read_finished.wait, 2))
        self.assertTrue(all(handle.closed for handle in self.handles))

    async def _start_loop(self, *, timeout=None):
        task = asyncio.create_task(run_loop(
            self.provider, self.editor, self.initial, [self.editor.definition], self.store,
            total_timeout_seconds=timeout,
        ))
        self.addAsyncCleanup(self._cleanup_task, task)
        await asyncio.wait_for(self.started.wait(), 2)
        return task

    async def _assert_cancelled_read(self, task, expected_status):
        done, _ = await asyncio.wait({task}, timeout=2)
        self.assertIn(task, done, "只读取消不要求先等底层读取自然完成")
        result = task.result()
        self.assertEqual(result.status, expected_status)
        self.assertFalse(self.read_finished.is_set())
        self.assertTrue(self.handles)
        self.assertFalse(self.handles[0].closed, "此刻不能把取消状态解释成句柄已关闭")
        self.assertEqual(self.read_calls, ["first.txt"])
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual([item for item in result.messages if isinstance(item, ToolResult)], [])
        loaded = self.store.load()
        self.assertEqual(loaded.history, result.messages)
        self.assertEqual([item.call.id for item in find_pending_calls(loaded)], ["read_001", "read_002"])
        ends = [row for row in loaded.records if row["type"] == "run_end"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]["data"]["status"], expected_status)
        records_before = self.store.path.read_bytes()
        history_before = list(result.messages)

        # 主流程返回后再完成真实读取，核对这个晚到的结果不被消费。
        self.release.set()
        self.assertTrue(await asyncio.to_thread(self.read_finished.wait, 2))
        await asyncio.sleep(0.02)
        self.assertTrue(all(handle.closed for handle in self.handles))
        self.assertEqual(self.store.path.read_bytes(), records_before)
        self.assertEqual(result.messages, history_before)
        self.assertEqual(self.read_calls, ["first.txt"])
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual(self.first.read_bytes(), b"first file\n")
        self.assertEqual(self.second.read_bytes(), b"second file\n")

    async def test_normal_read_returns_actual_contents_to_next_model_request(self):
        self.release.set()
        task = await self._start_loop()
        done, _ = await asyncio.wait({task}, timeout=2)
        self.assertIn(task, done)
        result = task.result()
        self.assertEqual(result.status, "finished")
        self.assertEqual(self.read_calls, ["first.txt", "second.txt"])
        self.assertEqual(len(self.provider.requests), 2)
        feedback = [item for item in self.provider.requests[1] if isinstance(item, ToolResult)]
        self.assertEqual([item.output for item in feedback], ["first file\n", "second file\n"])
        self.assertTrue(all(handle.closed for handle in self.handles))

    async def test_cancelled_read_discards_late_result_and_stops_next_tool(self):
        task = await self._start_loop()
        task.cancel()
        await self._assert_cancelled_read(task, "cancelled")

    async def test_timed_out_read_discards_late_result_and_stops_next_tool(self):
        task = await self._start_loop(timeout=1)
        await self._assert_cancelled_read(task, "timeout")


if __name__ == "__main__":
    unittest.main()
