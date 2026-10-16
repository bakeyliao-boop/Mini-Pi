"""D12：真实临时文件的同步编辑检查点；不代表异步取消链已接通。

本组验证 apply_edit 已接入的 cancellation 参数和同步检查点。
写入前/后通过包装真实方法登记取消，不模拟文件内容或写入结果。
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.file_cancellation import FileCancellation, FileOperationCancelled
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy


class EditCancelPointTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_edit_cancel_", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / "value.py"
        self.target.write_bytes(b"value = 10\n")
        self.editor = EditFileExecutor(EditPolicy(self.root, ["value.py"]))
        self.cancellation = FileCancellation()

    def apply(self):
        return self.editor.apply_edit(
            "value.py", "value = 10", "value = 20", cancellation=self.cancellation,
        )

    def test_normal_edit_writes_actual_file_and_returns_before_after(self):
        target, before, after = self.apply()
        self.assertEqual(target, self.target.resolve())
        self.assertEqual(before, "value = 10\n")
        self.assertEqual(after, "value = 20\n")
        self.assertEqual(self.target.read_bytes(), b"value = 20\n")

    def test_cancel_before_preparation_does_not_start_preparation(self):
        self.cancellation.request_cancel()
        with patch.object(self.editor, "prepare_edit", wraps=self.editor.prepare_edit) as prepare:
            with self.assertRaises(FileOperationCancelled):
                self.apply()
        prepare.assert_not_called()
        self.assertEqual(self.target.read_bytes(), b"value = 10\n")

    def test_cancel_after_real_preparation_prevents_write(self):
        real_prepare = self.editor.prepare_edit

        def prepare_then_cancel(*args):
            prepared = real_prepare(*args)
            self.cancellation.request_cancel()
            return prepared

        with patch.object(self.editor, "prepare_edit", side_effect=prepare_then_cancel):
            with self.assertRaises(FileOperationCancelled):
                self.apply()
        self.assertEqual(self.target.read_bytes(), b"value = 10\n")

    def test_cancel_after_write_permission_does_not_revoke_permission(self):
        # 许可是逻辑边界，不声称取消与操作系统实际启动写入能够原子化。
        real_begin_write = self.cancellation.begin_write

        def allow_then_cancel():
            real_begin_write()
            self.cancellation.request_cancel()

        with patch.object(self.cancellation, "begin_write", side_effect=allow_then_cancel):
            with self.assertRaises(FileOperationCancelled):
                self.apply()
        self.assertEqual(self.target.read_bytes(), b"value = 20\n")

    def test_cancel_observed_after_actual_write_preserves_change(self):
        real_write = Path.write_bytes

        def write_then_cancel(path, data):
            written = real_write(path, data)
            self.cancellation.request_cancel()
            return written

        with patch.object(Path, "write_bytes", new=write_then_cancel):
            with self.assertRaises(FileOperationCancelled):
                self.apply()
        self.assertEqual(self.target.read_bytes(), b"value = 20\n")


if __name__ == "__main__":
    unittest.main()
