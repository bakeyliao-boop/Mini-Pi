"""验证 Agent 将分开的资料准备配置传递给运行循环。"""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from mini_pi.agent import Agent
from mini_pi.context import ContextProvider, FullHistoryContext
from mini_pi.context_budget import ContextWindowBudget
from mini_pi.context_size import estimate_qwen_input
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message


class AgentSeparateContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_delivers_model_history_view_without_replacing_original(self):
        model = MockProvider([Message("assistant", "完成")])
        provider = ContextProvider(model, FullHistoryContext(), input_estimator=estimate_qwen_input,
                                   window_budget=ContextWindowBudget(10000, 100))
        agent = Agent(provider, SimpleNamespace(execute=AsyncMock()), [])
        original = [Message("user", "原始任务")]
        result = await agent.prompt(original, prepare_model_history=lambda history: [Message("user", "摘要视图")],
                                    max_context_chars=10000)
        self.assertEqual(result.status, "finished")
        self.assertEqual(model.requests[0], [Message("user", "摘要视图")])
        self.assertEqual(result.messages[0], original[0])
        self.assertEqual(original, [Message("user", "原始任务")])

    async def test_agent_delivers_reference_configuration(self):
        model = MockProvider([Message("assistant", "完成")])
        provider = ContextProvider(model, FullHistoryContext(), input_estimator=estimate_qwen_input,
                                   window_budget=ContextWindowBudget(10000, 100))
        agent = Agent(provider, SimpleNamespace(execute=AsyncMock()), [])
        prepare = AsyncMock(return_value=[Message("user", "本轮资料")])
        result = await agent.prompt([Message("user", "任务")], prepare_references=prepare,
                                    max_context_chars=10000)
        self.assertEqual(result.status, "finished")
        self.assertEqual(model.requests[0], [Message("user", "本轮资料"), Message("user", "任务")])
        prepare.assert_awaited_once()
        self.assertEqual(result.messages[0], Message("user", "任务"))


if __name__ == "__main__":
    unittest.main()
