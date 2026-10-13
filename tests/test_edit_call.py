"""D08：模型调用参数校验；核心方法由学习者完成后运行。"""

from pathlib import Path
import unittest

from mini_pi.models import ToolCall
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy


class EditCallTests(unittest.TestCase):
    def setUp(self):
        # 只校验调用数据，不读取或写入此目录中的文件。
        policy = EditPolicy(Path(__file__).resolve().parent, ["discount.py"])
        self.executor = EditFileExecutor(policy)
        self.arguments = {"path": "discount.py", "old_text": "old", "new_text": "new"}

    def test_valid_call_preserves_parameter_values(self):
        call = ToolCall("call_001", "edit_file", self.arguments)
        self.assertEqual(self.executor.validate_edit_call(call), self.arguments)
        self.assertEqual(call.id, "call_001")

    def test_empty_new_text_is_valid_for_deletion(self):
        arguments = dict(self.arguments, new_text="")
        call = ToolCall("call_002", "edit_file", arguments)
        self.assertEqual(self.executor.validate_edit_call(call)["new_text"], "")

    def test_wrong_tool_name_is_rejected(self):
        call = ToolCall("call_003", "read_file", self.arguments)
        with self.assertRaisesRegex(ValueError, "不支持"):
            self.executor.validate_edit_call(call)

    def test_invalid_argument_container_or_fields_are_rejected(self):
        cases = (
            None,
            [],
            {"path": "discount.py", "old_text": "old"},
            dict(self.arguments, extra="unexpected"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                call = ToolCall("call_bad", "edit_file", arguments)
                with self.assertRaises(ValueError):
                    self.executor.validate_edit_call(call)

    def test_non_string_and_invalid_empty_values_are_rejected(self):
        cases = (
            dict(self.arguments, path=123),
            dict(self.arguments, path="   "),
            dict(self.arguments, old_text=None),
            dict(self.arguments, old_text=""),
            dict(self.arguments, new_text=False),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                call = ToolCall("call_bad", "edit_file", arguments)
                with self.assertRaises(ValueError):
                    self.executor.validate_edit_call(call)


if __name__ == "__main__":
    unittest.main()
