"""助手准备：真实工作线程配合事件同步，验证取消返回前工作已结束。"""

import asyncio
import threading
import unittest

from mini_pi.thread_worker import run_sync_with_cleanup


class BlockingWork:
    def __init__(self, loop, result=None, error=None):
        self.loop = loop
        self.result = result
        self.error = error
        self.started = asyncio.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        self.loop.call_soon_threadsafe(self.started.set)
        try:
            if not self.release.wait(3):
                raise RuntimeError("测试工作线程未收到释放许可")
            if self.error is not None:
                raise self.error
            return self.result
        finally:
            self.finished.set()


async def settle_thread_task(task, work):
    work.release.set()
    if not task.done():
        task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    if work.calls:
        await asyncio.to_thread(work.finished.wait, 3)


class ThreadWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.previous_handler = self.loop.get_exception_handler()
        self.background_errors = []
        self.loop.set_exception_handler(lambda loop, context: self.background_errors.append(context))

    async def asyncTearDown(self):
        await asyncio.sleep(0)
        self.loop.set_exception_handler(self.previous_handler)
        self.assertEqual(self.background_errors, [], "不应留下后台异常日志")

    async def test_normal_result_is_preserved_and_runs_in_worker_thread(self):
        owner_thread = threading.get_ident()
        expected = object()

        def complete():
            return expected, threading.get_ident()

        actual, worker_thread = await run_sync_with_cleanup(complete)
        self.assertIs(actual, expected)
        self.assertNotEqual(worker_thread, owner_thread)

    async def test_normal_failure_is_preserved(self):
        error = ValueError("同步工作自身失败")

        def fail():
            raise error

        with self.assertRaises(ValueError) as caught:
            await run_sync_with_cleanup(fail)
        self.assertIs(caught.exception, error)

    async def test_repeated_cancel_waits_for_thread_and_discards_result(self):
        work = BlockingWork(asyncio.get_running_loop(), result=object())
        task = asyncio.create_task(run_sync_with_cleanup(work))
        self.addAsyncCleanup(settle_thread_task, task, work)
        async with asyncio.timeout(2):
            await work.started.wait()
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.assertFalse(work.finished.is_set())
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            work.release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(work.finished.is_set())
        self.assertEqual(work.calls, 1)

    async def test_worker_failure_after_cancel_does_not_replace_cancellation(self):
        work = BlockingWork(asyncio.get_running_loop(), error=RuntimeError("工作线程自身失败"))
        task = asyncio.create_task(run_sync_with_cleanup(work))
        self.addAsyncCleanup(settle_thread_task, task, work)
        async with asyncio.timeout(2):
            await work.started.wait()
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            work.release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(work.finished.is_set())
        self.assertEqual(work.calls, 1)


if __name__ == "__main__":
    unittest.main()
