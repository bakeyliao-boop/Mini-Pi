"""D09：用临时目录验证列表输出、截断和路径边界。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.models import ToolCall
from mini_pi.tools.list_files import ListFilesExecutor


class ListFilesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        test_parent = Path(__file__).resolve().parent
        self.temp = TemporaryDirectory(prefix="_list_files_", dir=test_parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workdir = self.root / "workspace"
        self.workdir.mkdir()
        self.executor = ListFilesExecutor(self.workdir)

    async def test_default_path_sorts_entries_and_marks_directories(self):
        (self.workdir / "z.txt").write_text("z", encoding="utf-8")
        (self.workdir / ".hidden").write_text("h", encoding="utf-8")
        (self.workdir / "a_dir").mkdir()
        call = ToolCall("call_list", "list_files", {})

        result = await self.executor.execute(call)

        self.assertEqual(result.output, ".hidden\na_dir/\nz.txt")
        self.assertIsNone(result.error)
        self.assertEqual((result.tool_call_id, result.tool_name), (call.id, call.name))
        empty = await self.executor.execute(
            ToolCall("call_empty_dir", "list_files", {"path": "a_dir"})
        )
        self.assertEqual(empty.output, "(empty directory)")
        self.assertIsNone(empty.error)

    async def test_limit_reports_omitted_entries(self):
        for name in ("a.txt", "b.txt", "c.txt"):
            (self.workdir / name).write_text(name, encoding="utf-8")
        result = await self.executor.execute(
            ToolCall("call_limited", "list_files", {"limit": 1})
        )

        self.assertEqual(result.output, "a.txt\n[已截断：仅显示前 1 项，共 3 项]")
        self.assertIsNone(result.error)

    async def test_invalid_and_outside_paths_do_not_list_directory(self):
        (self.root / "outside").mkdir()
        for arguments in ({"path": "../outside"}, {"limit": True}, {"extra": 1}):
            with self.subTest(arguments=arguments):
                call = ToolCall("call_bad", "list_files", arguments)
                with patch("pathlib.Path.iterdir") as iterdir:
                    result = await self.executor.execute(call)
                iterdir.assert_not_called()
                self.assertEqual(result.output, "")
                self.assertIsNotNone(result.error)
                self.assertEqual(result.tool_call_id, call.id)

    async def test_missing_path_and_regular_file_return_execution_errors(self):
        (self.workdir / "file.txt").write_text("x", encoding="utf-8")
        for path in ("missing", "file.txt"):
            with self.subTest(path=path):
                result = await self.executor.execute(
                    ToolCall("call_error", "list_files", {"path": path})
                )
                self.assertEqual(result.output, "")
                self.assertIn("执行失败", result.error or "")


if __name__ == "__main__":
    unittest.main()
