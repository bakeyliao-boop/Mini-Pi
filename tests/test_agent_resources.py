"""D13-B：公开 Agent 取消入口与真实本地连接、进程树、编辑线程收尾。

不访问真实模型服务；只在本次临时目录运行固定测试脚本及受控写入。
"""

import asyncio
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.agent import Agent
from mini_pi.file_cancellation import FileCancellation
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall
from mini_pi.qwen_client import QwenProvider
from mini_pi.session_store import SessionStore
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy
from mini_pi.tools.run_tests import RunTestsExecutor
from tests.http_test_server import LocalHttpsServer
from tests.test_process_cleanup import TREE_SCRIPT, process_is_running


class AgentResourceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_agent_resources_", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.observation = {}

    async def settle(self, agent, pending):
        agent.abort()
        try:
            async with asyncio.timeout(10):
                await agent.wait_for_idle()
                await pending
        except (asyncio.CancelledError, Exception):
            pass

    def submit(self, provider, executor, tools, store):
        agent = Agent(provider, executor, tools)
        pending = agent.prompt([Message("user", "受控资源验收")], session_store=store)
        self.addAsyncCleanup(self.settle, agent, pending)
        return agent, pending

    def assert_cancelled_record(self, agent, result, store):
        self.assertFalse(agent.is_running)
        self.assertEqual(result.status, "cancelled")
        loaded = store.load()
        self.assertEqual(loaded.history, result.messages)
        self.assertEqual([r["data"]["status"] for r in loaded.records
                          if r["type"] == "run_end"], ["cancelled"])

    async def test_https_abort_closes_client_before_idle(self):
        server = await LocalHttpsServer(mode="hang_body").start()
        self.addAsyncCleanup(server.close)
        store = SessionStore(self.root / "https.jsonl")
        provider = QwenProvider(api_key="offline-placeholder", timeout=10,
                                base_url=server.url.removesuffix("/chat/completions"))
        executor = AsyncMock()
        with patch("mini_pi.async_http_transport._make_client", side_effect=server.make_client):
            agent, pending = self.submit(provider, executor, [], store)
            async with asyncio.timeout(5):
                await server.response_seen.wait()
                agent.abort()
                await agent.wait_for_idle()
                result = await pending
            self.assert_cancelled_record(agent, result, store)
            self.assertTrue(server.clients)
            self.assertTrue(all(client.is_closed for client in server.clients))
            self.assertTrue(all(response.is_closed for response in server.responses))
            await asyncio.wait_for(server.disconnected.wait(), 2)
            executor.execute.assert_not_called()
            self.assertEqual(len(server.requests), 1)
            self.assertEqual(server.errors, [])
            self.observation = {"resource": "local_https", "status": result.status,
                                "clients_closed_before_idle_check": True,
                                "responses_closed": True, "server_disconnected": True}

    async def test_process_abort_stops_real_parent_and_descendant_before_idle(self):
        marker = self.root / "pids.json"
        script = self.root / "fixture.py"
        script.write_text(TREE_SCRIPT, encoding="utf-8")
        evidence = self.root / "process-evidence"
        executor = RunTestsExecutor(self.root,
            (sys.executable, "-X", "utf8", str(script), str(marker), "wait"),
            evidence, timeout_seconds=30)
        provider = MockProvider([Message("assistant", "测试", [
            ToolCall("tests_001", "run_tests", {}), ToolCall("tests_002", "run_tests", {}),
        ])])
        store = SessionStore(self.root / "process.jsonl")
        agent, pending = self.submit(provider, executor, [executor.definition], store)
        async with asyncio.timeout(8):
            while True:
                try:
                    pids = json.loads(marker.read_text(encoding="utf-8"))
                    break
                except (FileNotFoundError, PermissionError, json.JSONDecodeError):
                    if pending.done():
                        self.fail(f"进程未就绪，运行已结束：{pending.result()}")
                    await asyncio.sleep(0.01)
        self.assertTrue(all(process_is_running(pid) for pid in pids))
        agent.abort()
        async with asyncio.timeout(10):
            await agent.wait_for_idle()
            result = await pending
        self.assert_cancelled_record(agent, result, store)
        traces = [p for p in evidence.glob("run-tests-process-*.json")
                  if not p.name.endswith(".worker.json")]
        self.assertEqual(len(traces), 1)
        trace = json.loads(traces[0].read_text(encoding="utf-8"))
        self.assertTrue(trace["waiter_done"])
        self.assertEqual(trace["outcome"], "cancelled")
        if sys.platform == "win32":
            self.assertTrue(trace["tree_empty"])
        self.assertFalse(any(process_is_running(pid) for pid in pids + [trace["supervisor_pid"]]))
        self.assertEqual(len(provider.requests), 1)
        self.observation = {"resource": "real_process_tree", "status": result.status,
                            "parent_and_descendant_stopped": True, "process_waiter_done": True,
                            "second_tool_not_started": True}

    async def check_edit(self, during_write):
        target = self.root / "value.py"
        target.write_bytes(b"value = 10\n")
        editor = EditFileExecutor(EditPolicy(self.root, ["value.py"]))
        provider = MockProvider([Message("assistant", "编辑", [
            ToolCall("edit_001", "edit_file", {
                "path": "value.py", "old_text": "value = 10", "new_text": "value = 20"}),
            ToolCall("edit_002", "edit_file", {
                "path": "value.py", "old_text": "value = 20", "new_text": "value = 30"}),
        ])])
        store = SessionStore(self.root / "edit.jsonl")
        started, notified = asyncio.Event(), asyncio.Event()
        release, worker_finished = Event(), Event()
        loop = asyncio.get_running_loop()
        calls = []
        real_apply, real_prepare = editor.apply_edit, editor.prepare_edit
        real_write, real_cancel = Path.write_bytes, FileCancellation.request_cancel
        def pause():
            loop.call_soon_threadsafe(started.set)
            if not release.wait(8):
                raise RuntimeError("受控编辑门闩超时")
        def track_apply(*args, **kwargs):
            calls.append(args)
            try:
                return real_apply(*args, **kwargs)
            finally:
                worker_finished.set()
        def prepare_then_pause(*args):
            prepared = real_prepare(*args)
            if not during_write:
                pause()
            return prepared
        def controlled_write(path, data):
            if path != target or not during_write:
                return real_write(path, data)
            middle = len(data) // 2
            with path.open("wb") as stream:
                first = stream.write(data[:middle])
                stream.flush()
                pause()
                return first + stream.write(data[middle:])
        def notify(control):
            real_cancel(control)
            loop.call_soon_threadsafe(notified.set)
        with patch.object(editor, "apply_edit", side_effect=track_apply), \
             patch.object(editor, "prepare_edit", side_effect=prepare_then_pause), \
             patch.object(Path, "write_bytes", new=controlled_write), \
             patch.object(FileCancellation, "request_cancel", new=notify):
            agent, pending = self.submit(provider, editor, [editor.definition], store)
            waiter = asyncio.create_task(agent.wait_for_idle())
            try:
                async with asyncio.timeout(5):
                    await started.wait()
                    agent.abort()
                    await notified.wait()
                agent.abort()
                self.assertTrue(agent.is_running)
                self.assertFalse(worker_finished.is_set())
                self.assertFalse(waiter.done())
                self.assertFalse(pending.done())
                with self.assertRaises(RuntimeError):
                    agent.prompt([Message("user", "B")])
                self.assertFalse(any(r["type"] == "run_end" for r in store.load().records))
            finally:
                release.set()
                async with asyncio.timeout(10):
                    await waiter
                    result = await pending
        self.assert_cancelled_record(agent, result, store)
        self.assertTrue(worker_finished.is_set())
        expected = b"value = 20\n" if during_write else b"value = 10\n"
        self.assertEqual(target.read_bytes(), expected)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(provider.requests), 1)
        self.observation = {"resource": "edit_during_write" if during_write else "edit_before_write",
                            "status": result.status, "busy_until_worker_finished": True,
                            "idle_after_worker_finished": True, "second_edit_not_started": True,
                            "file_changed": during_write}

    async def test_edit_before_write_does_not_release_before_thread_finishes(self):
        await self.check_edit(False)

    async def test_edit_in_write_waits_and_preserves_already_permitted_change(self):
        await self.check_edit(True)


if __name__ == "__main__":
    unittest.main()
