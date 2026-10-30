"""D17 continuation acceptance: mock models and temporary sessions only."""

import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock

from mini_pi.auto_compaction import AutoCompactionSettings
from mini_pi.context import ContextProvider, FullHistoryContext
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context_size import estimate_qwen_input
from mini_pi.loop import run_loop
from mini_pi.message_queue import PendingMessageQueue
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message
from mini_pi.session_store import SessionStore


class ContinuationTests(unittest.IsolatedAsyncioTestCase):
    async def test_task_state_survives_compaction_with_scripted_summary(self):
        history = [
            Message("user", "目标：修复登录；约束：不要修改验收测试。"),
            Message("assistant", "已修改 auth.py；test_login 失败；待办：检查数据库。"),
            Message("user", "继续"),
        ]
        scripted_summary = "目标：修复登录；约束：不要修改验收测试；已修改 auth.py；test_login 失败；待办：检查数据库。"
        summary = MockProvider([Message("assistant", scripted_summary, stop_reason="stop")])
        answer = MockProvider([Message("assistant", "继续检查数据库", stop_reason="stop")])
        summary.max_completion_tokens = answer.max_completion_tokens = 1000
        window = ContextWindowBudget(10000, 1000)
        provider = ContextProvider(answer, FullHistoryContext(), input_estimator=estimate_qwen_input, window_budget=window)

        with TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "session.jsonl", "run")
            result = await run_loop(
                provider, SimpleNamespace(execute=AsyncMock()), history, [], session_store=store,
                auto_compaction=AutoCompactionSettings(1, 1), summary_provider=summary,
                summary_window=window, summary_estimator=estimate_qwen_input, item_estimator=lambda item: 1,
            )
            self.assertEqual(result.status, "finished", result.error)
            summary_prompt = "\n".join(item.content for item in summary.requests[0] if isinstance(item, Message))
            answer_prompt = "\n".join(item.content for item in answer.requests[0] if isinstance(item, Message))
            for fact in ("修复登录", "不要修改验收测试", "auth.py", "test_login", "检查数据库"):
                self.assertIn(fact, summary_prompt)
                self.assertIn(fact, answer_prompt)
            loaded = store.load()
            self.assertEqual(loaded.history[:len(history)], history)
            self.assertEqual(loaded.history[-1].content, "继续检查数据库")
            self.assertEqual([record["data"]["summary"] for record in loaded.records if record["type"] == "compaction"],
                             [scripted_summary])

    async def run_scenario(self, *, steering_during_summary=False, initial_steering=False, followup=False):
        steering = PendingMessageQueue()
        followups = PendingMessageQueue()
        if initial_steering:
            steering.enqueue("原先的额外要求")

        def summarize(_history, _tools):
            if steering_during_summary:
                steering.enqueue("重点检查数据库")
            if followup:
                followups.enqueue("再写一份说明")
            return Message("assistant", "登录排查摘要", stop_reason="stop")

        summary = MockProvider([summarize])
        summary.max_completion_tokens = 1000
        answer = MockProvider([Message("assistant", "本次回答"), Message("assistant", "后续回答")])
        answer.max_completion_tokens = 1000
        window = ContextWindowBudget(10000, 1000)
        provider = ContextProvider(answer, FullHistoryContext(), input_estimator=estimate_qwen_input, window_budget=window)
        history = [Message("user", "排查登录" + "历史" * 2000), Message("assistant", "已经检查"), Message("user", "继续")]
        references_calls = []

        async def prepare_references(items):
            references_calls.append(deepcopy(items))
            has_new = any(isinstance(item, Message) and item.content == "重点检查数据库" for item in items)
            return [Message("user", "资料：数据库" if has_new else "资料：登录")]

        with TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "session.jsonl", "run")
            result = await run_loop(
                provider, SimpleNamespace(execute=AsyncMock()), history, [], session_store=store,
                auto_compaction=AutoCompactionSettings(300, 1), summary_provider=summary,
                summary_window=window, summary_estimator=estimate_qwen_input, item_estimator=lambda item: 1,
                prepare_references=prepare_references, max_context_chars=50000,
                get_steering_messages=steering.drain_one, get_follow_up_messages=followups.drain_one,
            )
            return result, history, store.load(), summary, answer, references_calls, steering.drain_one()

    async def test_steering_during_summary_refreshes_reference_and_reaches_answer(self):
        result, history, loaded, summary, answer, refs, remaining = await self.run_scenario(steering_during_summary=True)
        self.assertEqual(result.status, "finished", result.error)
        self.assertEqual(len(refs), 2)
        self.assertNotIn("重点检查数据库", [item.content for item in refs[0] if isinstance(item, Message)])
        self.assertIn("重点检查数据库", [item.content for item in refs[1] if isinstance(item, Message)])
        self.assertEqual(len(summary.requests), 1)
        self.assertEqual(len(answer.requests), 1)
        content = [item.content for item in answer.requests[0] if isinstance(item, Message)]
        self.assertIn("资料：数据库", content)
        self.assertNotIn("资料：登录", content)
        self.assertTrue(any("登录排查摘要" in item for item in content))
        self.assertIn("重点检查数据库", content)
        self.assertEqual(loaded.history[:len(history)], history)
        self.assertEqual(loaded.history[len(history)], Message("user", "重点检查数据库"))
        self.assertFalse(any(item.content.startswith("资料：") for item in loaded.history if isinstance(item, Message)))
        self.assertEqual(remaining, [])

    async def test_without_new_steering_reference_is_not_prepared_twice(self):
        result, history, loaded, summary, answer, refs, remaining = await self.run_scenario()
        self.assertEqual(result.status, "finished", result.error)
        self.assertEqual(len(refs), 1)
        self.assertEqual(len(summary.requests), 1)
        self.assertEqual(len(answer.requests), 1)
        self.assertTrue(any("登录排查摘要" in item.content for item in answer.requests[0] if isinstance(item, Message)))
        self.assertEqual(loaded.history[:len(history)], history)
        self.assertEqual(remaining, [])

    async def test_already_delivered_steering_leaves_new_steering_queued_for_later(self):
        result, history, loaded, summary, answer, refs, remaining = await self.run_scenario(
            steering_during_summary=True, initial_steering=True
        )
        self.assertEqual(result.status, "finished", result.error)
        self.assertEqual(len(summary.requests), 1)
        self.assertGreaterEqual(len(answer.requests), 1)
        first = [item.content for item in answer.requests[0] if isinstance(item, Message)]
        self.assertIn("原先的额外要求", first)
        self.assertNotIn("重点检查数据库", first)
        self.assertIn("重点检查数据库", [item.content for item in loaded.history if isinstance(item, Message)])

    async def test_followup_during_summary_waits_for_first_answer(self):
        result, history, loaded, summary, answer, refs, remaining = await self.run_scenario(followup=True)
        self.assertEqual(result.status, "finished", result.error)
        self.assertEqual(len(summary.requests), 1)
        self.assertEqual(len(answer.requests), 2)
        first = [item.content for item in answer.requests[0] if isinstance(item, Message)]
        second = [item.content for item in answer.requests[1] if isinstance(item, Message)]
        self.assertNotIn("再写一份说明", first)
        self.assertIn("再写一份说明", second)
        self.assertLess(loaded.history.index(Message("assistant", "本次回答")),
                        loaded.history.index(Message("user", "再写一份说明")))
        self.assertEqual(remaining, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
