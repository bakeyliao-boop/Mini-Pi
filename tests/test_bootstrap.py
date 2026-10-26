"""D13-D 组装反例：能力定义与执行一致，既有范围和固定命令不被绕过。"""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from mini_pi.bootstrap import build_tools
from mini_pi.models import ToolCall


class BootstrapToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_bootstrap_", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "value.py").write_bytes(b"value = 1\n")
        (self.root / "forbidden.py").write_bytes(b"unchanged\n")
        self.evidence = self.root / "evidence"
        self.command = (sys.executable, "-c",
                        "from pathlib import Path; Path('fixed-command-ran').write_text('ok')")

    def build(self):
        return build_tools(self.root, ["value.py"], self.command, self.evidence)

    async def test_bundle_exposes_same_four_tools_without_starting_work(self):
        bundle = self.build()
        expected = ["list_files", "read_file", "edit_file", "run_tests"]
        self.assertEqual([tool.name for tool in bundle.definitions], expected)
        self.assertEqual(set(bundle.executor.executors), set(expected))
        self.assertEqual(bundle.read_only_tools, frozenset({"list_files", "read_file"}))
        self.assertEqual((self.root / "value.py").read_bytes(), b"value = 1\n")
        self.assertFalse((self.root / "fixed-command-ran").exists())
        self.assertFalse(self.evidence.exists())

    async def test_routed_read_and_allowed_edit_use_real_files(self):
        bundle = self.build()
        read = await bundle.executor.execute(ToolCall("read_001", "read_file", {"path": "value.py"}))
        self.assertIsNone(read.error)
        self.assertEqual(read.output, "value = 1\n")
        edit = await bundle.executor.execute(ToolCall("edit_001", "edit_file", {
            "path": "value.py", "old_text": "value = 1", "new_text": "value = 2"}))
        self.assertIsNone(edit.error)
        self.assertEqual((self.root / "value.py").read_bytes(), b"value = 2\n")
        rejected = await bundle.executor.execute(ToolCall("edit_002", "edit_file", {
            "path": "forbidden.py", "old_text": "unchanged", "new_text": "changed"}))
        self.assertTrue(rejected.error)
        self.assertEqual((self.root / "forbidden.py").read_bytes(), b"unchanged\n")

    async def test_model_cannot_replace_fixed_test_command(self):
        bundle = self.build()
        rejected = await bundle.executor.execute(ToolCall("tests_001", "run_tests", {
            "command": "must not be executed"}))
        self.assertTrue(rejected.error)
        self.assertFalse((self.root / "fixed-command-ran").exists())
        result = await bundle.executor.execute(ToolCall("tests_002", "run_tests", {}))
        self.assertIsNone(result.error)
        self.assertEqual(json.loads(result.output)["outcome"], "tests_passed")
        self.assertEqual((self.root / "fixed-command-ran").read_text(), "ok")

    async def test_invalid_edit_scope_is_rejected_without_work(self):
        for allowed in (["../outside.py"], "value.py"):
            with self.subTest(allowed=allowed):
                with self.assertRaises(ValueError):
                    build_tools(self.root, allowed, self.command, self.evidence)
        self.assertFalse((self.root / "fixed-command-ran").exists())
        self.assertFalse(self.evidence.exists())


if __name__ == "__main__":
    unittest.main()
