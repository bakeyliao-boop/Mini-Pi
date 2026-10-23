"""D13-A 单条调用结构反例；不执行工具，保留严格与截断两种解析模式。"""

from copy import deepcopy
import unittest

from mini_pi.qwen_provider import ModelResponseError, parse_tool_call


class ResponseCallStructureTests(unittest.TestCase):
    def valid_call(self):
        return {"id": "edit_001", "type": "function", "function": {
            "name": "edit_file", "arguments": '{"path":"sample.py"}',
        }}

    def assert_rejected(self, raw):
        for preserve in (False, True):
            with self.subTest(raw=raw, preserve=preserve):
                with self.assertRaises(ModelResponseError):
                    parse_tool_call(raw, preserve_unparsed=preserve)

    def test_call_must_be_object(self):
        for raw in (None, 123, [], "call"):
            self.assert_rejected(raw)

    def test_id_must_be_nonempty_text(self):
        for value in (None, "", "  ", 123):
            raw = self.valid_call()
            raw["id"] = value
            self.assert_rejected(raw)
        raw = self.valid_call()
        del raw["id"]
        self.assert_rejected(raw)

    def test_only_function_type_is_supported(self):
        for value in (None, "", "custom", 123):
            raw = self.valid_call()
            raw["type"] = value
            self.assert_rejected(raw)
        raw = self.valid_call()
        del raw["type"]
        self.assert_rejected(raw)

    def test_function_must_be_object(self):
        for value in (None, [], "function", 123):
            raw = self.valid_call()
            raw["function"] = value
            self.assert_rejected(raw)
        raw = self.valid_call()
        del raw["function"]
        self.assert_rejected(raw)

    def test_name_must_be_nonempty_text(self):
        for value in (None, "", "  ", 123):
            raw = self.valid_call()
            raw["function"]["name"] = value
            self.assert_rejected(raw)
        raw = self.valid_call()
        del raw["function"]["name"]
        self.assert_rejected(raw)

    def test_arguments_must_be_text_even_in_preserve_mode(self):
        for value in (None, {}, [], 123):
            raw = self.valid_call()
            raw["function"]["arguments"] = value
            self.assert_rejected(raw)
        raw = self.valid_call()
        del raw["function"]["arguments"]
        self.assert_rejected(raw)

    def test_valid_structure_preserves_identity_and_input(self):
        raw = self.valid_call()
        before = deepcopy(raw)
        call = parse_tool_call(raw)
        self.assertEqual((call.id, call.name), ("edit_001", "edit_file"))
        self.assertEqual(call.arguments, {"path": "sample.py"})
        self.assertEqual(raw, before)


if __name__ == "__main__":
    unittest.main()
