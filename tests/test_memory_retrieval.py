"""MEM-03 输入辅助及单条可用性反例；尚不代表检索已接入 Store。"""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mini_pi.memory.codec import make_entry
from mini_pi.memory.errors import MemoryPolicyError
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.retrieval import is_usable
from mini_pi.memory.retrieval_helpers import normalize_read_request
from mini_pi.memory.sqlite_backend import SQLiteMemoryBackend
from mini_pi.memory.store import MemoryStore


class ReadRequestHelperTests(unittest.TestCase):
    def test_normalizes_time_and_condition_order(self):
        self.assertEqual(normalize_read_request(MemoryScope('A', 'Pi'),
            (('tz', 'Asia/Shanghai'), ('day', 'weekday')), '2026-10-19T18:00:00+08:00'),
            ((('day', 'weekday'), ('tz', 'Asia/Shanghai')), '2026-10-19T10:00:00.000000+00:00'))

    def test_rejects_invalid_scope(self):
        for scope in (None, 'A', MemoryScope('', 'Pi'), MemoryScope('A', ' ')):
            with self.subTest(scope=scope), self.assertRaises(MemoryPolicyError):
                normalize_read_request(scope, (), '2026-10-19T10:00:00Z')

    def test_rejects_invalid_time_and_duplicate_conditions(self):
        for conditions, at in [((), '2026-10-19'), ((), '2026-10-19T10:00:00'),
                               ((), 'invalid'), ([], '2026-10-19T10:00:00Z'),
                               ((('day', 'a'), ('day', 'b')), '2026-10-19T10:00:00Z')]:
            with self.subTest(conditions=conditions, at=at), self.assertRaises(MemoryPolicyError):
                normalize_read_request(MemoryScope('A', 'Pi'), conditions, at)


class MemoryUsabilityTests(unittest.TestCase):
    def setUp(self):
        self.scope = MemoryScope('A', 'Pi')
        source = MemorySource('fact', self.scope, 'user', '工作日晚上学习。',
                              '2026-10-19T09:00:00+08:00')
        draft = MemoryDraft('study_time', 0, len(source.text), source.recorded_at,
                            conditions=(('day', 'weekday'),))
        self.entry = make_entry(self.scope, source, draft)

    def usable(self, entry=None, **changes):
        args = dict(scope=self.scope, conditions=(('day', 'weekday'),),
                    at='2026-10-19T18:00:00+08:00')
        args.update(changes)
        return is_usable(entry or self.entry, **args)

    def test_other_user_or_project_rejected(self):
        for scope in (MemoryScope('B', 'Pi'), MemoryScope('A', 'Other')):
            with self.subTest(scope=scope):
                self.assertFalse(self.usable(scope=scope))

    def test_retracted_excluded_even_for_historical_question(self):
        self.assertFalse(self.usable(replace(self.entry, state='retracted')))

    def test_required_conditions_must_all_be_known_and_equal(self):
        self.assertTrue(self.usable())
        self.assertFalse(self.usable(conditions=()))
        self.assertFalse(self.usable(conditions=(('day', 'weekend'),)))
        self.assertTrue(self.usable(conditions=(('tz', 'Asia/Shanghai'), ('day', 'weekday'))))

    def test_unconditional_memory_applies_with_extra_scene_conditions(self):
        entry = replace(self.entry, draft=replace(self.entry.draft, conditions=()))
        self.assertTrue(self.usable(entry))

    def test_active_future_version_is_not_yet_applicable(self):
        self.assertFalse(self.usable(at='2026-10-19T08:59:59+08:00'))
        self.assertTrue(self.usable(at='2026-10-19T09:00:00+08:00'))

    def test_superseded_version_remains_usable_inside_original_interval(self):
        entry = replace(self.entry, state='superseded', valid_to='2026-10-19T16:00:00.000000+00:00')
        self.assertTrue(self.usable(entry))
        self.assertFalse(self.usable(entry, at='2026-10-20T00:00:00+08:00'))

    def test_time_comparison_handles_timezone_offsets(self):
        self.assertFalse(self.usable(at='2026-10-19T00:59:59Z'))
        self.assertTrue(self.usable(at='2026-10-19T01:00:00Z'))


class PersistedMemoryUsabilityTests(unittest.TestCase):
    """通过真实写入/更新/撤回准备数据；仍不代表 Store 检索已接通。"""

    def setUp(self):
        temp = TemporaryDirectory(prefix='_memory_usability_')
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'memory.sqlite3'
        self.scope = MemoryScope('A', 'Pi')
        self.conditions = (('day', 'weekday'), ('tz', 'Asia/Shanghai'))
        self.store = MemoryStore(self.path)
        self.source = MemorySource('one', self.scope, 'user', '工作日晚上学习。',
                                   '2026-10-19T09:00:00+08:00')
        self.draft = MemoryDraft('study_time', 0, len(self.source.text), self.source.recorded_at,
                                 conditions=self.conditions)
        self.first = self.store.remember(self.scope, self.source, self.draft)
        source2 = replace(self.source, source_id='two', text='工作日改成早上学习。')
        self.second = self.store.replace(self.scope, source2,
            replace(self.draft, end=len(source2.text), valid_from='2026-10-20T00:00:00+08:00'),
            expected_version=1, operation_id='update')

    def usable(self, entry, at, conditions=None):
        return is_usable(entry, self.scope, conditions=self.conditions if conditions is None else conditions,
                         at=at)

    def test_persisted_versions_switch_at_boundary_without_any_read_side_write(self):
        backend = SQLiteMemoryBackend(self.path)
        entries = backend.read_entries(self.scope)
        before = self.path.read_bytes()
        self.assertEqual([e.state for e in entries], ['superseded', 'active'])
        old, new = entries
        for at, expected in [('2026-10-19T08:59:59+08:00', [False, False]),
                             ('2026-10-19T09:00:00+08:00', [True, False]),
                             ('2026-10-19T23:59:59.999999+08:00', [True, False]),
                             ('2026-10-20T00:00:00+08:00', [False, True]),
                             ('2026-10-19T16:00:00Z', [False, True])]:
            with self.subTest(at=at):
                self.assertEqual([self.usable(e, at) for e in entries], expected)
        self.assertFalse(self.usable(new, '2026-10-20T09:00:00+08:00', (('day', 'weekday'),)))
        self.assertFalse(self.usable(new, '2026-10-20T09:00:00+08:00',
                                    (('day', 'weekday'), ('tz', 'UTC'))))
        self.assertTrue(self.usable(old, '2026-10-19T18:00:00+08:00',
                                   self.conditions + (('task', 'study'),)))
        self.assertEqual(backend.read_entries(self.scope), entries)
        self.assertEqual(self.path.read_bytes(), before)

    def test_real_retraction_excludes_all_versions_even_for_past_questions(self):
        control = replace(self.source, source_id='withdraw', text='不要再记住学习时间。')
        self.store.retract(self.scope, control, 'study_time', conditions=self.conditions,
                           expected_version=2, operation_id='withdraw')
        entries = SQLiteMemoryBackend(self.path).read_entries(self.scope)
        before = self.path.read_bytes()
        self.assertEqual([e.state for e in entries], ['retracted', 'retracted'])
        for at in ['2026-10-19T18:00:00+08:00', '2026-10-20T18:00:00+08:00']:
            with self.subTest(at=at):
                self.assertEqual([self.usable(e, at) for e in entries], [False, False])
        replay = self.store.remember(self.scope, self.source, self.draft)
        self.assertEqual(replay.state, 'retracted')
        self.assertFalse(self.usable(replay, '2026-10-19T18:00:00+08:00'))
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
