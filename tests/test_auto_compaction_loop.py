"""自动压缩接线：触发、保存摘要并继续回答。"""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from mini_pi.auto_compaction import AutoCompactionSettings
from mini_pi.context import ContextProvider, FullHistoryContext, ReadOutputContext
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context_size import estimate_qwen_input
from mini_pi.harness import Harness
from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore


class AutoCompactionLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_and_below_threshold_paths(self):
        with TemporaryDirectory() as directory:
            model = MockProvider([Message("assistant", "自动判断完成"), Message("assistant", "原流程完成")])
            model.max_completion_tokens = 1000
            executor = SimpleNamespace(execute=AsyncMock())
            store = SessionStore(Path(directory) / "blocked.jsonl", "blocked")
            provider = ContextProvider(model, FullHistoryContext(), input_estimator=estimate_qwen_input,
                                       window_budget=ContextWindowBudget(10000, 1000))
            summary = MockProvider([])
            summary.max_completion_tokens = 1000
            result = await run_loop(provider, executor, [Message("user", "任务")], [], session_store=store,
                                    auto_compaction=AutoCompactionSettings(7000, 2000), summary_provider=summary,
                                    summary_window=ContextWindowBudget(10000, 1000), summary_estimator=estimate_qwen_input,
                                    item_estimator=lambda item: 1)
            self.assertEqual(result.status, "finished")
            self.assertEqual(model.requests, [[Message("user", "任务")]])
            self.assertEqual(summary.requests, [])
            executor.execute.assert_not_awaited()

            result = await run_loop(model, executor, [Message("user", "任务")], [])
            self.assertEqual(result.status, "finished")
            self.assertEqual(len(model.requests), 2)

    async def test_trigger_without_safe_cut_stops_without_calling_models(self):
        with TemporaryDirectory() as directory:
            model, summary = MockProvider([]), MockProvider([])
            model.max_completion_tokens = 1000
            summary.max_completion_tokens = 1000
            provider = ContextProvider(model, FullHistoryContext(), input_estimator=estimate_qwen_input,
                                       window_budget=ContextWindowBudget(10000, 1000))
            store = SessionStore(Path(directory) / "session.jsonl", "run")
            result = await run_loop(provider, SimpleNamespace(execute=AsyncMock()), [Message("user", "任务")], [],
                                    session_store=store, auto_compaction=AutoCompactionSettings(1, 1),
                                    summary_provider=summary, summary_window=ContextWindowBudget(10000, 1000),
                                    summary_estimator=estimate_qwen_input, item_estimator=lambda item: 1)
            self.assertEqual(result.status, "budget_exhausted")
            self.assertIn("找不到可用的摘要切点", result.error)
            self.assertEqual(model.requests, [])
            self.assertEqual(summary.requests, [])
            self.assertEqual(store.load().history, [Message("user", "任务")])
            self.assertEqual(store.load().records[-1]["data"]["status"], "budget_exhausted")

    async def test_trigger_saves_summary_and_continues_answering(self):
        with TemporaryDirectory() as directory:
            model = MockProvider([Message("assistant", "继续排查")])
            model.max_completion_tokens = 1000
            summary = MockProvider([Message("assistant", "测试失败，待排查", stop_reason="stop")])
            summary.max_completion_tokens = 1000
            provider = ContextProvider(model, FullHistoryContext(), input_estimator=estimate_qwen_input,
                                       window_budget=ContextWindowBudget(10000, 1000))
            history = [Message("user", "修复登录"), Message("assistant", "测试失败"), Message("user", "继续")]
            store = SessionStore(Path(directory) / "session.jsonl", "run")
            result = await run_loop(provider, SimpleNamespace(execute=AsyncMock()), history, [],
                                    session_store=store, auto_compaction=AutoCompactionSettings(1, 1),
                                    summary_provider=summary, summary_window=ContextWindowBudget(10000, 1000),
                                    summary_estimator=estimate_qwen_input, item_estimator=lambda item: 1)
            self.assertEqual(result.status, "finished")
            self.assertEqual(len(summary.requests), 1)
            self.assertEqual(len(model.requests), 1)
            self.assertTrue(any("测试失败，待排查" in item.content for item in model.requests[0] if isinstance(item, Message)))
            self.assertEqual(store.load().history, history + [Message("assistant", "继续排查")])
            self.assertIsNotNone(store.load().session_id)
            saved = [row for row in store.load().records if row["type"] == "compaction"]
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["data"]["summary"], "测试失败，待排查")
            resumed_model = MockProvider([Message("assistant", "继续排查")])
            tools = SimpleNamespace(executor=SimpleNamespace(execute=AsyncMock()), definitions=[], read_only_tools=set())
            harness = Harness(resumed_model, tools, input_estimator=estimate_qwen_input,
                              window_budget=ContextWindowBudget(10000, 1000))
            outcome = await harness.resume("新问题", SessionStore(store.path, "resume"))
            self.assertEqual(outcome.run_result.status, "finished")
            texts = [item.content for item in resumed_model.requests[0] if isinstance(item, Message)]
            self.assertTrue(any("测试失败，待排查" in text for text in texts))
            self.assertIn("新问题", texts)

    async def test_answer_output_limit_is_checked_before_summary_call(self):
        with TemporaryDirectory() as directory:
            answer, summary = MockProvider([]), MockProvider([])
            summary.max_completion_tokens = 1000
            provider = ContextProvider(answer, FullHistoryContext(), input_estimator=estimate_qwen_input,
                                       window_budget=ContextWindowBudget(10000, 1000))
            store = SessionStore(Path(directory) / "blocked.jsonl", "run")
            with self.assertRaisesRegex(ValueError, "回答模型必须提供"):
                await run_loop(provider, SimpleNamespace(execute=AsyncMock()), [Message("user", "任务")], [],
                               session_store=store, auto_compaction=AutoCompactionSettings(1, 1),
                               summary_provider=summary, summary_window=ContextWindowBudget(10000, 1000),
                               summary_estimator=estimate_qwen_input, item_estimator=lambda item: 1)
            self.assertFalse(store.path.exists())
            self.assertEqual(answer.requests, [])
            self.assertEqual(summary.requests, [])

    async def test_summary_errors_and_aborted_map_to_correct_run_status(self):
        with TemporaryDirectory() as directory:
            history = [Message("user", "修复"), Message("assistant", "测试失败"), Message("user", "继续")]
            for reason, status in (("length", "error"), ("error", "error"), ("aborted", "cancelled")):
                with self.subTest(reason=reason):
                    model = MockProvider([])
                    model.max_completion_tokens = 1000
                    summary = MockProvider([Message("assistant", "部分摘要", stop_reason=reason)])
                    summary.max_completion_tokens = 1000
                    provider = ContextProvider(model, FullHistoryContext(), input_estimator=estimate_qwen_input,
                                               window_budget=ContextWindowBudget(10000, 1000))
                    store = SessionStore(Path(directory) / f"{reason}.jsonl", "run")
                    result = await run_loop(provider, SimpleNamespace(execute=AsyncMock()), history, [],
                                            session_store=store, auto_compaction=AutoCompactionSettings(1, 1),
                                            summary_provider=summary, summary_window=ContextWindowBudget(10000, 1000),
                                            summary_estimator=estimate_qwen_input, item_estimator=lambda item: 1)
                    self.assertEqual(result.status, status)
                    self.assertEqual(store.load().records[-1]["data"]["status"], status)
                    self.assertEqual(store.load().history, history)
                    self.assertEqual(model.requests, [])
                    self.assertEqual(len(summary.requests), 1)
                    self.assertFalse(any(row["type"] == "compaction" for row in store.load().records))

    async def test_trigger_uses_shortened_read_not_full_original(self):
        with TemporaryDirectory() as directory:
            model, summary = MockProvider([Message("assistant", "完成")]), MockProvider([])
            model.max_completion_tokens = 100
            summary.max_completion_tokens = 100
            provider = ContextProvider(model, ReadOutputContext(120), input_estimator=estimate_qwen_input,
                                       window_budget=ContextWindowBudget(1000, 100))
            full_output = "文件正文" * 2000
            history = [Message("user", "读取"),
                       Message("assistant", "读取", [ToolCall("r", "read_file", {"path": "a"})]),
                       ToolResult("r", "read_file", full_output), Message("user", "继续")]
            store = SessionStore(Path(directory) / "session.jsonl", "run")
            result = await run_loop(provider, SimpleNamespace(execute=AsyncMock()), history, [], session_store=store,
                                    auto_compaction=AutoCompactionSettings(500, 1), summary_provider=summary,
                                    summary_window=ContextWindowBudget(1000, 100), summary_estimator=estimate_qwen_input,
                                    item_estimator=lambda item: 1)
            self.assertEqual(result.status, "finished")
            self.assertEqual(summary.requests, [])
            self.assertEqual(len(next(item for item in model.requests[0] if isinstance(item, ToolResult)).output), 120)
            self.assertEqual(next(item for item in store.load().history if isinstance(item, ToolResult)).output, full_output)

    async def test_summary_configuration_errors_stop_before_any_request(self):
        with TemporaryDirectory() as directory:
            model, summary = MockProvider([]), MockProvider([])
            model.max_completion_tokens = 1000
            summary.max_completion_tokens = 1000
            provider = ContextProvider(model, FullHistoryContext(), input_estimator=estimate_qwen_input,
                                       window_budget=ContextWindowBudget(10000, 1000))
            executor = SimpleNamespace(execute=AsyncMock())
            store = SessionStore(Path(directory) / "blocked.jsonl", "blocked")
            options = dict(provider=provider, session_store=store, auto_compaction=AutoCompactionSettings(7000, 2000),
                           summary_provider=summary, summary_window=ContextWindowBudget(10000, 1000),
                           summary_estimator=estimate_qwen_input, item_estimator=lambda item: 1)
            for field, value in (("summary_provider", None), ("summary_window", None),
                                 ("summary_estimator", None), ("item_estimator", None),
                                 ("summary_window", ContextWindowBudget(10000, 999))):
                changed = dict(options, **{field: value})
                with self.subTest(field=field), self.assertRaises(ValueError):
                    await run_loop(executor=executor, initial_messages=[Message("user", "任务")], tools=[], **changed)
                self.assertFalse(store.path.exists())
                self.assertEqual(model.requests, [])
                self.assertEqual(summary.requests, [])

    async def test_configuration_errors_stop_before_session_or_model(self):
        with TemporaryDirectory() as directory:
            model = MockProvider([])
            model.max_completion_tokens = 1000
            provider = ContextProvider(model, FullHistoryContext(), input_estimator=estimate_qwen_input,
                                       window_budget=ContextWindowBudget(10000, 1000))
            executor = SimpleNamespace(execute=AsyncMock())
            store = SessionStore(Path(directory) / "blocked.jsonl", "blocked")
            for options in (
                {"provider": provider, "session_store": None, "auto_compaction": AutoCompactionSettings(7000, 2000)},
                {"provider": model, "session_store": store, "auto_compaction": AutoCompactionSettings(7000, 2000)},
                {"provider": provider, "session_store": store, "auto_compaction": AutoCompactionSettings(9000, 2000)},
                {"provider": provider, "session_store": store, "auto_compaction": AutoCompactionSettings(7000, 0)},
                {"provider": provider, "session_store": store, "auto_compaction": AutoCompactionSettings(7000, 2000),
                 "prepare_messages": AsyncMock()},
            ):
                with self.subTest(options=options), self.assertRaises(ValueError):
                    await run_loop(executor=executor, initial_messages=[Message("user", "任务")], tools=[], **options)
                self.assertFalse(store.path.exists())
                self.assertEqual(model.requests, [])


if __name__ == "__main__":
    unittest.main()
