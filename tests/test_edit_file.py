"""D08：先验证唯一定位；后续加入实际写入与路径权限用例。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mini_pi.tools.edit_file import find_unique_match, replace_unique_text
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy


class UniqueMatchTests(unittest.TestCase):
    def test_unique_match_returns_character_position_including_zero(self):
        for content, old_text, expected in (("abc", "a", 0), ("abc", "b", 1)):
            with self.subTest(content=content, old_text=old_text):
                self.assertEqual(find_unique_match(content, old_text), expected)

    def test_missing_text_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未找到"):
            find_unique_match("abc", "x")

    def test_duplicate_text_in_different_functions_is_rejected(self):
        content = (
            "def discount_amount(price, rate):\n    return price * rate\n\n"
            "def final_price(price, rate):\n    return price * rate\n"
        )
        with self.assertRaisesRegex(ValueError, "多处"):
            find_unique_match(content, "return price * rate")

    def test_overlapping_matches_are_also_rejected(self):
        with self.assertRaisesRegex(ValueError, "多处"):
            find_unique_match("aaa", "aa")

    def test_empty_old_text_is_rejected(self):
        with self.assertRaises(ValueError):
            find_unique_match("abc", "")


class TextReplacementTests(unittest.TestCase):
    def test_replaces_only_the_uniquely_identified_function(self):
        first = "def discount_amount(price, rate):\n    return price * rate\n\n"
        old = "def final_price(price, rate):\n    return price * rate"
        new = "def final_price(price, rate):\n    return price * (1 - rate)"
        self.assertEqual(replace_unique_text(first + old + "\n", old, new), first + new + "\n")

    def test_boundaries_deletion_and_surrounding_text_are_preserved(self):
        cases = (
            ("abc", "a", "X", "Xbc"),
            ("abc", "c", "X", "abX"),
            ("abc", "abc", "X", "X"),
            ("abc", "b", "XYZ", "aXYZc"),
            ("abc", "b", "", "ac"),
            ("左旧右", "旧", "新", "左新右"),
            ("head\r\nold\r\ntail", "old", "new", "head\r\nnew\r\ntail"),
        )
        for content, old, new, expected in cases:
            with self.subTest(content=content, old=old, new=new):
                self.assertEqual(replace_unique_text(content, old, new), expected)

    def test_missing_ambiguous_and_empty_matches_block_replacement(self):
        for content, old in (("abc", "x"), ("abcabc", "abc"), ("aaa", "aa"), ("abc", "")):
            with self.subTest(content=content, old=old):
                with self.assertRaises(ValueError):
                    replace_unique_text(content, old, "new")


class EditPathTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parent
        self.temp = TemporaryDirectory(prefix="_edit_path_", dir=parent)
        self.root = Path(self.temp.name).resolve()
        self.root.relative_to(parent)
        self.addCleanup(self.temp.cleanup)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "discount.py").write_bytes(b"return price * rate\n")
        (self.root / "outside.py").write_bytes(b"outside fixture\n")
        self.executor = EditFileExecutor(EditPolicy(self.workspace, ["discount.py"]))

    def test_allowed_path_resolves_to_the_workspace_file(self):
        self.assertEqual(
            self.executor.resolve_edit_path("discount.py"),
            (self.workspace / "discount.py").resolve(),
        )

    def test_existing_file_outside_allow_list_is_rejected(self):
        (self.workspace / "settings.py").write_bytes(b"settings fixture\n")
        with self.assertRaisesRegex(ValueError, "清单"):
            self.executor.resolve_edit_path("settings.py")

    def test_parent_directory_escape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "之外"):
            self.executor.resolve_edit_path("../outside.py")

    def test_absolute_path_is_rejected_even_for_an_allowed_file(self):
        with self.assertRaisesRegex(ValueError, "相对路径"):
            self.executor.resolve_edit_path(str(self.workspace / "discount.py"))

    def test_symlink_to_outside_workspace_is_rejected(self):
        link = self.workspace / "alias.py"
        try:
            link.symlink_to(self.root / "outside.py")
        except (OSError, NotImplementedError) as error:
            self.skipTest(
                f"当前环境不能创建符号链接：{type(error).__name__}"
                f"，winerror={getattr(error, 'winerror', None)}"
            )
        executor = EditFileExecutor(EditPolicy(self.workspace, ["alias.py"]))
        with self.assertRaisesRegex(ValueError, "之外"):
            executor.resolve_edit_path("alias.py")


if __name__ == "__main__":
    unittest.main()
