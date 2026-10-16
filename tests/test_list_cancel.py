"""D12：真实临时目录扫描的执行线程、取消与总时限边界。

不替换工具或循环。只在实际 os.scandir 迭代到目录项时暂停，
由独立控制线程发出取消/等待结果，避免测试本身被事件循环阻塞。
"""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread, get_ident
import unittest
from unittest.mock import patch

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore
from mini_pi.tools.list_files import ListFilesExecutor


class ListCancelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_list_cancel_", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workdir = self.root / "workspace"
        self.workdir.mkdir()
        (self.workdir / "a.txt").write_bytes(b"a\n")
        (self.workdir / "sub").mkdir()
        self.executor = ListFilesExecutor(self.workdir)
        self.store = SessionStore(self.root / "session.jsonl")
        self.main_thread = get_ident()
        self.started = Event()
        self.release = Event()
        self.scan_finished = Event()
        self.task_finished = Event()
        self.scan_threads = []
        self.metadata_threads = []
        self.closed_handles = []
        self.observation = {}
        self.control_errors = []
        self.controller = None
        self.task = None
        self.calls = [
            ToolCall("list_001", "list_files", {}),
            ToolCall("list_002", "list_files", {}),
        ]
        self.provider = MockProvider([
            Message("assistant", "列出目录两次。", self.calls),
            Message("assistant", "已收到目录列表。"),
        ])
        self.initial = [Message("user", "列出测试目录。")]
        native_scandir = os.scandir
        native_is_dir = Path.is_dir
        owner = self

        class ControlledScan:
            def __init__(self, path):
                self.handle = native_scandir(path)

            def __enter__(self):
                self.handle.__enter__()
                owner.scan_threads.append(get_ident())
                return self

            def __iter__(self):
                for entry in self.handle:
                    owner.started.set()
                    if not owner.release.wait(3):
                        raise RuntimeError("测试扫描等待放行超时")
                    yield entry

            def __exit__(self, *args):
                try:
                    return self.handle.__exit__(*args)
                finally:
                    owner.closed_handles.append(True)
                    owner.scan_finished.set()

        def controlled_scandir(path):
            if str(path) == str(owner.workdir):
                return ControlledScan(path)
            return native_scandir(path)

        def observed_is_dir(path, *args, **kwargs):
            if path.parent == owner.workdir:
                owner.metadata_threads.append(get_ident())
            return native_is_dir(path, *args, **kwargs)

        for instrument in (
            patch.object(os, "scandir", new=controlled_scandir),
            patch.object(Path, "is_dir", new=observed_is_dir),
        ):
            instrument.start()
            self.addCleanup(instrument.stop)
        self.addAsyncCleanup(self._cleanup_work)

    async def _cleanup_work(self):
        self.release.set()
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.wait({self.task}, timeout=2)
        if self.controller is not None:
            await asyncio.to_thread(self.controller.join, 2)
            self.assertFalse(self.controller.is_alive())
        if self.started.is_set():
            self.assertTrue(await asyncio.to_thread(self.scan_finished.wait, 2))

    async def _run(self, *, timeout=None):
        self.task = asyncio.create_task(run_loop(
            self.provider, self.executor, self.initial,
            [self.executor.definition], self.store,
            total_timeout_seconds=timeout,
        ))
        self.task.add_done_callback(lambda _: self.task_finished.set())
        return await asyncio.wait_for(asyncio.shield(self.task), 3)

    async def test_scan_runs_off_event_loop_thread(self):
        self.release.set()
        result = await self._run()
        feedback = [item for item in self.provider.requests[1] if isinstance(item, ToolResult)]
        self.assertEqual([item.output for item in feedback], ["a.txt\nsub/", "a.txt\nsub/"])
        self.assertEqual(result.status, "finished")
        self.assertEqual(len(self.closed_handles), 2)
        self.observation = {"scan_on_event_loop_thread": self.main_thread in self.scan_threads}
        self.assertNotIn(self.main_thread, self.scan_threads, "真实扫描不能阻塞事件循环")

    async def test_metadata_checks_run_off_event_loop_thread(self):
        self.release.set()
        result = await self._run()
        self.assertEqual(result.status, "finished")
        self.assertTrue(self.metadata_threads)
        self.observation = {"metadata_on_event_loop_thread": self.main_thread in self.metadata_threads}
        self.assertNotIn(self.main_thread, self.metadata_threads, "逐项目录判断也不应阻塞事件循环")

    async def _interrupt_scan(self, mode):
        loop = asyncio.get_running_loop()
        returned_before_release = []

        def control():
            try:
                if not self.started.wait(2):
                    self.control_errors.append("扫描未开始")
                    return
                if mode == "cancelled":
                    loop.call_soon_threadsafe(self.task.cancel)
                # 超时场景由真实 total_timeout_seconds 触发，不由测试手动取消。
                returned_before_release.append(self.task_finished.wait(0.6))
            finally:
                self.release.set()

        self.controller = Thread(target=control, daemon=True)
        self.controller.start()
        result = await self._run(timeout=0.1 if mode == "timeout" else None)
        history_before = list(result.messages)
        records_before = self.store.path.read_bytes()
        await asyncio.to_thread(self.controller.join, 2)
        self.assertTrue(await asyncio.to_thread(self.scan_finished.wait, 2))
        await asyncio.sleep(0)
        loaded = self.store.load()
        ends = [row["data"]["status"] for row in loaded.records if row["type"] == "run_end"]
        self.observation = {
            "expected_status": mode, "actual_status": result.status,
            "expected_return_before_scan_release": True,
            "actual_return_before_scan_release": returned_before_release == [True],
            "scan_on_event_loop_thread": self.main_thread in self.scan_threads,
            "scans_started": len(self.scan_threads),
            "model_requests": len(self.provider.requests),
            "tool_results": [item.tool_call_id for item in result.messages if isinstance(item, ToolResult)],
            "run_end_statuses": ends,
            "late_records_unchanged": records_before == self.store.path.read_bytes(),
        }
        self.assertEqual(self.control_errors, [])
        self.assertEqual(result.status, mode)
        self.assertEqual(len(self.scan_threads), 1)
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual(self.observation["tool_results"], [])
        self.assertEqual(ends, [mode])
        self.assertEqual(result.messages, history_before)
        self.assertEqual(records_before, self.store.path.read_bytes())
        self.assertEqual((self.workdir / "a.txt").read_bytes(), b"a\n")
        self.assertEqual(returned_before_release, [True], "主流程应能在扫描未结束时处理取消或超时")

    async def test_cancel_can_return_while_scan_is_still_blocked(self):
        await self._interrupt_scan("cancelled")

    async def test_deadline_can_return_while_scan_is_still_blocked(self):
        await self._interrupt_scan("timeout")

    async def test_cancel_requested_before_start_does_not_scan(self):
        def cancel_before_tools(history, tools):
            asyncio.current_task().cancel()
            return Message("assistant", "准备列目录。", self.calls)

        self.provider = MockProvider([cancel_before_tools])
        result = await self._run()
        self.observation = {"status": result.status, "scans_started": len(self.scan_threads)}
        self.assertEqual(result.status, "cancelled")
        self.assertFalse(self.started.is_set())
        self.assertEqual(self.scan_threads, [])


if __name__ == "__main__":
    unittest.main()
