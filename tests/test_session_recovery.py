"""D11：通过实际 JSONL 核对待确认调用，检查阶段不执行工具。"""

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_recovery import PendingCall, find_pending_calls
from mini_pi.session_store import SessionStore
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.list_files import ListFilesExecutor
from mini_pi.tools.read_file import ReadFileExecutor
from mini_pi.tools.run_tests import RunTestsExecutor
from mini_pi.tools.tool_router import ToolRouter


class SessionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(
            prefix="_recovery_", dir=Path(__file__).resolve().parent,
        )
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "session.jsonl"

    def _write_items(self, items):
        """准备真实记录；这些消息不触发任何工具执行。"""
        self.path.write_text("", encoding="utf-8")
        for run_id, item in items:
            SessionStore(self.path, run_id).append_item(item)

    def _inspect(self, expected_error=None):
        """加载及检查保持磁盘内容不变，且不得调用执行器。"""
        before = self.path.read_bytes()
        with ExitStack() as stack:
            executors = [
                stack.enter_context(patch.object(executor, "execute"))
                for executor in (
                    ToolRouter, ReadFileExecutor, EditFileExecutor,
                    ListFilesExecutor, RunTestsExecutor,
                )
            ]
            loaded = SessionStore(self.path, "inspection_run").load()
            if expected_error is None:
                pending = find_pending_calls(loaded)
            else:
                with self.assertRaisesRegex(ValueError, expected_error):
                    find_pending_calls(loaded)
                pending = None
            for execute in executors:
                execute.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)
        return pending

    def test_completed_success_and_error_results_leave_only_unconfirmed_edit(self):
        successful_read = ToolCall("call_001", "read_file", {"path": "discount.py"})
        failed_read = ToolCall("call_002", "read_file", {"path": "missing.py"})
        pending_edit = ToolCall("call_003", "edit_file", {
            "path": "discount.py", "old_text": "old", "new_text": "new",
        })
        self._write_items([
            ("run_A", Message("user", "检查并修改文件。")),
            ("run_A", Message("assistant", "提出三个调用。", [
                successful_read, failed_read, pending_edit,
            ])),
            ("run_A", ToolResult("call_001", "read_file", "旧文件内容")),
            ("run_A", ToolResult("call_002", "read_file", "", "文件不存在")),
        ])
        # 结束事件不能补上编辑请求缺失的执行结果。
        SessionStore(self.path, "run_A").append_entry("run_end", {
            "status": "finished", "task_passed": None, "error": None,
        })
        self.assertEqual(self._inspect(), [PendingCall("run_A", pending_edit)])

    def test_reused_call_id_in_another_run_cannot_complete_previous_edit(self):
        pending_edit = ToolCall("call_001", "edit_file", {
            "path": "discount.py", "old_text": "old", "new_text": "new",
        })
        later_read = ToolCall("call_001", "read_file", {"path": "discount.py"})
        self._write_items([
            ("run_A", Message("assistant", "上次编辑结果未记录。", [pending_edit])),
            ("run_B", Message("assistant", "本次读取文件。", [later_read])),
            ("run_B", ToolResult("call_001", "read_file", "本次读取的内容")),
        ])
        self.assertEqual(self._inspect(), [PendingCall("run_A", pending_edit)])

    def test_orphan_wrong_name_early_and_cross_run_results_are_rejected(self):
        call = ToolCall("call_001", "edit_file", {"path": "discount.py"})
        request = Message("assistant", "编辑请求。", [call])
        result = ToolResult("call_001", "edit_file", "编辑反馈")
        cases = {
            "孤立结果": (
                [("run_A", result)], "没有前置请求",
            ),
            "工具名错配": (
                [
                    ("run_A", request),
                    ("run_A", ToolResult("call_001", "read_file", "读取内容")),
                ], "工具名不匹配",
            ),
            "结果先于请求": (
                [("run_A", result), ("run_A", request)], "没有前置请求",
            ),
            "结果来自另一运行": (
                [("run_A", request), ("run_B", result)], "没有前置请求",
            ),
        }
        for scenario, (items, error) in cases.items():
            with self.subTest(scenario=scenario):
                self._write_items(items)
                self._inspect(
                    rf"第 [0-9]+ 条记录.*运行 run_[AB].*call_001.*{error}",
                )

    def test_duplicate_requests_and_results_are_rejected_without_hiding_edits(self):
        edit = ToolCall("call_001", "edit_file", {"path": "discount.py"})
        same_id_read = ToolCall("call_001", "read_file", {"path": "discount.py"})
        edit_request = Message("assistant", "编辑请求。", [edit])
        read_request = Message("assistant", "复用 ID 的读取请求。", [same_id_read])
        result = ToolResult("call_001", "edit_file", "编辑反馈")
        cases = {
            "同一消息中重复请求": [
                ("run_A", Message("assistant", "两个请求复用 ID。", [edit, same_id_read])),
            ],
            "未完成请求被后续请求覆盖": [
                ("run_A", edit_request), ("run_A", read_request),
            ],
            "已完成后再次复用请求 ID": [
                ("run_A", edit_request), ("run_A", result), ("run_A", read_request),
            ],
            "结果重复": [
                ("run_A", edit_request), ("run_A", result), ("run_A", result),
            ],
        }
        for scenario, items in cases.items():
            with self.subTest(scenario=scenario):
                self._write_items(items)
                self._inspect(r"第 [0-9]+ 条记录.*运行 run_A.*call_001.*重复")


if __name__ == "__main__":
    unittest.main()
