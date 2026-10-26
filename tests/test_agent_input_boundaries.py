"""D13-C：队列递送与预算、取消、超时、跨run及截断的组合边界。

超时插入点由受控门禁固定，不据此宣称新的硬实时保证；
模型请求快照与临时JSONL保留，实际时限/资源清理由原有测试另行覆盖。
"""

import asyncio
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mini_pi.agent import Agent
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.run_deadline import RunDeadlineExceeded, await_before_deadline
from mini_pi.session_store import SessionStore
from mini_pi.tools.tool_router import ToolRouter


class AgentInputBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="_input_boundaries_", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.observation = {}

    def store(self, name="A"):
        return SessionStore(self.root / (name + ".jsonl"))

    def assert_saved(self, result, store, status):
        self.assertEqual(result.status, status)
        loaded = store.load()
        self.assertEqual(loaded.history, result.messages)
        self.assertEqual([r["data"]["status"] for r in loaded.records
                          if r["type"] == "run_end"], [status])

    def text(self, history):
        return [m.content for m in history if isinstance(m, Message)]

    async def test_timeout_before_first_request_retains_steering_for_next_run(self):
        provider = MockProvider([Message("assistant", "完成", stop_reason="stop")])
        agent = Agent(provider, ToolRouter({}), [])
        agent.steer("保留方向")
        first_store = self.store()
        with patch("mini_pi.loop.await_before_deadline", side_effect=RunDeadlineExceeded("受控到期")):
            first = await agent.prompt([Message("user", "A")], session_store=first_store,
                                       total_timeout_seconds=60)
        self.assert_saved(first, first_store, "timeout")
        self.assertEqual(provider.requests, [])
        self.assertNotIn("保留方向", self.text(first.messages))
        second_store = self.store("B")
        second = await agent.prompt([Message("user", "B")], session_store=second_store)
        self.assert_saved(second, second_store, "finished")
        self.assertEqual(self.text(provider.requests[0]), ["B", "保留方向"])
        self.observation = {"case_kind": "timeout_before_dequeue", "first_status": "timeout",
                            "first_model_requests": 0, "pending_delivered_once_in_next_run": True}

    async def check_selected_follow_up_gate(self, cancel):
        provider = MockProvider([Message("assistant", "首轮完成", stop_reason="stop")])
        agent = Agent(provider, ToolRouter({}), [])
        agent.follow_up("已选后续")
        store = self.store()
        count = 0
        async def gate(operation, deadline):
            nonlocal count
            count += 1
            if count == 2:
                if cancel:
                    asyncio.current_task().cancel()
                else:
                    raise RunDeadlineExceeded("后续请求前受控到期")
            return await await_before_deadline(operation, deadline)
        with patch("mini_pi.loop.await_before_deadline", new=gate):
            result = await agent.prompt([Message("user", "A")], session_store=store,
                                        total_timeout_seconds=60)
        expected = "cancelled" if cancel else "timeout"
        self.assert_saved(result, store, expected)
        self.assertEqual(len(provider.requests), 1)
        self.assertNotIn("已选后续", self.text(provider.requests[0]))
        self.assertEqual(self.text(result.messages).count("已选后续"), 1)
        self.assertEqual(agent._follow_up_queue.drain_one(), [])
        self.assertFalse(agent.is_running)
        self.observation = {"case_kind": "selected_follow_up_" + expected,
                            "status": expected, "model_requests": 1,
                            "selected_message_saved_once": True, "model_did_not_read_selected_message": True}

    async def test_selected_follow_up_is_saved_when_next_request_times_out(self):
        await self.check_selected_follow_up_gate(False)

    async def test_selected_follow_up_is_saved_when_next_request_is_cancelled(self):
        await self.check_selected_follow_up_gate(True)

    async def test_cancel_during_model_keeps_unselected_inputs_for_next_run(self):
        entered, release = asyncio.Event(), asyncio.Event()
        requests = []
        async def generate(history, tools):
            requests.append(deepcopy(list(history)))
            if len(requests) == 1:
                entered.set()
                await release.wait()
            return Message("assistant", "完成", stop_reason="stop")
        provider = Mock()
        provider.generate = AsyncMock(side_effect=generate)
        agent = Agent(provider, ToolRouter({}), [])
        first_store = self.store()
        pending = agent.prompt([Message("user", "A")], session_store=first_store)
        try:
            async with asyncio.timeout(3):
                await entered.wait()
            agent.steer("保留方向")
            agent.follow_up("保留后续")
            agent.abort()
            async with asyncio.timeout(3):
                await agent.wait_for_idle()
                first = await pending
        finally:
            release.set()
            if not pending.done():
                agent.abort()
                await pending
        self.assert_saved(first, first_store, "cancelled")
        self.assertEqual(len(requests), 1)
        self.assertNotIn("保留方向", self.text(first.messages))
        self.assertNotIn("保留后续", self.text(first.messages))
        second_store = self.store("B")
        second = await agent.prompt([Message("user", "B")], session_store=second_store)
        self.assert_saved(second, second_store, "finished")
        self.assertEqual(len(requests), 3)
        self.assertEqual(self.text(requests[1]), ["B", "保留方向"])
        self.assertNotIn("保留后续", self.text(requests[1]))
        self.assertEqual(requests[2][-1], Message("user", "保留后续"))
        self.observation = {"case_kind": "unselected_inputs_after_cancel",
                            "first_status": "cancelled", "second_status": "finished",
                            "steering_and_follow_up_retained_in_order": True}

    async def test_multiple_follow_ups_are_fifo_one_per_request(self):
        provider = MockProvider([Message("assistant", str(i), stop_reason="stop") for i in range(3)])
        agent = Agent(provider, ToolRouter({}), [])
        agent.follow_up("后续A")
        agent.follow_up("后续B")
        store = self.store()
        result = await agent.prompt([Message("user", "初始")], session_store=store)
        self.assert_saved(result, store, "finished")
        self.assertEqual(len(provider.requests), 3)
        self.assertEqual(provider.requests[1][-1], Message("user", "后续A"))
        self.assertNotIn("后续B", self.text(provider.requests[1]))
        self.assertEqual(provider.requests[2][-1], Message("user", "后续B"))

    async def test_inputs_added_in_end_callback_are_kept_for_next_run(self):
        provider = MockProvider([Message("assistant", str(i), stop_reason="stop") for i in range(3)])
        hook_count = 0
        async def hook(result, error):
            nonlocal hook_count
            hook_count += 1
            if hook_count == 1:
                agent.steer("下次方向")
                agent.follow_up("下次后续")
        agent = Agent(provider, ToolRouter({}), [], on_run_end=hook)
        first_store = self.store()
        first = await agent.prompt([Message("user", "A")], session_store=first_store)
        self.assert_saved(first, first_store, "finished")
        self.assertEqual(len(provider.requests), 1)
        self.assertNotIn("下次方向", self.text(first.messages))
        second_store = self.store("B")
        second = await agent.prompt([Message("user", "B")], session_store=second_store)
        self.assert_saved(second, second_store, "finished")
        self.assertEqual(self.text(provider.requests[1]), ["B", "下次方向"])
        self.assertEqual(provider.requests[2][-1], Message("user", "下次后续"))

    async def test_length_feedback_is_paired_before_steering_and_follow_up(self):
        def truncated(history, tools):
            agent.steer("重新给完整参数")
            agent.follow_up("最后总结")
            return Message("assistant", "截断", [
                ToolCall("edit_001", "edit_file", {"path": "value.py"}, '{"path":"value.py"}'),
                ToolCall("edit_002", "edit_file", None, '{"path":'),
            ], stop_reason="length")
        provider = MockProvider([truncated,
            Message("assistant", "不再调用工具", stop_reason="stop"),
            Message("assistant", "总结", stop_reason="stop")])
        executor = Mock()
        executor.execute = AsyncMock()
        agent = Agent(provider, executor, [])
        store = self.store()
        result = await agent.prompt([Message("user", "A")], session_store=store)
        self.assert_saved(result, store, "finished")
        executor.execute.assert_not_called()
        self.assertEqual(len(provider.requests), 3)
        feedback = [m for m in provider.requests[1] if isinstance(m, ToolResult)]
        self.assertEqual([m.tool_call_id for m in feedback], ["edit_001", "edit_002"])
        self.assertTrue(all("未执行" in m.error for m in feedback))
        self.assertEqual(provider.requests[1][-1], Message("user", "重新给完整参数"))
        self.assertNotIn("最后总结", self.text(provider.requests[1]))
        self.assertEqual(provider.requests[2][-1], Message("user", "最后总结"))
        self.observation = {"case_kind": "length_with_queued_input", "tools_executed": 0,
                            "paired_error_ids": ["edit_001", "edit_002"],
                            "steering_after_feedback_follow_up_after_final": True}


if __name__ == "__main__":
    unittest.main()
