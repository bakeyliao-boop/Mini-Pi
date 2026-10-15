"""助手准备：等待入口的启动、超时来源和协程清理边界。"""

import asyncio
import unittest
from unittest.mock import Mock

from mini_pi.run_deadline import RunDeadlineExceeded, await_before_deadline


class RunDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_deadline_returns_real_result(self):
        expected = object()

        async def complete():
            return expected

        operation = Mock(side_effect=complete)
        result = await await_before_deadline(operation, None)
        self.assertIs(result, expected)
        operation.assert_called_once_with()

    async def test_expired_deadline_does_not_start_operation(self):
        operation = Mock(side_effect=AssertionError("截止时间已到，不应启动操作"))
        deadline = asyncio.get_running_loop().time() - 1
        with self.assertRaises(RunDeadlineExceeded):
            await await_before_deadline(operation, deadline)
        operation.assert_not_called()

    async def test_result_before_deadline_is_preserved(self):
        expected = object()

        async def complete():
            return expected

        deadline = asyncio.get_running_loop().time() + 1
        result = await await_before_deadline(complete, deadline)
        self.assertIs(result, expected)

    async def test_waiting_operation_is_cancelled_and_cleaned_up(self):
        cleaned = False

        async def wait():
            nonlocal cleaned
            try:
                await asyncio.Future()
            finally:
                cleaned = True

        deadline = asyncio.get_running_loop().time() + 0.03
        async with asyncio.timeout(2):
            with self.assertRaises(RunDeadlineExceeded):
                await await_before_deadline(wait, deadline)
        self.assertTrue(cleaned)

    async def test_operation_own_timeout_is_not_misclassified(self):
        own_error = TimeoutError("模型或工具自身报告的超时")

        async def fail():
            raise own_error

        deadline = asyncio.get_running_loop().time() + 1
        with self.assertRaises(TimeoutError) as caught:
            await await_before_deadline(fail, deadline)
        self.assertIs(caught.exception, own_error)
        self.assertNotIsInstance(caught.exception, RunDeadlineExceeded)

    async def test_external_cancellation_is_not_misclassified_as_timeout(self):
        started = asyncio.Event()
        cleaned = False

        async def wait():
            nonlocal cleaned
            started.set()
            try:
                await asyncio.Future()
            finally:
                cleaned = True

        deadline = asyncio.get_running_loop().time() + 1
        async with asyncio.timeout(2):
            task = asyncio.create_task(await_before_deadline(wait, deadline))
            self.addAsyncCleanup(self._ensure_task_stopped, task)
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(cleaned)

    async def _ensure_task_stopped(self, task):
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


if __name__ == "__main__":
    unittest.main()
