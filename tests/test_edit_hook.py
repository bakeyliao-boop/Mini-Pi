"""D18 edit_file 接线：模拟模型与真实临时文件，无外部请求。"""
import asyncio
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from mini_pi.loop import run_loop
from mini_pi.mock_provider import MockProvider
from mini_pi.models import Message, ToolCall, ToolResult
from mini_pi.session_store import SessionStore
from mini_pi.tools.edit_executor import EditFileExecutor
from mini_pi.tools.edit_policy import EditPolicy
from mini_pi.tools.tool_router import ToolRouter


class EditHookTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix='mini-pi-edit-hook-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('app.py', 'test_login.py', 'outside_allowlist.py'):
            (self.root / name).write_text('old\n', encoding='utf-8')
        self.editor = EditFileExecutor(EditPolicy(self.root, ['app.py', 'test_login.py']))
        self.router = ToolRouter({'edit_file': self.editor})
        self.store = SessionStore(self.root / 'session.jsonl', 'd18-test')

    def make_call(self, name='app.py', identifier='edit-1'):
        return ToolCall(identifier, 'edit_file', {'path': name, 'old_text': 'old', 'new_text': 'new'})

    async def run_case(self, call, rule=None, timeout=None):
        model = MockProvider([
            Message('assistant', '编辑文件', [call], stop_reason='toolUse'),
            Message('assistant', '收到工具结果', stop_reason='stop'),
        ])
        result = await run_loop(model, self.router, [Message('user', '处理任务')],
                                [self.editor.definition], session_store=self.store,
                                before_tool_call=rule, total_timeout_seconds=timeout)
        return result, model

    def result_seen_by_model(self, model):
        self.assertEqual(len(model.requests), 2)
        found = [item for item in model.requests[1] if isinstance(item, ToolResult)]
        self.assertEqual(len(found), 1)
        return found[0]

    async def test_rule_denies_test_file_without_writing_and_reason_reaches_model(self):
        rule = AsyncMock(return_value='规则禁止修改测试文件')
        with patch.object(self.editor, '_execute_validated', wraps=self.editor._execute_validated) as operation:
            result, model = await self.run_case(self.make_call('test_login.py'), rule)
        self.assertEqual(result.status, 'finished')
        operation.assert_not_awaited()
        rule.assert_awaited_once()
        self.assertEqual((self.root / 'test_login.py').read_text(encoding='utf-8'), 'old\n')
        seen = self.result_seen_by_model(model)
        self.assertEqual((seen.tool_call_id, seen.error), ('edit-1', '执行前规则拒绝：规则禁止修改测试文件'))
        self.assertIn(seen, self.store.load().history)

    async def test_allow_rule_edits_real_temp_file(self):
        rule = AsyncMock(return_value=None)
        result, model = await self.run_case(self.make_call(), rule)
        self.assertEqual(result.status, 'finished')
        rule.assert_awaited_once()
        self.assertEqual((self.root / 'app.py').read_text(encoding='utf-8'), 'new\n')
        self.assertIsNone(self.result_seen_by_model(model).error)

    async def test_without_rule_existing_edit_still_works(self):
        result, model = await self.run_case(self.make_call())
        self.assertEqual(result.status, 'finished')
        self.assertEqual((self.root / 'app.py').read_text(encoding='utf-8'), 'new\n')
        self.assertIsNone(self.result_seen_by_model(model).error)

    async def test_invalid_arguments_never_run_rule_or_write(self):
        rule = AsyncMock(return_value=None)
        call = ToolCall('bad-1', 'edit_file', {'path': 'app.py', 'old_text': 'old'})
        with patch.object(self.editor, '_execute_validated', wraps=self.editor._execute_validated) as operation:
            result, model = await self.run_case(call, rule)
        self.assertEqual(result.status, 'finished')
        rule.assert_not_awaited()
        operation.assert_not_awaited()
        self.assertEqual((self.root / 'app.py').read_text(encoding='utf-8'), 'old\n')
        self.assertEqual(self.result_seen_by_model(model).tool_call_id, 'bad-1')
        self.assertTrue(self.result_seen_by_model(model).error)

    async def test_rule_allows_but_base_allowlist_still_blocks_write(self):
        rule = AsyncMock(return_value=None)
        result, model = await self.run_case(self.make_call('outside_allowlist.py'), rule)
        self.assertEqual(result.status, 'finished')
        rule.assert_awaited_once()
        self.assertEqual((self.root / 'outside_allowlist.py').read_text(encoding='utf-8'), 'old\n')
        self.assertIn('允许', self.result_seen_by_model(model).error)

    async def test_cancel_after_rule_does_not_start_edit(self):
        async def cancel_rule(_call):
            asyncio.current_task().cancel()
            return None
        with patch.object(self.editor, '_execute_validated', wraps=self.editor._execute_validated) as operation:
            result, model = await asyncio.create_task(self.run_case(self.make_call(), cancel_rule))
        self.assertEqual(result.status, 'cancelled')
        operation.assert_not_awaited()
        self.assertEqual((self.root / 'app.py').read_text(encoding='utf-8'), 'old\n')
        self.assertEqual(len(model.requests), 1)

    async def test_timeout_after_rule_does_not_start_edit(self):
        called = False
        async def slow_rule(_call):
            nonlocal called
            called = True
            time.sleep(0.30)
            return None
        with patch.object(self.editor, '_execute_validated', wraps=self.editor._execute_validated) as operation:
            result, model = await self.run_case(self.make_call(), slow_rule, timeout=0.15)
        self.assertTrue(called)
        self.assertEqual(result.status, 'timeout')
        operation.assert_not_awaited()
        self.assertEqual((self.root / 'app.py').read_text(encoding='utf-8'), 'old\n')
        self.assertEqual(len(model.requests), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
