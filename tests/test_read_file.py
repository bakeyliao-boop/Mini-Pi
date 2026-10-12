"""用实际文件验证读取结果，并检查非法输入不触发文件读取。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.models import ToolCall
from mini_pi.tools.read_file import ReadFileExecutor


class ReadFileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        test_parent = Path(__file__).resolve().parent
        self.temp = TemporaryDirectory(prefix="_read_file_", dir=test_parent)
        self.root = Path(self.temp.name).resolve()
        self.root.relative_to(test_parent)
        self.addCleanup(self.temp.cleanup)
        self.workdir = self.root / "workspace"
        self.workdir.mkdir()
        self.executor = ReadFileExecutor(self.workdir)

    async def test_reads_buggy_code_without_marking_read_as_failure(self):
        source = "def final_price(price, discount_rate):\n    return price * discount_rate\n"
        (self.workdir / "discount.py").write_text(source, encoding="utf-8")
        call = ToolCall("call_001", "read_file", {"path": "discount.py"})
        result = await self.executor.execute(call)
        self.assertEqual(result.output, source)
        self.assertIsNone(result.error)
        self.assertEqual(result.tool_call_id, call.id)
        self.assertEqual(result.tool_name, call.name)

    async def test_empty_file_is_a_successful_read(self):
        (self.workdir / "empty.txt").write_text("", encoding="utf-8")
        result = await self.executor.execute(
            ToolCall("call_empty", "read_file", {"path": "empty.txt"})
        )
        self.assertEqual(result.output, "")
        self.assertIsNone(result.error)

    async def test_missing_file_returns_error_with_call_identity(self):
        call = ToolCall("call_missing", "read_file", {"path": "missing.txt"})
        result = await self.executor.execute(call)
        self.assertEqual(result.output, "")
        self.assertIn("文件不存在", result.error or "")
        self.assertEqual(result.tool_call_id, call.id)
        self.assertEqual(result.tool_name, call.name)

    async def test_numeric_path_is_not_coerced_or_read(self):
        (self.workdir / "123").write_text("不应读取这个文件", encoding="utf-8")
        call = ToolCall("call_invalid", "read_file", {"path": 123})
        with patch("pathlib.Path.read_text") as read_text:
            result = await self.executor.execute(call)
        read_text.assert_not_called()
        self.assertIn("path 必须是非空字符串", result.error or "")
        self.assertEqual(result.output, "")
        self.assertEqual(result.tool_call_id, call.id)
        self.assertEqual(result.tool_name, call.name)

    async def test_path_escape_is_rejected_before_reading(self):
        (self.root / "outside.txt").write_text("目录外的内容", encoding="utf-8")
        call = ToolCall("call_outside", "read_file", {"path": "../outside.txt"})
        with patch("pathlib.Path.read_text") as read_text:
            result = await self.executor.execute(call)
        read_text.assert_not_called()
        self.assertIsNotNone(result.error)
        self.assertEqual(result.output, "")


if __name__ == "__main__":
    unittest.main()
