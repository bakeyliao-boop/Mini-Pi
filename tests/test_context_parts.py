"""D17：检查历史与临时资料在构建阶段保持分离。"""

from copy import deepcopy
import unittest

from mini_pi.context import ContextParts, build_separate_context, check_request_chars
from mini_pi.memory.context_helpers import messages_char_count
from mini_pi.memory.errors import MemoryContextError
from mini_pi.models import Message


class ContextPartsTests(unittest.IsolatedAsyncioTestCase):
    def test_character_limit_applies_to_complete_combined_request(self):
        messages = [Message("user", "历史"), Message("user", "参考资料")]
        size = messages_char_count(messages)
        check_request_chars(messages, size)
        with self.assertRaises(MemoryContextError):
            check_request_chars(messages, size - 1)
        for limit in (0, -1, True):
            with self.subTest(limit=limit), self.assertRaises(MemoryContextError):
                check_request_chars(messages, limit)

    async def test_builder_receives_only_history_and_cannot_mutate_inputs(self):
        parts = ContextParts(
            history=[Message("system", "规则"), Message("user", "同一段文字")],
            references=[Message("user", "同一段文字")],
        )
        original = deepcopy(parts)

        class RecordingBuilder:
            async def build(self, history):
                self.seen = deepcopy(history)
                history[1].content = "整理后的历史"
                return history

        builder = RecordingBuilder()
        messages = await build_separate_context(builder, parts)
        self.assertEqual(builder.seen, original.history)
        self.assertEqual(parts, original)
        self.assertEqual([m.content for m in messages], ["规则", "同一段文字", "整理后的历史"])


if __name__ == "__main__":
    unittest.main()
