"""D08：策略迁移后的行为验证；路径检查完成后运行，不调用模型服务。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.tools.edit_policy import EditPolicy


class EditPolicyTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parent
        self.temp = TemporaryDirectory(prefix="_edit_policy_", dir=parent)
        self.root = Path(self.temp.name).resolve()
        self.root.relative_to(parent)
        self.addCleanup(self.temp.cleanup)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "discount.py").write_bytes(b"return price * rate\n")
        (self.root / "outside.py").write_bytes(b"outside fixture\n")
        self.policy = EditPolicy(self.workspace, ["discount.py"])

    def test_explicitly_allowed_target_is_returned(self):
        self.assertEqual(
            self.policy.resolve_edit_path("discount.py"),
            (self.workspace / "discount.py").resolve(),
        )

    def test_unlisted_targets_are_rejected_without_classifying_their_names(self):
        for name in ("settings.py", "credentials.yaml", ".env", "AGENTS.md"):
            with self.subTest(name=name):
                target = self.workspace / name
                original = b"unchanged fixture\n"
                target.write_bytes(original)
                with self.assertRaisesRegex(ValueError, "清单"):
                    self.policy.resolve_edit_path(name)
                self.assertEqual(target.read_bytes(), original)

    def test_policy_does_not_hardcode_forbidden_file_names(self):
        target = self.workspace / "AGENTS.md"
        target.write_bytes(b"authorized fixture\n")
        policy = EditPolicy(self.workspace, ["AGENTS.md"])
        self.assertEqual(policy.resolve_edit_path("AGENTS.md"), target.resolve())

    def test_parent_escape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "之外"):
            self.policy.resolve_edit_path("../outside.py")

    def test_absolute_path_is_rejected_even_for_an_allowed_target(self):
        with self.assertRaisesRegex(ValueError, "相对路径"):
            self.policy.resolve_edit_path(str(self.workspace / "discount.py"))

    def test_symbolic_link_to_outside_the_workspace_is_rejected(self):
        link = self.workspace / "alias.py"
        try:
            link.symlink_to(self.root / "outside.py")
        except (OSError, NotImplementedError) as error:
            self.skipTest(
                f"当前环境不能创建符号链接：{type(error).__name__}"
                f"，winerror={getattr(error, 'winerror', None)}"
            )
        policy = EditPolicy(self.workspace, ["alias.py"])
        with self.assertRaisesRegex(ValueError, "之外"):
            policy.resolve_edit_path("alias.py")

    def test_simulated_link_resolution_to_outside_is_rejected(self):
        """模拟解析结果；不代表本机成功创建了真实符号链接。"""
        policy = EditPolicy(self.workspace, ["alias.py"])
        outside = (self.root / "outside.py").resolve()
        with patch.object(Path, "resolve", return_value=outside):
            with self.assertRaisesRegex(ValueError, "之外"):
                policy.resolve_edit_path("alias.py")


if __name__ == "__main__":
    unittest.main()
