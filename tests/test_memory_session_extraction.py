"""真实临时JSONL到提取五组的离线接线；不证明新提示的真实模型语义效果。"""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from examples.memory_session_v2_demo import (
    SYNTHETIC_KEY, SYNTHETIC_MODEL, TOOL_DATA, USER_TEXT, fixed_response, write_demo_session,
)
from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.extraction_client import MemoryExtractor
from mini_pi.memory.models import MemoryScope
from mini_pi.memory.planning import RememberPlan, plan_candidate
from mini_pi.memory.session_source import read_memory_source
from mini_pi.memory.store import MemoryStore
from mini_pi.session_records import read_session_records


ROUTES = {"long_term", "task_constraint", "ignore", "needs_review", "withdrawal"}


class SessionExtractionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="session-extraction-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "saved-session.jsonl"
        self.indices = write_demo_session(self.path)
        self.scope = MemoryScope("demo-user", "mini-pi-demo")
        self.original_bytes = self.path.read_bytes()
        self.database = self.enterContext(patch("sqlite3.connect", side_effect=AssertionError("不得开库")))
        self.environment = self.enterContext(patch("mini_pi.qwen_client.os.getenv", side_effect=AssertionError("不得读取环境凭据")))
        self.execute = self.enterContext(patch("mini_pi.memory.execution.execute_plans", side_effect=AssertionError("不得执行写入计划")))
        self.tool = self.enterContext(patch("mini_pi.tools.run_tests.RunTestsExecutor.execute", new_callable=AsyncMock,
                                          side_effect=AssertionError("不得重跑历史工具")))
        self.sync_network = self.enterContext(patch("mini_pi.qwen_client.post_json", side_effect=AssertionError("不得发同步网络请求")))
        self.post = self.enterContext(patch("mini_pi.qwen_client.post_json_async", new_callable=AsyncMock,
                                          side_effect=self.respond))

    async def respond(self, endpoint, key, payload, timeout):
        material = json.loads(payload["messages"][1]["content"])
        return fixed_response(material["role"])

    def extractor(self):
        return MemoryExtractor(api_key=SYNTHETIC_KEY, model=SYNTHETIC_MODEL,
                               base_url="https://synthetic.invalid/v1", timeout=2.0, max_requests=2)

    def tearDown(self):
        self.database.assert_not_called()
        self.environment.assert_not_called()
        self.execute.assert_not_called()
        self.tool.assert_not_called()
        self.sync_network.assert_not_called()
        self.assertEqual(self.path.read_bytes(), self.original_bytes)

    async def test_saved_user_source_traverses_parent_extract_and_returns_all_groups_then_readonly_plan(self):
        bound = []

        def read_and_capture(*args, **kwargs):
            source = read_memory_source(*args, **kwargs)
            bound.append(source)
            return source

        extractor = self.extractor()
        with patch("mini_pi.memory.extraction_client.read_memory_source", side_effect=read_and_capture):
            groups = await extractor.extract_session(self.scope, self.path, self.indices["user"])
        self.assertEqual(set(groups), ROUTES)
        self.assertEqual({route: len(items) for route, items in groups.items()},
                         {"long_term": 1, "task_constraint": 1, "needs_review": 2, "ignore": 1, "withdrawal": 0})
        self.assertTrue(all(isinstance(items, tuple) for items in groups.values()))
        self.assertEqual(len(bound), 1)
        for items in groups.values():
            for candidate in items:
                self.assertIs(candidate.source, bound[0])
        self.assertEqual((bound[0].scope, bound[0].role, bound[0].text), (self.scope, "user", USER_TEXT))
        records = read_session_records(self.path)
        self.assertEqual(bound[0].recorded_at, records[self.indices["user"]]["timestamp"])
        self.assertEqual((self.post.await_count, extractor.request_count), (1, 1))
        endpoint, key, payload, timeout = self.post.await_args.args
        self.assertEqual((endpoint, key, timeout), ("https://synthetic.invalid/v1/chat/completions", SYNTHETIC_KEY, 2.0))
        self.assertEqual(json.loads(payload["messages"][1]["content"]),
                         {"role": "user", "recorded_at": bound[0].recorded_at, "text": USER_TEXT})
        self.assertNotIn("tools", payload)
        actual = [{"content": item.content, "proposed_route": item.proposed_route, "reason": item.reason}
                  for route in ("long_term", "task_constraint", "needs_review", "ignore") for item in groups[route]]
        expected = json.loads(fixed_response("user")["choices"][0]["message"]["content"])
        self.assertEqual(actual, expected)
        database_path = self.root / "memory" / "state.sqlite3"
        plan = plan_candidate(MemoryStore(database_path), self.scope, groups["long_term"][0],
                              action="remember", key="explanation_language", kind="semantic",
                              conditions=(), valid_from="2026-11-01T00:00:00+08:00")
        self.assertIsInstance(plan, RememberPlan)
        self.assertEqual((plan.draft.key, plan.draft.kind, plan.draft.conditions), ("explanation_language", "semantic", ()))
        self.assertEqual(plan.source, bound[0])
        self.assertFalse(database_path.parent.exists())

    async def test_saved_tool_result_preserves_complete_state_and_remains_observation(self):
        extractor = self.extractor()
        groups = await extractor.extract_session(self.scope, self.path, self.indices["tool"])
        self.assertEqual(set(groups), ROUTES)
        self.assertEqual({route: len(items) for route, items in groups.items()},
                         {"long_term": 0, "task_constraint": 1, "needs_review": 0, "ignore": 0, "withdrawal": 0})
        candidate = groups["task_constraint"][0]
        self.assertEqual(candidate.source.role, "tool")
        self.assertEqual(json.loads(candidate.source.text), TOOL_DATA)
        expected = json.loads(fixed_response("tool")["choices"][0]["message"]["content"])[0]
        self.assertEqual((candidate.content, candidate.proposed_route, candidate.reason),
                         (expected["content"], expected["proposed_route"], expected["reason"]))
        payload = self.post.await_args.args[2]
        self.assertEqual(json.loads(payload["messages"][1]["content"]),
                         {"role": "tool", "recorded_at": candidate.source.recorded_at, "text": candidate.source.text})
        self.assertEqual((self.post.await_count, extractor.request_count), (1, 1))

    async def test_bad_index_events_and_assistant_source_reject_before_send_without_replaying_tools(self):
        extractor = self.extractor()
        for index in (-1, True, "1", 99, self.indices["run_start"], self.indices["run_end"], self.indices["assistant"]):
            with self.subTest(index=index):
                with self.assertRaises(MemoryPolicyError):
                    await extractor.extract_session(self.scope, self.path, index)
        self.assertEqual(extractor.request_count, 0)
        self.post.assert_not_called()
        self.tool.assert_not_called()

    async def test_truncated_bad_json_and_transport_error_propagate_without_empty_fallback_or_session_change(self):
        truncated = fixed_response("user")
        truncated["choices"][0]["finish_reason"] = "length"
        bad_json = fixed_response("user")
        bad_json["choices"][0]["message"]["content"] = "[unfinished"
        for label, result, expected_error in (("length", truncated, MemoryPolicyError),
                                               ("json", bad_json, MemoryPolicyError),
                                               ("transport", RuntimeError("synthetic failure"), RuntimeError)):
            with self.subTest(label=label):
                extractor = self.extractor()
                self.post.reset_mock()
                if isinstance(result, Exception):
                    self.post.side_effect = result
                else:
                    self.post.side_effect = None
                    self.post.return_value = deepcopy(result)
                with self.assertRaises(expected_error):
                    await extractor.extract_session(self.scope, self.path, self.indices["user"])
                self.assertEqual((self.post.await_count, extractor.request_count), (1, 1))
                self.assertEqual(self.path.read_bytes(), self.original_bytes)
                self.assertEqual(len(extractor.request_records), 1)

    async def test_cancellation_reaches_parent_send_waits_cleanup_and_never_retries(self):
        started = asyncio.Event()
        cleaned = asyncio.Event()

        async def pending_request(*args):
            started.set()
            try:
                await asyncio.Future()
            finally:
                cleaned.set()

        self.post.side_effect = pending_request
        extractor = self.extractor()
        task = asyncio.create_task(extractor.extract_session(self.scope, self.path, self.indices["user"]))
        try:
            await asyncio.wait_for(started.wait(), timeout=2.0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.assertTrue(cleaned.is_set())
        self.assertEqual((self.post.await_count, extractor.request_count), (1, 1))
        self.assertEqual([record["status"] for record in extractor.request_records], ["cancelled"])


if __name__ == "__main__":
    unittest.main()
