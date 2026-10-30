"""检查压缩触发前的实际请求组装，不发送模型请求。"""

from copy import deepcopy
import asyncio
from types import SimpleNamespace
import unittest

from mini_pi.context import ContextParts, ContextProvider, FullHistoryContext, ReadOutputContext
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context_size import InputSizeEstimate, estimate_qwen_input
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolDefinition, ToolResult
from mini_pi.run_deadline import RunDeadlineExceeded


class CompactionProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_references_and_estimator_cannot_modify_candidate(self):
        history = [Message("user", "任务")]
        tools = [ToolDefinition("read", "说明", {"type": "object"})]
        provider = MockProvider([])
        def mutating_estimator(messages, definitions):
            messages[0].content = "被修改"
            definitions[0].description = "被修改"
            return InputSizeEstimate(4, 1, "test")
        wrapped = ContextProvider(provider, FullHistoryContext(), input_estimator=mutating_estimator,
                                  window_budget=ContextWindowBudget(100, 10))
        messages, measured_tools, _ = await wrapped.prepare_for_compaction(ContextParts(history, []), tools)
        self.assertEqual(messages, history)
        self.assertEqual(measured_tools, tools)
        self.assertEqual(provider.requests, [])

    async def test_snapshots_are_fixed_before_waiting_for_builder(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def build(history):
            started.set()
            await release.wait()
            return history
        history = [Message("user", "原任务")]
        references = [Message("user", "原资料")]
        tools = [ToolDefinition("read", "原工具", {"type": "object"})]
        provider = MockProvider([])
        wrapped = ContextProvider(provider, SimpleNamespace(build=build), input_estimator=estimate_qwen_input,
                                  window_budget=ContextWindowBudget(10000, 100))
        task = asyncio.create_task(wrapped.prepare_for_compaction(ContextParts(history, references), tools))
        try:
            await asyncio.wait_for(started.wait(), 1)
            history[0].content = "更改任务"
            references[0].content = "更改资料"
            tools[0].description = "更改工具"
            release.set()
            messages, measured_tools, _ = await asyncio.wait_for(task, 1)
            self.assertEqual([m.content for m in messages], ["原资料", "原任务"])
            self.assertEqual(measured_tools[0].description, "原工具")
            self.assertEqual(provider.requests, [])
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_expired_deadline_does_not_start_builder(self):
        calls = []
        async def build(history):
            calls.append(True)
            return history
        wrapped = ContextProvider(MockProvider([]), SimpleNamespace(build=build), input_estimator=estimate_qwen_input,
                                  window_budget=ContextWindowBudget(1000, 100))
        with self.assertRaises(RunDeadlineExceeded):
            await wrapped.prepare_for_compaction(ContextParts([Message("user", "任务")], []), [],
                                                 deadline=asyncio.get_running_loop().time() - 1)
        self.assertEqual(calls, [])

    async def test_probe_uses_shortened_read_and_includes_reference_and_tools_without_sending(self):
        history = [Message("user", "读取文件"),
                   Message("assistant", "读取", [ToolCall("read", "read_file", {"path": "a.txt"})]),
                   ToolResult("read", "read_file", "文件内容" * 1000)]
        references = [Message("user", "本轮参考资料")]
        tools = [ToolDefinition("read_file", "说明" * 1000, {"type": "object"})]
        before = deepcopy((history, references, tools))
        provider = MockProvider([])
        wrapped = ContextProvider(provider, ReadOutputContext(120), input_estimator=estimate_qwen_input,
                                  window_budget=ContextWindowBudget(100, 10))
        messages, measured_tools, estimate = await wrapped.prepare_for_compaction(ContextParts(history, references), tools)
        self.assertIn("本轮参考资料", [item.content for item in messages if isinstance(item, Message)])
        self.assertEqual(len(next(item for item in messages if isinstance(item, ToolResult)).output), 120)
        self.assertEqual(measured_tools, tools)
        self.assertEqual(estimate, estimate_qwen_input(messages, measured_tools))
        self.assertGreater(estimate.estimated_input_tokens + 10, 100)
        self.assertEqual(provider.requests, [])
        self.assertEqual((history, references, tools), before)


if __name__ == "__main__":
    unittest.main()
