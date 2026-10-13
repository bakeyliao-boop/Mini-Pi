"""D08：读写预检查验证；核心方法由学习者完成后运行。"""

import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest

from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy


class EditAccessTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parent
        self.temp = TemporaryDirectory(prefix="_edit_access_", dir=parent)
        self.workspace = Path(self.temp.name).resolve()
        self.workspace.relative_to(parent)
        self.addCleanup(self.temp.cleanup)
        self.target = self.workspace / "discount.py"
        self.original = b"return price * rate\n"
        self.target.write_bytes(self.original)
        policy = EditPolicy(self.workspace, ["discount.py", "missing.py", "nested"])
        self.executor = EditFileExecutor(policy)

    def test_readable_writable_file_passes_without_changing_its_content(self):
        target = self.executor.resolve_edit_path("discount.py")
        self.assertIsNone(self.executor.check_file_access(target))
        self.assertEqual(target.read_bytes(), self.original)

    def test_allowed_but_missing_file_is_rejected(self):
        target = self.executor.resolve_edit_path("missing.py")
        with self.assertRaises(FileNotFoundError):
            self.executor.check_file_access(target)
        self.assertFalse(target.exists())

    def test_allowed_directory_is_rejected(self):
        directory = self.workspace / "nested"
        directory.mkdir()
        target = self.executor.resolve_edit_path("nested")
        with self.assertRaisesRegex(ValueError, "普通文件"):
            self.executor.check_file_access(target)
        self.assertEqual(list(directory.iterdir()), [])

    def test_read_only_file_is_rejected_without_modifying_its_content(self):
        target = self.executor.resolve_edit_path("discount.py")
        original_mode = target.stat().st_mode
        try:
            target.chmod(stat.S_IREAD)
            if os.access(target, os.R_OK | os.W_OK):
                self.skipTest("当前进程仍有读写权限，不能验证真实权限拒绝")
            with self.assertRaises(PermissionError):
                self.executor.check_file_access(target)
            self.assertEqual(target.read_bytes(), self.original)
        finally:
            target.chmod(original_mode)


if __name__ == "__main__":
    unittest.main()
