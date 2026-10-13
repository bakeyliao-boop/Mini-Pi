"""D08：编辑准备验证；实际读取文件，只生成新文本，不写回。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy


class EditPrepareTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parent
        self.temp = TemporaryDirectory(prefix="_edit_prepare_", dir=parent)
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

    def test_unique_edit_is_prepared_without_changing_the_file(self):
        target, before, after = self.executor.prepare_edit("discount.py", self.old, self.new)
        self.assertEqual(target, self.target.resolve())
        self.assertEqual(before, self.original.decode("utf-8"))
        self.assertEqual(after, self.first + self.new + "\n")
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_missing_duplicate_and_empty_matches_are_rejected_without_writes(self):
        for old in ("missing text", "return price * rate", ""):
            with self.subTest(old=old):
                with self.assertRaises(ValueError):
                    self.executor.prepare_edit("discount.py", old, "replacement")
                self.assertEqual(self.target.read_bytes(), self.original)

    def test_unchanged_edit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "没有变化"):
            self.executor.prepare_edit("discount.py", self.old, self.old)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_prepared_text_preserves_surrounding_line_endings_and_bom(self):
        for content in ("head\nold\ntail\n", "head\r\nold\r\ntail\r\n", "\ufeffhead\r\nold\r\ntail\n"):
            with self.subTest(content=repr(content)):
                original = content.encode("utf-8")
                self.target.write_bytes(original)
                target, before, after = self.executor.prepare_edit("discount.py", "old", "new")
                self.assertEqual(target, self.target.resolve())
                self.assertEqual(before, content)
                self.assertEqual(after, content.replace("old", "new"))
                self.assertEqual(self.target.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
