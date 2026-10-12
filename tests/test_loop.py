"""用可预测的模拟响应和真实读取工具验证循环，不调用模型服务。"""

import asyncio
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.tools.read_file import ReadFileExecutor


class RecordingExecutor:
    """记录实际交给执行器的调用，读取仍由 D05 的真实工具完成。"""

    def __init__(self, executor):
        self.executor = executor
        self.calls = []

    async def execute(self, call):
        self.calls.append(deepcopy(call))
        return await self.executor.execute(call)


class LoopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        test_parent = Path(__file__).resolve().parent
        self.temp = TemporaryDirectory(prefix="_loop_", dir=test_parent)
        self.root = Path(self.temp.name).resolve()
        self.root.relative_to(test_parent)
        self.addCleanup(self.temp.cleanup)
        self.source = "def final_price(price, discount_rate):\n    return price * discount_rate\n"
        (self.root / "discount.py").write_text(self.source, encoding="utf-8")
        self.reader = ReadFileExecutor(self.root)
        self.executor = RecordingExecutor(self.reader)
        self.user = Message(role="user", content="读取 discount.py 并解释代码。")

    def request(self, call_id, path):
        return Message(
            role="assistant",
            content="先读取文件。",
            tool_calls=[ToolCall(call_id, "read_file", {"path": path})],
        )

    async def run_case(self, provider, initial=None):
        if initial is None:
            initial = [self.user]
        return await asyncio.wait_for(
            run_loop(provider, self.executor, initial, [self.reader.definition]),
            timeout=3,
        )

    async def test_second_request_sees_result_and_matching_call(self):
        request = self.request("call_001", "discount.py")
        initial = [self.user]

        def answer(history, tools):
            self.assertEqual(len(history), 3)
            self.assertEqual(history[:2], [self.user, request])
            result = history[2]
            self.assertIsInstance(result, ToolResult)
            self.assertEqual(result.tool_call_id, request.tool_calls[0].id)
            self.assertEqual(result.tool_name, request.tool_calls[0].name)
            self.assertEqual(result.output, self.source)
            self.assertIsNone(result.error)
            self.assertEqual(tools, [self.reader.definition])
            return Message(role="assistant", content="读取内容：\n" + result.output)

        provider = MockProvider([request, answer])
        run = await self.run_case(provider, initial)
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(provider.requests[0], [self.user])
        self.assertEqual(initial, [self.user])
        self.assertEqual(run.messages[:3], provider.requests[1])
        self.assertEqual(len(run.messages), 4)
        self.assertEqual(run.messages[-1].content, "读取内容：\n" + self.source)
        self.assertEqual(run.status, "finished")
        self.assertIsNone(run.task_passed)
        self.assertEqual(self.executor.calls, request.tool_calls)

    async def test_no_tool_calls_finishes_without_executing_text(self):
        response = Message(role="assistant", content="read_file 是一个读取工具。")
        provider = MockProvider([response])
        run = await self.run_case(provider)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(self.executor.calls, [])
        self.assertEqual(run.messages, [self.user, response])
        self.assertEqual(run.status, "finished")
        self.assertIsNone(run.task_passed)

    async def test_failed_calls_do_not_skip_later_calls_in_same_turn(self):
        calls = [
            ToolCall("call_missing", "read_file", {"path": "missing.txt"}),
            ToolCall("call_invalid", "read_file", {"path": 123}),
            ToolCall("call_good", "read_file", {"path": "discount.py"}),
        ]
        request = Message(role="assistant", content="依次读取三个目标。", tool_calls=calls)

        def answer(history, tools):
            self.assertEqual(history[:2], [self.user, request])
            results = history[2:]
            self.assertEqual(len(results), 3)
            self.assertTrue(all(isinstance(result, ToolResult) for result in results))
            self.assertEqual([result.tool_call_id for result in results], [call.id for call in calls])
            self.assertEqual([result.tool_name for result in results], [call.name for call in calls])
            self.assertIn("文件不存在", results[0].error or "")
            self.assertIn("path 必须是非空字符串", results[1].error or "")
            self.assertIsNone(results[2].error)
            self.assertEqual(results[2].output, self.source)
            return Message(role="assistant", content="两个调用失败，第三个读取成功。")

        provider = MockProvider([request, answer])
        run = await self.run_case(provider)
        self.assertEqual(self.executor.calls, calls)
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(len(run.messages), 6)
        self.assertEqual(run.status, "finished")
        self.assertIsNone(run.task_passed)

    async def test_error_feedback_can_produce_another_tool_turn(self):
        failed_request = self.request("call_001", "missing.txt")
        retry_request = self.request("call_002", "discount.py")

        def retry(history, tools):
            self.assertEqual(len(history), 3)
            self.assertEqual(history[:2], [self.user, failed_request])
            self.assertEqual(history[-1].tool_call_id, "call_001")
            self.assertIn("文件不存在", history[-1].error or "")
            return retry_request

        def answer(history, tools):
            self.assertEqual(len(history), 5)
            self.assertEqual(history[3], retry_request)
            self.assertEqual(history[4].tool_call_id, "call_002")
            self.assertEqual(history[4].output, self.source)
            self.assertIsNone(history[4].error)
            return Message(role="assistant", content="重新读取成功：\n" + history[4].output)

        provider = MockProvider([failed_request, retry, answer])
        run = await self.run_case(provider)
        self.assertEqual([len(history) for history in provider.requests], [1, 3, 5])
        self.assertEqual([call.id for call in self.executor.calls], ["call_001", "call_002"])
        self.assertEqual(len(run.messages), 6)
        self.assertEqual(run.status, "finished")

    async def test_repeated_runs_have_identical_histories_and_status(self):
        runs = []
        snapshots = []

        def answer(history, tools):
            result = history[-1]
            self.assertIsInstance(result, ToolResult)
            self.assertEqual(result.output, self.source)
            return Message(role="assistant", content="读取内容：\n" + result.output)

        for _ in range(3):
            provider = MockProvider([self.request("call_001", "discount.py"), answer])
            runs.append(await self.run_case(provider))
            snapshots.append(provider.requests)
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(runs[1], runs[2])
        self.assertEqual(snapshots[0], snapshots[1])
        self.assertEqual(snapshots[1], snapshots[2])
        self.assertEqual(len(self.executor.calls), 3)


if __name__ == "__main__":
    unittest.main()
