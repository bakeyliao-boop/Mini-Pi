"""自动压缩配置检查，不启动模型或访问会话。"""

import unittest

from mini_pi.auto_compaction import AutoCompactionSettings, check_auto_compaction_settings
from mini_pi.context_budget import ContextWindowBudget


class AutoCompactionSettingsTests(unittest.TestCase):
    def test_valid_configuration_passes(self):
        self.assertIsNone(check_auto_compaction_settings(AutoCompactionSettings(7000, 2000),
                                                        ContextWindowBudget(10000, 2000, 500)))

    def test_invalid_trigger_and_recent_target_are_rejected(self):
        budget = ContextWindowBudget(10000, 2000, 500)
        for settings in (None, AutoCompactionSettings(7500, 2000), AutoCompactionSettings(0, 2000),
                         AutoCompactionSettings(7000, 0), AutoCompactionSettings(7000, True)):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                check_auto_compaction_settings(settings, budget)
        with self.assertRaises(ValueError):
            check_auto_compaction_settings(AutoCompactionSettings(7000, 2000), None)


if __name__ == "__main__":
    unittest.main()
