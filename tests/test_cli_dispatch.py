"""CLI分流使用真实Harness与临时JSONL，不请求外部模型。"""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from mini_pi.bootstrap import build_tools
from mini_pi.cli import run_command
from mini_pi.harness import Harness, RunBudget
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore


class CliDispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="_cli_", dir=Path(__file__).parent)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        (self.root / "sample.txt").write_text("real file", encoding="utf-8")
        self.tools = build_tools(self.root, ["sample.txt"],
            (sys.executable, "-c", "raise SystemExit(0)"), self.root / "evidence")
        self.path = self.root / "session.jsonl"

    def seed(self, pending=False):
        store = SessionStore(self.path, "old")
        store.append_entry("run_start", {"status": "running"})
        store.append_item(Message("user", "旧任务"))
        if pending:
            store.append_item(Message("assistant", "待核对", [ToolCall("pending", "edit_file", {})]))
        else:
            store.append_item(Message("assistant", "旧回答"))
            store.append_entry("run_end", {"status": "finished"})
        return self.path.read_bytes()

    async def test_new_command_real_read_returns_actual_status_and_path(self):
        provider = MockProvider([
            Message("assistant", "读", [ToolCall("r1", "read_file", {"path": "sample.txt"})]),
            Message("assistant", "完成", stop_reason="stop")])
        harness = Harness(provider, self.tools)
        outcome = await run_command(harness, "读取", self.path)
        self.assertEqual(outcome.status, "finished")
        self.assertEqual(outcome.session_path, self.path)
        self.assertEqual(SessionStore(self.path).load().history, outcome.run_result.messages)
        self.assertEqual([x.output for x in outcome.run_result.messages if isinstance(x, ToolResult)], ["real file"])
        self.assertFalse(harness.agent.is_running)

    async def test_ready_resume_preserves_old_prefix_and_uses_new_run_id(self):
        before = self.seed()
        provider = MockProvider([Message("assistant", "新回答", stop_reason="stop")])
        outcome = await run_command(Harness(provider, self.tools), "继续", self.path, resume=True)
        self.assertEqual(outcome.status, "finished")
        self.assertTrue(self.path.read_bytes().startswith(before))
        loaded = SessionStore(self.path).load()
        self.assertEqual(len({r["run_id"] for r in loaded.records}), 2)
        self.assertEqual(provider.requests[0], [Message("user", "旧任务"), Message("assistant", "旧回答"), Message("user", "继续")])

    async def test_blocked_resume_reports_gate_without_model_or_append(self):
        before = self.seed(pending=True)
        provider = MockProvider([])
        outcome = await run_command(Harness(provider, self.tools), "继续", self.path, resume=True)
        self.assertEqual(outcome.status, "needs_review")
        self.assertIsNone(outcome.run_result)
        self.assertEqual(outcome.session_path, self.path)
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.path.read_bytes(), before)

    async def test_existing_path_is_not_implicitly_resumed(self):
        before = self.seed()
        provider = MockProvider([])
        with self.assertRaises(FileExistsError):
            await run_command(Harness(provider, self.tools), "新任务", self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(provider.requests, [])

    async def test_reports_budget_exhausted_instead_of_success(self):
        provider = MockProvider([Message("assistant", "读", [ToolCall("r1", "read_file", {"path": "sample.txt"})])])
        harness = Harness(provider, self.tools, budget=RunBudget(max_model_turns=1))
        outcome = await run_command(harness, "读取", self.path)
        self.assertEqual(outcome.status, "budget_exhausted")
        self.assertEqual(outcome.status, outcome.run_result.status)
        self.assertEqual(SessionStore(self.path).load().records[-1]["data"]["status"], outcome.status)

    async def test_missing_resume_path_is_not_created(self):
        provider = MockProvider([])
        with self.assertRaises(FileNotFoundError):
            await run_command(Harness(provider, self.tools), "继续", self.path, resume=True)
        self.assertFalse(self.path.exists())
        self.assertEqual(provider.requests, [])
