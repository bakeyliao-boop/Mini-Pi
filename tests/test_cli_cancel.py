"""入口取消须等待实际运行及结束回调，重复取消不截断收尾。"""

import asyncio
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.bootstrap import build_tools
from mini_pi.cli import parse_command_args, run_command_safely
from mini_pi.harness import Harness
from mini_pi.models import Message
from mini_pi.session_store import SessionStore


class CliArgumentTests(unittest.TestCase):
    def test_parse_new_and_resume_without_starting_work(self):
        for resume in (False, True):
            argv = ["继续检查", "--session", "my session.jsonl"] + (["--resume"] if resume else [])
            options = parse_command_args(argv)
            self.assertEqual(options.text, "继续检查")
            self.assertEqual(options.session, Path("my session.jsonl"))
            self.assertEqual(options.resume, resume)

    def test_missing_path_and_unknown_option_are_rejected(self):
        for argv in (["任务"], ["任务", "--session", "a.jsonl", "--unknown"]):
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
                parse_command_args(argv)
            self.assertEqual(raised.exception.code, 2)


class CliCancelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="_cancel_cli_", dir=Path(__file__).parent)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        (self.root / "sample.txt").write_text("unchanged", encoding="utf-8")
        self.tools = build_tools(self.root, ["sample.txt"],
            (sys.executable, "-c", "raise SystemExit(0)"), self.root / "evidence")

    async def test_both_entries_cancel_model_then_wait_for_hook_even_if_cancelled_twice(self):
        for resume in (False, True):
            with self.subTest(resume=resume):
                path = self.root / ("resume.jsonl" if resume else "new.jsonl")
                if resume:
                    old = SessionStore(path, "old")
                    old.append_entry("run_start", {"status": "running"})
                    old.append_item(Message("user", "旧问题"))
                    old.append_item(Message("assistant", "旧回答"))
                    old.append_entry("run_end", {"status": "finished"})
                entered, model_cleaned = asyncio.Event(), asyncio.Event()
                closing, release = asyncio.Event(), asyncio.Event()
                class Provider:
                    async def generate(self, history, tools):
                        entered.set()
                        try:
                            await asyncio.Event().wait()
                        finally:
                            model_cleaned.set()
                async def hook(result, error):
                    closing.set()
                    await release.wait()
                harness = Harness(Provider(), self.tools, on_run_end=hook)
                task = asyncio.create_task(run_command_safely(harness, "继续", path, resume=resume))
                try:
                    await asyncio.wait_for(entered.wait(), 0.5)
                    task.cancel()
                    await asyncio.wait_for(closing.wait(), 0.5)
                    self.assertTrue(model_cleaned.is_set())
                    self.assertTrue(harness.agent.is_running)
                    self.assertFalse(task.done())
                    task.cancel()
                    await asyncio.sleep(0)
                    self.assertFalse(task.done())
                    release.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await asyncio.wait_for(asyncio.shield(task), 0.5)
                    self.assertFalse(harness.agent.is_running)
                    self.assertEqual(SessionStore(path).load().records[-1]["data"]["status"], "cancelled")
                finally:
                    release.set()
                    harness.agent.abort()
                    await asyncio.gather(task, return_exceptions=True)
                    await harness.agent.wait_for_idle()

    async def test_busy_rejection_does_not_abort_existing_task(self):
        entered, release = asyncio.Event(), asyncio.Event()
        class Provider:
            async def generate(self, history, tools):
                entered.set()
                await release.wait()
                return Message("assistant", "完成", stop_reason="stop")
        harness = Harness(Provider(), self.tools)
        first = harness.run("A", SessionStore(self.root / "A.jsonl"))
        try:
            await entered.wait()
            with patch.object(harness.agent, "abort", wraps=harness.agent.abort) as abort:
                with self.assertRaisesRegex(RuntimeError, "Harness已有活动运行"):
                    await run_command_safely(harness, "B", self.root / "B.jsonl")
                abort.assert_not_called()
            self.assertTrue(harness.agent.is_running)
            self.assertFalse((self.root / "B.jsonl").exists())
        finally:
            release.set()
            await first

    async def test_normal_completion_returns_result_without_abort(self):
        class Provider:
            async def generate(self, history, tools):
                return Message("assistant", "完成", stop_reason="stop")
        harness = Harness(Provider(), self.tools)
        with patch.object(harness.agent, "abort", wraps=harness.agent.abort) as abort:
            outcome = await run_command_safely(harness, "任务", self.root / "normal.jsonl")
            self.assertEqual(outcome.status, "finished")
            abort.assert_not_called()
