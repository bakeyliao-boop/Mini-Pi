"""D08：实际写入验证，仅修改本测试创建的临时文件。"""

import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy


class EditWriteTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parent
        self.temp = TemporaryDirectory(prefix="_edit_write_", dir=parent)
        self.workspace = Path(self.temp.name).resolve()
        self.workspace.relative_to(parent)
        self.addCleanup(self.temp.cleanup)
        self.target = self.workspace / "discount.py"
        self.first = "def discount_amount(price, rate):\n    return price * rate\n\n"
        self.old = "def final_price(price, rate):\n    return price * rate"
        self.new = "def final_price(price, rate):\n    return price * (1 - rate)"
        self.original = (self.first + self.old + "\n").encode("utf-8")
        self.target.write_bytes(self.original)
        self.executor = EditFileExecutor(EditPolicy(self.workspace, ["discount.py"]))

    def test_unique_edit_is_actually_written_and_other_function_is_preserved(self):
        target, before, after = self.executor.apply_edit("discount.py", self.old, self.new)
        expected = self.first + self.new + "\n"
        self.assertEqual(target, self.target.resolve())
        self.assertEqual(before, self.original.decode("utf-8"))
        self.assertEqual(after, expected)
        self.assertEqual(self.target.read_bytes(), expected.encode("utf-8"))

    def test_scope_and_matching_failures_leave_files_unchanged(self):
        unlisted = self.workspace / "settings.py"
        unlisted.write_bytes(self.original)
        cases = (
            ("settings.py", self.old, self.new),
            ("discount.py", "missing text", "replacement"),
            ("discount.py", "return price * rate", "replacement"),
            ("discount.py", "", "replacement"),
            ("discount.py", self.old, self.old),
        )
        for path, old, new in cases:
            with self.subTest(path=path, old=old):
                with self.assertRaises(ValueError):
                    self.executor.apply_edit(path, old, new)
                self.assertEqual(self.target.read_bytes(), self.original)
                self.assertEqual(unlisted.read_bytes(), self.original)

    def test_read_only_target_is_not_modified(self):
        original_mode = self.target.stat().st_mode
        try:
            self.target.chmod(stat.S_IREAD)
            if os.access(self.target, os.R_OK | os.W_OK):
                self.skipTest("当前进程仍有读写权限，不能验证真实权限拒绝")
            with self.assertRaises(PermissionError):
                self.executor.apply_edit("discount.py", self.old, self.new)
            self.assertEqual(self.target.read_bytes(), self.original)
        finally:
            self.target.chmod(original_mode)

    def test_actual_write_refusal_is_propagated(self):
        # 模拟写入开始前的拒绝，不声称验证了真实 ACL 变化或部分写入恢复。
        with patch.object(Path, "write_bytes", side_effect=PermissionError("模拟实际写入拒绝")):
            with self.assertRaises(PermissionError):
                self.executor.apply_edit("discount.py", self.old, self.new)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_written_utf8_bytes_preserve_surroundings_and_support_deletion(self):
        cases = (
            ("中文\nold\ntail\n", "old", "new", "中文\nnew\ntail\n"),
            ("中文\r\nold\r\ntail\r\n", "old", "new", "中文\r\nnew\r\ntail\r\n"),
            ("\ufeffhead\r\nold\r\ntail\n", "old", "new", "\ufeffhead\r\nnew\r\ntail\n"),
            ("old", "old", "new", "new"),
            ("old", "old", "", ""),
        )
        for content, old, new, expected in cases:
            with self.subTest(content=repr(content), new=new):
                self.target.write_bytes(content.encode("utf-8"))
                target, before, after = self.executor.apply_edit("discount.py", old, new)
                self.assertEqual(target, self.target.resolve())
                self.assertEqual(before, content)
                self.assertEqual(after, expected)
                self.assertEqual(self.target.read_bytes(), expected.encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
