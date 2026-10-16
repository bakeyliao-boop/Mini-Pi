"""D12：取消已请求、下一工具尚未启动时的门禁反例。

用模拟模型/探针工具精确安排 task.cancel 时点；探针入口实际写临时启动标记。
只测试当前 run_loop 与 await_before_deadline，不替换核心方法或执行真实模型。
"""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolDefinition, ToolResult
from mini_pi.session_store import SessionStore


class StartWitnessExecutor:
    """测试专用工具：入口落盘，独立于返回状态观察是否真的启动。"""

    def __init__(self, marker, *, cancel_after=None):
        self.marker = marker
        self.cancel_after = cancel_after
        self.calls = []

    async def execute(self, call):
        self.calls.append(call.id)
        self.marker.write_text(json.dumps(self.calls), encoding="utf-8")
        await asyncio.sleep(0)  # 已进入工具后的等待点，不能充当启动前门禁。
        if call.id == self.cancel_after:
            asyncio.current_task().cancel()
        return ToolResult(call.id, call.name, "探针完成")


class CancelStartGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_start_gate_", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.marker = self.root / "tool-started.json"
        self.store = SessionStore(self.root / "session.jsonl")
        self.initial = [Message("user", "工具开始前取消门禁测试。")]
        self.calls = [ToolCall("probe_001", "probe", {}), ToolCall("probe_002", "probe", {})]
        self.request = Message("assistant", "安排两个探针调用。", self.calls)
        self.tools = [ToolDefinition("probe", "仅测试工具启动", {"type": "object"})]
        self.observation = {}

    async def _settle(self, task):
        if not task.done():
            task.cancel()
        done, _ = await asyncio.wait({task}, timeout=2)
        self.assertIn(task, done)
        try:
            task.result()
        except (asyncio.CancelledError, Exception):
            pass

    async def _run(self, provider, executor, *, timeout):
        task = asyncio.create_task(run_loop(
            provider, executor, self.initial, self.tools, self.store,
            total_timeout_seconds=timeout,
        ))
        self.addAsyncCleanup(self._settle, task)
        done, _ = await asyncio.wait({task}, timeout=2)
        self.assertIn(task, done)
        return task.result()

    def _observe(self, result, provider, executor, expected_calls):
        loaded = self.store.load()
        self.observation = {
            "run_status": result.status,
            "expected_tool_starts": expected_calls,
            "actual_tool_starts": list(executor.calls),
            "marker_written": self.marker.exists(),
            "marker_contents": json.loads(self.marker.read_text(encoding="utf-8")) if self.marker.exists() else [],
            "model_requests": len(provider.requests),
            "returned_tool_results": [item.tool_call_id for item in result.messages if isinstance(item, ToolResult)],
            "run_end_statuses": [row["data"]["status"] for row in loaded.records if row["type"] == "run_end"],
        }
        self.assertEqual(loaded.history, result.messages)

    async def _cancel_after_model(self, *, timeout):
        def return_calls_and_request_cancel(history, tools):
            # 模拟主流程在刚获得模型消息时收到取消；此时下一工具还没进入。
            asyncio.current_task().cancel()
            return self.request

        provider = MockProvider([return_calls_and_request_cancel])
        executor = StartWitnessExecutor(self.marker)
        result = await self._run(provider, executor, timeout=timeout)
        self._observe(result, provider, executor, [])
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.messages, self.initial + [self.request])
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(self.observation["run_end_statuses"], ["cancelled"])
        self.assertEqual(executor.calls, [], "取消已请求，尚未开始的工具不应启动")
        self.assertFalse(self.marker.exists())

    async def test_cancel_before_first_tool_without_deadline_blocks_start(self):
        await self._cancel_after_model(timeout=None)

    async def test_cancel_before_first_tool_with_future_deadline_blocks_start(self):
        await self._cancel_after_model(timeout=10)

    async def test_cancel_after_completed_tool_blocks_next_tool(self):
        provider = MockProvider([self.request])
        executor = StartWitnessExecutor(self.marker, cancel_after="probe_001")
        result = await self._run(provider, executor, timeout=10)
        self._observe(result, provider, executor, ["probe_001"])
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(self.observation["returned_tool_results"], ["probe_001"])
        self.assertEqual(self.observation["run_end_statuses"], ["cancelled"])
        self.assertEqual(executor.calls, ["probe_001"], "第一项完成后已请求取消，第二项不应启动")

    async def test_no_cancel_allows_tools_and_feedback(self):
        provider = MockProvider([self.request, Message("assistant", "探针结束。")])
        executor = StartWitnessExecutor(self.marker)
        result = await self._run(provider, executor, timeout=10)
        self._observe(result, provider, executor, ["probe_001", "probe_002"])
        self.assertEqual(result.status, "finished")
        self.assertEqual(executor.calls, ["probe_001", "probe_002"])
        self.assertEqual(len(provider.requests), 2)
        feedback = [item for item in provider.requests[1] if isinstance(item, ToolResult)]
        self.assertEqual([item.tool_call_id for item in feedback], ["probe_001", "probe_002"])


if __name__ == "__main__":
    unittest.main()
