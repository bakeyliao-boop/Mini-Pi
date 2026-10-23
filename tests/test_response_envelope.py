"""D13-A 外壳校验：错误外部结构明确拒绝，合法数据保持原样。"""

from copy import deepcopy
import unittest

from mini_pi.qwen_provider import ModelResponseError, get_response_choice


class ResponseEnvelopeTests(unittest.TestCase):
    def test_rejects_non_object_response(self):
        for response in (None, [], "text", 0, False):
            with self.subTest(response=response):
                with self.assertRaises(ModelResponseError):
                    get_response_choice(response)

    def test_rejects_missing_empty_or_non_list_choices(self):
        for response in ({}, {"choices": None}, {"choices": []},
                         {"choices": {}}, {"choices": "text"}):
            with self.subTest(response=response):
                with self.assertRaises(ModelResponseError):
                    get_response_choice(response)

    def test_rejects_non_object_first_choice(self):
        for choice in (None, [], "text", 0, False):
            with self.subTest(choice=choice):
                with self.assertRaises(ModelResponseError):
                    get_response_choice({"choices": [choice]})

    def test_returns_first_choice_without_changing_input(self):
        response = {"choices": [
            {"finish_reason": "stop", "message": {"role": "assistant", "content": "回答"}},
            {"finish_reason": "length"},
        ]}
        before = deepcopy(response)
        self.assertIs(get_response_choice(response), response["choices"][0])
        self.assertEqual(response, before)

    def test_empty_choice_is_left_for_next_validation_stage(self):
        self.assertEqual(get_response_choice({"choices": [{}]}), {})


if __name__ == "__main__":
    unittest.main()
