"""自动摘要配置从 Harness 进入实际循环，使用模拟模型和临时会话。"""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from mini_pi.auto_compaction import AutoCompactionSettings
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context_size import estimate_qwen_input
from mini_pi.harness import Harness
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message
from mini_pi.session_store import SessionStore


class HarnessAutoCompactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_resume_compacts_and_answers_with_original_history_preserved(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            old_store = SessionStore(path, "old")
            original = [Message("user", "排查登录"), Message("assistant", "测试失败"), Message("user", "继续")]
            for item in original:
                old_store.append_item(item)

            answer = MockProvider([Message("assistant", "继续检查", stop_reason="stop")])
            summary = MockProvider([Message("assistant", "登录测试失败，待检查", stop_reason="stop")])
            answer.max_completion_tokens = summary.max_completion_tokens = 100
            window = ContextWindowBudget(10000, 100)
            tools = SimpleNamespace(executor=SimpleNamespace(execute=AsyncMock()), definitions=[], read_only_tools=set())
            harness = Harness(
                answer, tools, input_estimator=estimate_qwen_input, window_budget=window,
                auto_compaction=AutoCompactionSettings(1, 1), summary_provider=summary,
                summary_window=window, summary_estimator=estimate_qwen_input, item_estimator=lambda item: 1,
            )

            store = SessionStore(path, "resumed")
            outcome = await harness.resume("请继续排查", store)
            self.assertEqual(outcome.plan.state, "ready")
            self.assertEqual(outcome.run_result.status, "finished", outcome.run_result.error)
            self.assertEqual(len(summary.requests), 1)
            self.assertEqual(len(answer.requests), 1)
            texts = [item.content for item in answer.requests[0] if isinstance(item, Message)]
            self.assertTrue(any("登录测试失败，待检查" in text for text in texts))
            self.assertIn("请继续排查", texts)
            loaded = store.load()
            self.assertEqual(loaded.history, original + [Message("user", "请继续排查"), Message("assistant", "继续检查", stop_reason="stop")])
            self.assertEqual(sum(row["type"] == "compaction" for row in loaded.records), 1)
