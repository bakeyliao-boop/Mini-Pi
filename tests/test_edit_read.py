"""D08：编辑前读取验证；读取核心由学习者完成后运行。"""

import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy


class EditReadTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parent
        self.temp = TemporaryDirectory(prefix="_edit_read_", dir=parent)
        self.workspace = Path(self.temp.name).resolve()
        self.workspace.relative_to(parent)
        self.addCleanup(self.temp.cleanup)
        self.target = self.workspace / "discount.py"
        self.original = b"return price * rate\n"
        self.target.write_bytes(self.original)
        self.executor = EditFileExecutor(EditPolicy(self.workspace, ["discount.py"]))

    def test_utf8_text_line_endings_and_bom_are_read_without_changes(self):
        cases = (
            "中文内容\nreturn price * rate\n",
            "中文内容\r\nreturn price * rate\r\n",
            "first\r\nsecond\nthird\r",
            "\ufeffreturn price * rate\r\n",
        )
        for content in cases:
            with self.subTest(content=repr(content)):
                original = content.encode("utf-8")
                self.target.write_bytes(original)
                target, actual = self.executor.read_editable_file("discount.py")
                self.assertEqual(target, self.target.resolve())
                self.assertEqual(actual, content)
                self.assertEqual(self.target.read_bytes(), original)

    def test_unlisted_file_is_rejected_before_its_content_is_read(self):
        secret = self.workspace / "credentials.yaml"
        secret.write_bytes(b"private fixture\n")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("拒绝范围时不应读取内容")):
            with self.assertRaisesRegex(ValueError, "清单"):
                self.executor.read_editable_file("credentials.yaml")

    def test_read_only_file_is_rejected_before_its_content_is_read(self):
        original_mode = self.target.stat().st_mode
        try:
            self.target.chmod(stat.S_IREAD)
            if os.access(self.target, os.R_OK | os.W_OK):
                self.skipTest("当前进程仍有读写权限，不能验证真实权限拒绝")
            with patch.object(Path, "read_bytes", side_effect=AssertionError("编辑前应先拒绝只读目标")):
                with self.assertRaises(PermissionError):
                    self.executor.read_editable_file("discount.py")
            self.assertEqual(self.target.read_bytes(), self.original)
        finally:
            self.target.chmod(original_mode)

    def test_invalid_utf8_is_reported_without_changing_the_file(self):
        original = b"\xff\xfe\x00"
        self.target.write_bytes(original)
        with self.assertRaises(UnicodeDecodeError):
            self.executor.read_editable_file("discount.py")
        self.assertEqual(self.target.read_bytes(), original)

    def test_read_failure_after_precheck_is_propagated(self):
        # 模拟实际读取时的拒绝；没有修改 ACL，不声称真实权限变化。
        with patch.object(Path, "read_bytes", side_effect=PermissionError("模拟读取时权限变化")):
            with self.assertRaises(PermissionError):
                self.executor.read_editable_file("discount.py")
        self.assertEqual(self.target.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
