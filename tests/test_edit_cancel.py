"""D12：真实编辑线程、临时磁盘文件与循环记录的取消链验证。

写前暂停真实 prepare_edit 的返回；写中通过受控分段写入真实临时文件，
不声称暂停了操作系统的单次 write 系统调用。线程门闩自带独立时间上限。
execute 已接入共享标记与带通知的收尾等待；本组核对文件及运行记录时序。
"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from mini_pi.file_cancellation import FileCancellation
from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_recovery import find_pending_calls
from mini_pi.session_store import SessionStore
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy


class EditCancelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.temp = TemporaryDirectory(prefix="_edit_cancel_chain_", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / "value.py"
        self.target.write_bytes(b"value = 10\n")
        self.editor = EditFileExecutor(EditPolicy(self.root, ["value.py"]))
        self.started = asyncio.Event()
        self.notified = asyncio.Event()
        self.release = Event()
        self.worker_finished = Event()
        self.applied_controls = []
        self.notified_controls = []
        self.store = SessionStore(self.root / "session.jsonl")
        calls = [
            ToolCall("edit_001", "edit_file", {
                "path": "value.py", "old_text": "value = 10", "new_text": "value = 20",
            }),
            ToolCall("edit_002", "edit_file", {
                "path": "value.py", "old_text": "value = 20", "new_text": "value = 30",
            }),
        ]
        self.provider = MockProvider([Message("assistant", "依次编辑两次。", calls)])

        real_apply = self.editor.apply_edit

        def track_apply(*args, **kwargs):
            self.applied_controls.append(kwargs.get("cancellation"))
            try:
                return real_apply(*args, **kwargs)
            finally:
                self.worker_finished.set()

        self._patch(self.editor, "apply_edit", track_apply)
        real_request_cancel = FileCancellation.request_cancel

        def observe_notification(control):
            real_request_cancel(control)
            self.notified_controls.append(control)
            self.loop.call_soon_threadsafe(self.notified.set)

        self._patch(FileCancellation, "request_cancel", observe_notification)

    def _patch(self, owner, name, replacement):
        patcher = patch.object(owner, name, new=replacement)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _pause_worker(self):
        self.loop.call_soon_threadsafe(self.started.set)
        if not self.release.wait(4):
            raise RuntimeError("测试线程门闩超时；防止被测取消逻辑使测试永久挂起")

    def _gate_after_preparation(self):
        real_prepare = self.editor.prepare_edit

        def prepare_then_pause(*args):
            prepared = real_prepare(*args)
            self._pause_worker()
            return prepared

        self._patch(self.editor, "prepare_edit", prepare_then_pause)

    def _gate_during_controlled_write(self):
        def write_in_two_parts(path, data):
            # 真实写入第一段后暂停，取消期间文件实际处于在途修改状态。
            middle = len(data) // 2
            with path.open("wb") as stream:
                written = stream.write(data[:middle])
                stream.flush()
                self._pause_worker()
                written += stream.write(data[middle:])
            return written

        self._patch(Path, "write_bytes", write_in_two_parts)

    async def _cleanup_task(self, task):
        self.release.set()
        if not task.done():
            task.cancel()
        done, _ = await asyncio.wait({task}, timeout=4)
        self.assertIn(task, done, "清理后本次运行仍未结束")
        try:
            task.result()
        except (asyncio.CancelledError, Exception):
            pass
        if self.applied_controls:
            self.assertTrue(await asyncio.to_thread(self.worker_finished.wait, 4))

    async def _start_loop(self, *, total_timeout_seconds=None):
        task = asyncio.create_task(run_loop(
            self.provider, self.editor, [Message("user", "受控编辑测试。")],
            [self.editor.definition], self.store,
            total_timeout_seconds=total_timeout_seconds,
        ))
        self.addAsyncCleanup(self._cleanup_task, task)
        await asyncio.wait_for(self.started.wait(), 2)
        return task

    async def _assert_still_cleaning(self, task):
        done, _ = await asyncio.wait({task}, timeout=0.02)
        self.assertFalse(done, "编辑线程仍暂停时，循环不应提前返回")
        self.assertFalse(self.worker_finished.is_set())
        self.assertFalse(any(row["type"] == "run_end" for row in self.store.load().records))

    async def _finish_and_verify(self, task, *, status, expected_bytes):
        self.release.set()
        done, _ = await asyncio.wait({task}, timeout=2)
        self.assertIn(task, done, "线程放行后应完成收尾")
        result = task.result()
        self.assertEqual(result.status, status)
        self.assertTrue(self.worker_finished.is_set())
        self.assertEqual(self.target.read_bytes(), expected_bytes)
        self.assertEqual(len(self.applied_controls), 1, "后续编辑不得启动")
        self.assertEqual(len(self.notified_controls), 1)
        self.assertIsNotNone(self.applied_controls[0])
        self.assertIs(self.applied_controls[0], self.notified_controls[0], "通知与编辑须使用同一个标记")
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual([item for item in result.messages if isinstance(item, ToolResult)], [])
        loaded = self.store.load()
        self.assertEqual(loaded.history, result.messages)
        ends = [row for row in loaded.records if row["type"] == "run_end"]
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]["data"]["status"], status)
        self.assertEqual([item.call.id for item in find_pending_calls(loaded)], ["edit_001", "edit_002"])
        # 收尾后再给调度器一个机会，确认原工作没有留下后续写入。
        await asyncio.sleep(0.02)
        self.assertEqual(self.target.read_bytes(), expected_bytes)

    async def test_cancel_before_write_waits_for_worker_and_preserves_file(self):
        self._gate_after_preparation()
        task = await self._start_loop()
        task.cancel()
        await self._assert_still_cleaning(task)
        await asyncio.wait_for(self.notified.wait(), 1)
        self.assertEqual(self.target.read_bytes(), b"value = 10\n")
        task.cancel()  # 重复取消也不能跳过已经开始的工作收尾。
        await self._assert_still_cleaning(task)
        await self._finish_and_verify(task, status="cancelled", expected_bytes=b"value = 10\n")

    async def test_cancel_during_controlled_write_waits_and_preserves_completed_change(self):
        self._gate_during_controlled_write()
        task = await self._start_loop()
        self.assertEqual(self.target.read_bytes(), b"value")
        task.cancel()
        await self._assert_still_cleaning(task)
        await asyncio.wait_for(self.notified.wait(), 1)
        await self._finish_and_verify(task, status="cancelled", expected_bytes=b"value = 20\n")

    async def test_run_deadline_notifies_editor_and_waits_before_timeout_result(self):
        self._gate_after_preparation()
        task = await self._start_loop(total_timeout_seconds=1)
        await asyncio.wait_for(self.notified.wait(), 2)
        await self._assert_still_cleaning(task)
        await self._finish_and_verify(task, status="timeout", expected_bytes=b"value = 10\n")


if __name__ == "__main__":
    unittest.main()
