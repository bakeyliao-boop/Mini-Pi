"""助手准备：保存Session到请求、真实文件工具及结束记录的整链离线验收。

模拟问题时间固定为2026-11-02，不代表执行当天；提取与回答为固定响应，
embedding为固定向量。SQLite、Session与read_file均操作真实合成临时文件。
"""

from copy import deepcopy
from functools import partial
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from examples.memory_session_v2_demo import FixedResponseExtractor, write_demo_session
from mini_pi.loop import run_loop
from mini_pi.memory.execution import execute_plans
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.planning import plan_candidate
from mini_pi.memory.request_context import prepare_context
from mini_pi.memory.store import MemoryStore
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore
from mini_pi.tools.read_file import ReadFileExecutor
from tests.test_memory_request_context import FixedEmbedder


class RecordingReader:
    def __init__(self, root, after_read=None):
        self.reader = ReadFileExecutor(root)
        self.after_read = after_read
        self.calls = []

    async def execute(self, call):
        self.calls.append(deepcopy(call))
        result = await self.reader.execute(call)
        if self.after_read is not None:
            self.after_read()
        return result


class MemoryContextAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = TemporaryDirectory(prefix="mini-pi-context-acceptance-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scope = MemoryScope("demo-user", "mini-pi-demo")
        self.original = self.root / "saved-session.jsonl"
        indexes = write_demo_session(self.original)
        self.original_bytes = self.original.read_bytes()
        extractor = FixedResponseExtractor()
        self.groups = await extractor.extract_session(self.scope, self.original, indexes["user"])
        self.database = self.root / "memory.sqlite3"
        self.store = MemoryStore(self.database)
        plan = plan_candidate(self.store, self.scope, self.groups["long_term"][0],
                              action="remember", key="explanation_language", kind="semantic",
                              conditions=(), valid_from="2026-11-01T00:00:00+08:00")
        self.assertFalse(self.database.exists())
        self.entry, = execute_plans(self.store, self.scope, (plan,))
        self.store = MemoryStore(self.database)  # 重新读取持久结果，不复用写入对象缓存。
        self.source_file = self.root / "discount.py"
        self.source_text = "def final_price(price, rate):\n    return price * rate\n"
        self.source_file.write_text(self.source_text, encoding="utf-8")
        self.session = SessionStore(self.root / "current-session.jsonl", run_id="acceptance-run")
        self.initial = [Message("system", "使用证据解释代码。"),
                        Message("user", "继续这个合成任务，读取discount.py并解释，保留原测试断言。")]
        self.provider = MockProvider([
            Message("assistant", "先读取文件。", [ToolCall("read-discount", "read_file", {"path": "discount.py"})]),
            Message("assistant", "已读取文件，本例未运行测试，也未修改代码。"),
        ])
        self.executor = RecordingReader(self.root)
        # 任务材料由教学调用方明确确认归属本任务，保留待核对标签，不自动推断。
        self.prepare = partial(prepare_context, self.store, self.scope, "讲解代码时的语言偏好",
                               embedder=FixedEmbedder(), at="2026-11-02T10:00:00+08:00",
                               task_material=self.groups["task_constraint"] + self.groups["needs_review"],
                               conditions=(), top_k=2, min_score=0.9, max_context_chars=30000)

    async def run_case(self, prepare=None):
        return await run_loop(self.provider, self.executor, self.initial,
                              [self.executor.reader.definition], session_store=self.session,
                              prepare_messages=prepare or self.prepare,
                              total_timeout_seconds=3, max_model_turns=3)

    def payload(self, turn):
        return json.loads(self.provider.requests[turn][1].content)

    def assert_preserved(self, result, expected_status):
        loaded = self.session.load()
        self.assertEqual(result.status, expected_status)
        self.assertEqual(result.messages, loaded.history)
        self.assertEqual(loaded.records[-1]["type"], "run_end")
        self.assertEqual(loaded.records[-1]["data"]["status"], expected_status)
        self.assertEqual(sum(record["type"] == "run_end" for record in loaded.records), 1)
        self.assertEqual(self.original.read_bytes(), self.original_bytes)
        self.assertEqual(self.source_file.read_text(encoding="utf-8"), self.source_text)
        self.assertNotIn('"memories"', self.session.path.read_text(encoding="utf-8"))

    async def test_session_extraction_write_retrieval_provider_real_file_and_finish(self):
        result = await self.run_case()
        self.assert_preserved(result, "finished")
        self.assertEqual(len(self.provider.requests), 2)
        self.assertEqual(len(self.executor.calls), 1)
        for turn in (0, 1):
            data = self.payload(turn)
            self.assertEqual(data["memories"][0]["memory_id"], self.entry.memory_id)
            self.assertEqual(data["memories"][0]["source"]["source_id"], self.entry.source.source_id)
            self.assertEqual([item["proposed_route"] for item in data["task_material"]],
                             ["task_constraint", "needs_review", "needs_review"])
        observed = self.provider.requests[1][-1]
        self.assertIsInstance(observed, ToolResult)
        self.assertEqual(observed.output, self.source_text)
        self.assertEqual(observed.tool_call_id, "read-discount")
        self.assertEqual(len(result.messages), 5)

    async def test_next_round_uses_replacement_after_real_tool(self):
        def update_preference():
            text = "从11月2日起改用TypeScript举例。"
            source = MemorySource("replacement", self.scope, "user", text, "2026-11-02T00:00:00+08:00")
            draft = MemoryDraft(self.entry.draft.key, 0, len(text), source.recorded_at, content=text)
            self.store.replace(self.scope, source, draft, expected_version=1, operation_id="replace-after-read")
        self.executor.after_read = update_preference
        result = await self.run_case()
        self.assert_preserved(result, "finished")
        self.assertEqual(self.payload(0)["memories"][0]["version"], 1)
        self.assertEqual(self.payload(1)["memories"][0]["version"], 2)
        self.assertIn("TypeScript", self.payload(1)["memories"][0]["content"])

    async def test_next_round_excludes_retracted_preference_after_real_tool(self):
        def retract_preference():
            source = MemorySource("withdrawal", self.scope, "user", "撤回语言偏好。", "2026-11-02T00:00:00+08:00")
            self.store.retract(self.scope, source, self.entry.draft.key,
                               expected_version=1, operation_id="withdraw-after-read")
        self.executor.after_read = retract_preference
        result = await self.run_case()
        self.assert_preserved(result, "finished")
        self.assertEqual(len(self.payload(0)["memories"]), 1)
        self.assertEqual(self.payload(1)["memories"], [])
        self.assertEqual(len(self.payload(1)["task_material"]), 3)

    async def test_second_retrieval_failure_keeps_first_tool_result_and_records_error(self):
        original_search = self.store.search
        searches = 0
        async def search_then_fail(*args, **kwargs):
            nonlocal searches
            searches += 1
            if searches == 2:
                raise OSError("synthetic second retrieval failure")
            return await original_search(*args, **kwargs)
        with patch.object(self.store, "search", side_effect=search_then_fail):
            result = await self.run_case()
        self.assert_preserved(result, "error")
        self.assertEqual(searches, 2)
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual(len(self.executor.calls), 1)
        self.assertIsInstance(result.messages[-1], ToolResult)
        self.assertEqual(result.messages[-1].output, self.source_text)
        self.assertIn("synthetic second retrieval failure", result.error)

    async def test_actual_character_budget_failure_stops_before_provider_or_tool(self):
        result = await self.run_case(partial(self.prepare, max_context_chars=1))
        self.assert_preserved(result, "error")
        self.assertEqual(self.provider.requests, [])
        self.assertEqual(self.executor.calls, [])
        self.assertEqual(result.messages, self.initial)
        self.assertIn("字符预算", result.error)


if __name__ == "__main__":
    unittest.main()
