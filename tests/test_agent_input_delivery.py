"""D13-C 递送时序：事件屏障＋模型请求快照＋真实文件/JSONL。"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mini_pi.agent import Agent
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy
from mini_pi.tools.read_file import ReadFileExecutor
from mini_pi.tools.tool_router import ToolRouter


class AgentInputDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def execute_case(self, steering=(), follow_up=(), budget=5):
        temp = TemporaryDirectory(prefix="_input_delivery_", dir=Path(__file__).parent)
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        target = root / "value.py"
        target.write_bytes(b"value = 1\n")
        reader = ReadFileExecutor(root)
        editor = EditFileExecutor(EditPolicy(root, ["value.py"]))
        router = ToolRouter({"read_file": reader, "edit_file": editor})
        provider = MockProvider([
            Message("assistant", "读取并编辑", [
                ToolCall("read_001", "read_file", {"path": "value.py"}),
                ToolCall("edit_001", "edit_file", {
                    "path": "value.py", "old_text": "value = 1", "new_text": "value = 2"}),
            ]),
            *[Message("assistant", f"答复{index}", stop_reason="stop") for index in range(2, 7)],
        ])
        store = SessionStore(root / "session.jsonl")
        agent = Agent(provider, router, [reader.definition, editor.definition])
        read_done, release = asyncio.Event(), asyncio.Event()
        executed = []
        real_execute = router.execute
        async def execute(call):
            result = await real_execute(call)
            executed.append(call.id)
            if call.id == "read_001":
                read_done.set()
                await release.wait()
            return result
        async def cleanup():
            release.set()
            agent.abort()
            async with asyncio.timeout(5):
                await agent.wait_for_idle()
                await pending
        with patch.object(router, "execute", new=execute):
            pending = agent.prompt([Message("user", "受控递送测试")],
                                   session_store=store, max_model_turns=budget)
            self.addAsyncCleanup(cleanup)
            try:
                async with asyncio.timeout(3):
                    await read_done.wait()
                for text in steering:
                    agent.steer(text)
                for text in follow_up:
                    agent.follow_up(text)
                self.assertEqual(len(provider.requests), 1)
                self.assertEqual(target.read_bytes(), b"value = 1\n")
            finally:
                release.set()
            async with asyncio.timeout(5):
                result = await pending
        self.assertEqual(executed, ["read_001", "edit_001"])
        self.assertEqual(target.read_bytes(), b"value = 2\n")
        loaded = store.load()
        self.assertEqual(loaded.history, result.messages)
        self.assertEqual(sum(r["type"] == "run_start" for r in loaded.records), 1)
        self.assertEqual(sum(r["type"] == "run_end" for r in loaded.records), 1)
        self.assertEqual(loaded.records[-1]["data"]["status"], result.status)
        self.assertEqual([m.tool_call_id for m in result.messages if isinstance(m, ToolResult)],
                         ["read_001", "edit_001"])
        return agent, provider, result

    def text(self, history):
        return [item.content for item in history if isinstance(item, Message)]

    async def test_steer_arrives_after_whole_batch_before_second_request(self):
        agent, provider, result = await self.execute_case(steering=("先只解释",))
        self.assertEqual(len(provider.requests), 2)
        second = provider.requests[1]
        self.assertEqual([m.tool_call_id for m in second if isinstance(m, ToolResult)],
                         ["read_001", "edit_001"])
        self.assertEqual(second[-1], Message("user", "先只解释"))
        self.assertEqual(result.status, "finished")

    async def test_follow_up_waits_until_after_natural_final_answer(self):
        agent, provider, result = await self.execute_case(follow_up=("最后总结",))
        self.assertEqual(len(provider.requests), 3)
        self.assertNotIn("最后总结", self.text(provider.requests[1]))
        self.assertEqual(provider.requests[2][-2:], [
            Message("assistant", "答复2", stop_reason="stop"), Message("user", "最后总结"),
        ])

    async def test_steering_precedes_follow_up_at_different_boundaries(self):
        agent, provider, result = await self.execute_case(
            steering=("先只解释",), follow_up=("最后总结",))
        self.assertEqual(len(provider.requests), 3)
        self.assertIn("先只解释", self.text(provider.requests[1]))
        self.assertNotIn("最后总结", self.text(provider.requests[1]))
        self.assertEqual(provider.requests[2][-1], Message("user", "最后总结"))

    async def test_fifo_delivers_one_steering_message_per_request(self):
        agent, provider, result = await self.execute_case(
            steering=("方向A", "方向B", "方向C"), follow_up=("最后总结",))
        self.assertEqual(len(provider.requests), 5)
        self.assertEqual(provider.requests[1][-1], Message("user", "方向A"))
        self.assertNotIn("方向B", self.text(provider.requests[1]))
        self.assertEqual(provider.requests[2][-1], Message("user", "方向B"))
        self.assertNotIn("方向C", self.text(provider.requests[2]))
        self.assertEqual(provider.requests[3][-1], Message("user", "方向C"))
        self.assertEqual(provider.requests[4][-1], Message("user", "最后总结"))

    async def test_prequeued_steering_enters_first_request(self):
        provider = MockProvider([Message("assistant", "完成", stop_reason="stop")])
        agent = Agent(provider, ToolRouter({}), [])
        agent.steer("预排队输入")
        result = await agent.prompt([Message("user", "初始任务")])
        self.assertEqual(provider.requests[0], [
            Message("user", "初始任务"), Message("user", "预排队输入"),
        ])
        self.assertEqual(result.status, "finished")

    async def test_budget_stops_requests_without_silently_losing_input(self):
        agent, provider, result = await self.execute_case(steering=("待递送",), budget=1)
        self.assertEqual(result.status, "budget_exhausted")
        self.assertEqual(len(provider.requests), 1)
        queued = agent._steering_queue.drain_one()
        preserved = self.text(result.messages) + [item.content for item in queued]
        self.assertEqual(preserved.count("待递送"), 1)

    async def test_budget_after_final_answer_preserves_follow_up(self):
        provider = MockProvider([Message("assistant", "首轮完成", stop_reason="stop")])
        agent = Agent(provider, ToolRouter({}), [])
        agent.follow_up("后续要求")
        result = await agent.prompt([Message("user", "初始任务")], max_model_turns=1)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(result.status, "budget_exhausted")
        queued = agent._follow_up_queue.drain_one()
        preserved = self.text(result.messages) + [item.content for item in queued]
        self.assertEqual(preserved.count("后续要求"), 1)

    async def test_model_error_does_not_deliver_follow_up(self):
        provider = MockProvider([Message("assistant", "", stop_reason="error", error_message="错误对照")])
        agent = Agent(provider, ToolRouter({}), [])
        agent.follow_up("后续要求")
        result = await agent.prompt([Message("user", "初始任务")])
        self.assertEqual(result.status, "error")
        self.assertEqual(len(provider.requests), 1)
        self.assertNotIn("后续要求", self.text(result.messages))
        self.assertEqual(agent._follow_up_queue.drain_one(), [Message("user", "后续要求")])

    async def test_cancel_before_first_request_keeps_both_queues(self):
        provider = MockProvider([Message("assistant", "不应请求")])
        agent = Agent(provider, ToolRouter({}), [])
        agent.steer("方向要求")
        agent.follow_up("后续要求")
        pending = agent.prompt([Message("user", "初始任务")])
        agent.abort()
        result = await pending
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(provider.requests, [])
        self.assertEqual(agent._steering_queue.drain_one(), [Message("user", "方向要求")])
        self.assertEqual(agent._follow_up_queue.drain_one(), [Message("user", "后续要求")])


if __name__ == "__main__":
    unittest.main()
