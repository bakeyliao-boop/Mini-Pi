"""D13-C Agent 入队入口局部反例；循环递送时序由后续集成测试验收。"""

import unittest
from unittest.mock import AsyncMock, Mock

from mini_pi.agent import Agent
from mini_pi.models import Message


class AgentInputQueueTests(unittest.TestCase):
    def make_agent(self):
        provider = Mock()
        provider.generate = AsyncMock()
        executor = Mock()
        executor.execute = AsyncMock()
        return Agent(provider, executor, []), provider, executor

    def test_each_entry_queues_user_text_without_starting_a_run(self):
        agent, provider, executor = self.make_agent()
        agent.steer("先解释")
        agent.follow_up("最后总结")
        self.assertFalse(agent.is_running)
        self.assertEqual(agent._steering_queue.drain_one(), [Message("user", "先解释")])
        self.assertEqual(agent._follow_up_queue.drain_one(), [Message("user", "最后总结")])
        self.assertEqual(agent._steering_queue.drain_one(), [])
        self.assertEqual(agent._follow_up_queue.drain_one(), [])
        provider.generate.assert_not_called()
        executor.execute.assert_not_called()

    def test_invalid_input_is_rejected_by_both_entries(self):
        agent, provider, executor = self.make_agent()
        for method in (agent.steer, agent.follow_up):
            for value in (None, "", " \n", 123):
                with self.subTest(method=method.__name__, value=value):
                    with self.assertRaises(ValueError):
                        method(value)
        self.assertEqual(agent._steering_queue.drain_one(), [])
        self.assertEqual(agent._follow_up_queue.drain_one(), [])
        provider.generate.assert_not_called()
        executor.execute.assert_not_called()

    def test_instances_do_not_share_pending_inputs(self):
        first, _, _ = self.make_agent()
        second, _, _ = self.make_agent()
        first.steer("A的方向")
        second.follow_up("B的后续")
        self.assertEqual(second._steering_queue.drain_one(), [])
        self.assertEqual(first._follow_up_queue.drain_one(), [])
        self.assertEqual(first._steering_queue.drain_one(), [Message("user", "A的方向")])
        self.assertEqual(second._follow_up_queue.drain_one(), [Message("user", "B的后续")])


if __name__ == "__main__":
    unittest.main()
