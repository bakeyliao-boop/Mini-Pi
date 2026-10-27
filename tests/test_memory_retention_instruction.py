"""保留目标规则的离线分支契约；不证明提示语义或真实模型遵循效果。"""

import unittest
from unittest.mock import AsyncMock, patch

from mini_pi.memory import extraction_client
from mini_pi.memory.errors import MemoryPolicyError


class RetentionInstructionTests(unittest.TestCase):
    def setUp(self):
        self.database = self.enterContext(patch(
            "sqlite3.connect", side_effect=AssertionError("组装规则不得访问数据库"),
        ))
        self.network = self.enterContext(patch(
            "mini_pi.qwen_client.post_json_async", new_callable=AsyncMock,
            side_effect=AssertionError("组装规则不得发起模型请求"),
        ))

    def tearDown(self):
        self.database.assert_not_called()
        self.network.assert_not_called()

    def test_false_keeps_shared_user_target_and_selects_only_session_event_rule(self):
        instruction = extraction_client.build_retention_instruction(False)
        self.assertEqual(instruction, extraction_client.USER_RETENTION_RULE + extraction_client.SESSION_ONLY_RULE)
        self.assertNotIn(extraction_client.PROJECT_HISTORY_RULE, instruction)

    def test_true_keeps_shared_user_target_and_selects_only_project_history_rule(self):
        instruction = extraction_client.build_retention_instruction(True)
        self.assertEqual(instruction, extraction_client.USER_RETENTION_RULE + extraction_client.PROJECT_HISTORY_RULE)
        self.assertNotIn(extraction_client.SESSION_ONLY_RULE, instruction)

    def test_non_boolean_inputs_are_rejected_without_truthiness_conversion(self):
        for invalid in (None, 0, 1, "false", "", [], {}, (), set()):
            with self.subTest(value=repr(invalid)):
                with self.assertRaises(MemoryPolicyError):
                    extraction_client.build_retention_instruction(invalid)


if __name__ == "__main__":
    unittest.main()
