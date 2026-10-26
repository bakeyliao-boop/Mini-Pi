"""可执行入口退出码、输出、记录一致性及信号收尾；不请求云模型。"""

import argparse
import asyncio
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.cli import CommandResult, _run_in_terminal, command_exit_code, main, parse_command_args
from mini_pi.harness import Harness
from mini_pi.bootstrap import build_tools
from mini_pi.models import Message, RunResult, ToolCall
from mini_pi.session_store import SessionStore


class CliMainTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="_main_cli_", dir=Path(__file__).parent)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.path = self.root / "session.jsonl"
        self.argv = ["任务", "--session", str(self.path), "--workdir", str(self.root)]

    def invoke(self, args):
        output = StringIO()
        with redirect_stdout(output):
            code = main(args)
        return code, json.loads(output.getvalue())

    def test_exit_codes_are_explicit_and_finished_does_not_override_failed_acceptance(self):
        expected = {"finished": 0, "error": 1, "cancelled": 130, "timeout": 124,
                    "budget_exhausted": 3, "needs_review": 4, "read_interrupted": 4}
        for status, code in expected.items():
            with self.subTest(status=status):
                self.assertEqual(command_exit_code(CommandResult(status, self.path, None)), code)
        self.assertEqual(command_exit_code(CommandResult("finished", self.path,
            RunResult("finished", task_passed=False))), 1)
        with self.assertRaises(ValueError):
            command_exit_code(CommandResult("unknown", self.path, None))

    def test_default_mock_main_and_ready_resume(self):
        code, data = self.invoke(self.argv)
        self.assertEqual(code, 0)
        self.assertEqual(data["status"], "finished")
        self.assertEqual(data["session_path"], str(self.path))
        self.assertIsNone(data["task_passed"])
        before = self.path.read_bytes()
        code, data = self.invoke(self.argv + ["--resume"])
        self.assertEqual(code, 0)
        self.assertTrue(self.path.read_bytes().startswith(before))
        self.assertEqual(len({r["run_id"] for r in SessionStore(self.path).load().records}), 2)

    def test_blocked_resume_returns_four_without_append(self):
        store = SessionStore(self.path)
        store.append_item(Message("user", "旧任务"))
        store.append_item(Message("assistant", "待核对", [ToolCall("edit", "edit_file", {})]))
        before = self.path.read_bytes()
        code, data = self.invoke(self.argv + ["--resume"])
        self.assertEqual(code, 4)
        self.assertEqual(data["status"], "needs_review")
        self.assertEqual(self.path.read_bytes(), before)

    def test_existing_path_reports_error_without_append(self):
        self.invoke(self.argv)
        before = self.path.read_bytes()
        code, data = self.invoke(self.argv)
        self.assertEqual(code, 2)
        self.assertEqual(data["status"], "error")
        self.assertEqual(self.path.read_bytes(), before)

    def test_help_and_bad_args_do_not_construct_harness(self):
        for args, expected in ((["--help"], 0), (["任务"], 2), (self.argv + ["--total-timeout", "nan"], 2),
                               (self.argv + ["--max-model-turns", "0"], 2),
                               (self.argv + ["--test-command-json", '"shell command"'], 2)):
            with self.subTest(args=args), patch("mini_pi.cli._build_terminal_harness") as factory:
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
                    main(args)
                self.assertEqual(raised.exception.code, expected)
                factory.assert_not_called()

    def test_qwen_missing_key_fails_before_request_or_session_file(self):
        with patch.dict(os.environ, {}, clear=True), patch("mini_pi.qwen_client.QwenProvider._send") as send:
            code, data = self.invoke(self.argv + ["--provider", "qwen"])
        self.assertEqual(code, 2)
        self.assertEqual(data["status"], "error")
        self.assertFalse(self.path.exists())
        send.assert_not_called()

    def test_python_module_runs_in_real_process(self):
        process = subprocess.run([sys.executable, "-X", "utf8", "-m", "mini_pi", *self.argv],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["status"], "finished")
        self.assertEqual(SessionStore(self.path).load().records[-1]["data"]["status"], "finished")


class TerminalSignalTests(unittest.IsolatedAsyncioTestCase):
    async def test_sigint_cancels_agent_waits_hook_and_restores_handler(self):
        with TemporaryDirectory(prefix="_sig_cli_", dir=Path(__file__).parent) as directory:
            root = Path(directory).resolve()
            (root / "file.txt").write_text("unchanged", encoding="utf-8")
            tools = build_tools(root, ["file.txt"], (sys.executable, "-c", "pass"), root / "evidence")
            entered, cleaned, closing, release = (asyncio.Event() for _ in range(4))
            class Provider:
                async def generate(self, history, tools):
                    entered.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cleaned.set()
            async def hook(result, error):
                closing.set()
                await release.wait()
            harness = Harness(Provider(), tools, on_run_end=hook)
            options = argparse.Namespace(text="任务", session=root / "session.jsonl", resume=False)
            previous = signal.getsignal(signal.SIGINT)
            task = asyncio.create_task(_run_in_terminal(harness, options))
            try:
                await asyncio.wait_for(entered.wait(), 1)
                signal.raise_signal(signal.SIGINT)
                await asyncio.wait_for(closing.wait(), 1)
                self.assertTrue(cleaned.is_set())
                self.assertFalse(task.done())
                signal.raise_signal(signal.SIGINT)
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(asyncio.shield(task), 1)
                self.assertFalse(harness.agent.is_running)
                self.assertEqual(signal.getsignal(signal.SIGINT), previous)
                self.assertEqual(SessionStore(options.session).load().records[-1]["data"]["status"], "cancelled")
            finally:
                release.set()
                harness.agent.abort()
                await asyncio.gather(task, return_exceptions=True)
                await harness.agent.wait_for_idle()
                signal.signal(signal.SIGINT, previous)
