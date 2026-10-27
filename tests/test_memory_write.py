"""MEM-01：助手准备的入库反例；核心待手敲时应真实失败，不跳过。

这些测试只验证原话锚定、范围隔离与持久化，不认证原话的世界真实性。
retracted 用公开辅助接口预置，只验收重放不激活，不代表已有撤回 API。
"""

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from mini_pi.memory.errors import MemoryConflict, MemoryPolicyError
from mini_pi.memory.models import MemoryDraft, MemoryScope, MemorySource
from mini_pi.memory.policy import validate_draft


def sample_input():
    scope = MemoryScope("user_A", "project_A")
    source = MemorySource(
        "message_001", scope, "user", "我不喜欢 Python。",
        "2026-10-19T13:00:00+08:00",
    )
    draft = MemoryDraft(
        "language_preference", 0, len(source.text),
        "2026-10-19T13:00:00+08:00",
    )
    return scope, source, draft


def invalid_inputs():
    """供真实数据库拒绝测试复用的独立坏输入；不调用待测校验器造预期。"""
    scope, source, draft = sample_input()
    return [
        ("empty user", replace(scope, user_id=" "), source, draft),
        ("empty project", replace(scope, project_id=""), source, draft),
        ("foreign user", replace(scope, user_id="user_B"), source, draft),
        ("foreign project", replace(scope, project_id="project_B"), source, draft),
        ("assistant", scope, replace(source, role="assistant"), draft),
        ("system", scope, replace(source, role="system"), draft),
        ("tool semantic", scope, replace(source, role="tool"), draft),
        ("tool procedural", scope, replace(source, role="tool"),
         replace(draft, kind="procedural")),
        ("empty source id", scope, replace(source, source_id=""), draft),
        ("empty source text", scope, replace(source, text=""), draft),
        ("empty key", scope, source, replace(draft, key=" ")),
        ("unknown kind", scope, source, replace(draft, kind="preference")),
        ("bool offset", scope, source, replace(draft, start=False)),
        ("negative offset", scope, source, replace(draft, start=-1)),
        ("past end", scope, source, replace(draft, end=len(source.text) + 1)),
        ("negation removed", scope, source, replace(draft, start=2)),
        ("naive recorded time", scope,
         replace(source, recorded_at="2026-10-19T13:00:00"), draft),
        ("naive valid time", scope, source,
         replace(draft, valid_from="2026-10-19T13:00:00")),
        ("empty condition value", scope, source,
         replace(draft, conditions=(("mode", ""),))),
        ("duplicate condition key", scope, source,
         replace(draft, conditions=(("mode", "learn"), ("mode", "work")))),
    ]


class MemoryPolicyTests(unittest.TestCase):
    """可先单独运行：只验来源门禁，不依赖 SQLite 辅助层。"""

    def test_user_full_source_accepts_all_three_kinds_and_no_conditions(self):
        scope, source, draft = sample_input()
        for kind in ("semantic", "episodic", "procedural"):
            with self.subTest(kind=kind):
                self.assertIsNone(validate_draft(scope, source, replace(draft, kind=kind)))

    def test_nonempty_string_identifiers_text_and_supported_kind_are_required(self):
        scope, source, draft = sample_input()
        cases = []
        for value in ("", " ", None, 42):
            for field in ("user_id", "project_id"):
                bad_scope = replace(scope, **{field: value})
                cases.append((field, value, bad_scope, replace(source, scope=bad_scope), draft))
            cases.extend([
                ("source_id", value, scope, replace(source, source_id=value), draft),
                ("text", value, scope, replace(source, text=value), draft),
                ("key", value, scope, source, replace(draft, key=value)),
            ])
        cases.append(("kind", "unknown", scope, source, replace(draft, kind="preference")))
        for field, value, bad_scope, bad_source, bad_draft in cases:
            with self.subTest(field=field, value=value):
                with self.assertRaises(MemoryPolicyError):
                    validate_draft(bad_scope, bad_source, bad_draft)

    def test_user_and_project_scope_mismatches_are_both_rejected(self):
        scope, source, draft = sample_input()
        for other in (replace(scope, user_id="user_B"), replace(scope, project_id="project_B")):
            with self.subTest(scope=other):
                with self.assertRaises(MemoryPolicyError):
                    validate_draft(other, source, draft)

    def test_assistant_system_and_unknown_roles_cannot_be_memory_sources(self):
        scope, source, draft = sample_input()
        for role in ("assistant", "system", "developer", "", None):
            with self.subTest(role=role):
                with self.assertRaises(MemoryPolicyError):
                    validate_draft(scope, replace(source, role=role), draft)

    def test_tool_source_is_accepted_only_for_episodic_memory(self):
        scope, source, draft = sample_input()
        tool_source = replace(source, role="tool", text="进程以退出码 1 结束。")
        tool_draft = replace(draft, end=len(tool_source.text), kind="episodic")
        self.assertIsNone(validate_draft(scope, tool_source, tool_draft))
        for kind in ("semantic", "procedural"):
            with self.subTest(kind=kind):
                with self.assertRaises(MemoryPolicyError):
                    validate_draft(scope, tool_source, replace(tool_draft, kind=kind))

    def test_offsets_are_plain_integers_and_stay_inside_a_nonempty_span(self):
        scope, source, draft = sample_input()
        cases = [
            (False, draft.end), (0, True), (0.0, draft.end), (0, float(draft.end)),
            ("0", draft.end), (0, str(draft.end)), (-1, draft.end),
            (0, 0), (draft.end, draft.end), (draft.end, 0),
            (0, draft.end + 1),
        ]
        for start, end in cases:
            with self.subTest(start=start, end=end):
                with self.assertRaises(MemoryPolicyError):
                    validate_draft(scope, source, replace(draft, start=start, end=end))

    def test_partial_spans_cannot_remove_negation_or_other_original_context(self):
        scope, source, draft = sample_input()
        # 原话[2:]确实变成“喜欢 Python。”，必须拒绝而非只检查下标合法。
        self.assertEqual(source.text[2:], "喜欢 Python。")
        for start, end in ((2, draft.end), (0, draft.end - 1), (1, draft.end - 1)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(MemoryPolicyError):
                    validate_draft(scope, source, replace(draft, start=start, end=end))

    def test_recorded_and_valid_times_require_real_dates_and_explicit_timezones(self):
        scope, source, draft = sample_input()
        for value in ("2026-10-19T13:00:00", "not-a-time", "2026-02-30T13:00:00Z", "", None):
            for field in ("recorded_at", "valid_from"):
                with self.subTest(field=field, value=value):
                    bad_source = replace(source, recorded_at=value) if field == "recorded_at" else source
                    bad_draft = replace(draft, valid_from=value) if field == "valid_from" else draft
                    with self.assertRaises(MemoryPolicyError):
                        validate_draft(scope, bad_source, bad_draft)

    def test_conditions_require_unique_nonempty_string_pairs_in_tuples(self):
        scope, source, draft = sample_input()
        cases = [
            [], (("mode",),), (["mode", "learn"],), (("", "learn"),),
            (("mode", " "),), (("mode", 1),), ((1, "learn"),),
            (("mode", "learn"), ("mode", "work")),
        ]
        for conditions in cases:
            with self.subTest(conditions=conditions):
                with self.assertRaises(MemoryPolicyError):
                    validate_draft(scope, source, replace(draft, conditions=conditions))


class MemoryWriteTests(unittest.TestCase):
    """真实临时 SQLite 与独立 Python 进程；不以 mock 证明持久化。"""

    def setUp(self):
        # 局部导入让 policy 的手敲验收可以独立于数据库接线分段运行。
        from mini_pi.memory.codec import dump_entry, make_entry, normalize_draft, normalize_source
        from mini_pi.memory.sqlite_backend import SQLiteMemoryBackend
        from mini_pi.memory.store import MemoryStore

        self.store_class = MemoryStore
        self.backend_class = SQLiteMemoryBackend
        self.dump_entry = dump_entry
        self.make_entry = make_entry
        self.normalize_draft = normalize_draft
        self.normalize_source = normalize_source
        self.temp = TemporaryDirectory(prefix="_memory_write_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "memory" / "state.sqlite3"
        self.scope, self.source, self.draft = sample_input()

    def file_snapshot(self):
        return {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*") if path.is_file()
        }

    def entries(self, scope=None):
        return self.backend_class(self.path).read_entries(scope or self.scope)

    def test_full_original_text_round_trips_after_new_instance_and_new_process(self):
        saved = self.store_class(self.path).remember(self.scope, self.source, self.draft)
        self.assertTrue(self.path.is_file())
        self.assertEqual(saved.text, "我不喜欢 Python。")
        self.assertEqual((saved.version, saved.state), (1, "active"))
        self.assertEqual(self.store_class(self.path).get(self.scope, saved.memory_id), saved)

        script = """
import sys
from mini_pi.memory.codec import dump_entry
from mini_pi.memory.models import MemoryScope
from mini_pi.memory.store import MemoryStore
entry = MemoryStore(sys.argv[1]).get(MemoryScope(sys.argv[2], sys.argv[3]), sys.argv[4])
if entry is None:
    raise SystemExit("persisted entry missing")
print(dump_entry(entry))
"""
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", script, str(self.path),
             self.scope.user_id, self.scope.project_id, saved.memory_id],
            cwd=Path(__file__).resolve().parents[1], capture_output=True,
            text=True, encoding="utf-8", timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), json.loads(self.dump_entry(saved)))

    def test_real_session_source_round_trips_without_rewriting_original_jsonl(self):
        from mini_pi.memory.session_source import read_memory_source
        from mini_pi.models import Message
        from mini_pi.session_store import SessionStore

        session_path = self.root / "session.jsonl"
        SessionStore(session_path, run_id="memory_source_run").append_item(
            Message("user", "我不喜欢 Python。"),
        )
        original = session_path.read_bytes()
        source = read_memory_source(session_path, 0, self.scope)
        self.assertEqual((source.scope, source.role, source.text),
                         (self.scope, "user", "我不喜欢 Python。"))
        draft = MemoryDraft(
            "language_preference", 0, len(source.text), source.recorded_at,
        )
        try:
            saved = self.store_class(self.path).remember(self.scope, source, draft)
            restored = self.store_class(self.path).get(self.scope, saved.memory_id)
            self.assertEqual(restored, saved)
            self.assertEqual(restored.source, self.normalize_source(source))
            self.assertEqual(restored.source.source_id, source.source_id)
            self.assertEqual(restored.text, "我不喜欢 Python。")
        finally:
            # 核心占位失败时也核对：尝试入库不能改写原始 Session 证据。
            self.assertEqual(session_path.read_bytes(), original)

    def test_rejected_inputs_create_no_database_or_parent_directory(self):
        store = self.store_class(self.path)
        self.assertFalse(self.path.parent.exists(), "初始化不能先创建数据库目录")
        for label, scope, source, draft in invalid_inputs():
            with self.subTest(case=label):
                with self.assertRaises(MemoryPolicyError):
                    store.remember(scope, source, draft)
                self.assertFalse(self.path.parent.exists(), "门禁拒绝前后均不应落盘")

    def test_rejected_input_leaves_an_existing_database_byte_for_byte_unchanged(self):
        store = self.store_class(self.path)
        saved = store.remember(self.scope, self.source, self.draft)
        before = self.file_snapshot()
        for label, scope, source, draft in invalid_inputs():
            with self.subTest(case=label):
                with self.assertRaises(MemoryPolicyError):
                    store.remember(scope, source, draft)
                self.assertEqual(self.file_snapshot(), before)
        self.assertEqual(self.entries(), [saved])

    def test_exact_replay_is_idempotent_and_normalized_times_conditions_keep_identity(self):
        draft = replace(self.draft, conditions=(("subject", "python"), ("mode", "learn")))
        saved = self.store_class(self.path).remember(self.scope, self.source, draft)
        replay_source = replace(self.source, recorded_at="2026-10-19T05:00:00Z")
        replay_draft = replace(
            draft, valid_from="2026-10-19T05:00:00Z",
            conditions=(("mode", "learn"), ("subject", "python")),
        )
        replay = self.store_class(self.path).remember(self.scope, replay_source, replay_draft)
        self.assertEqual(replay, saved)
        self.assertEqual(saved.source.recorded_at, "2026-10-19T05:00:00.000000+00:00")
        self.assertEqual(saved.draft.valid_from, "2026-10-19T05:00:00.000000+00:00")
        self.assertEqual(saved.draft.conditions, (("mode", "learn"), ("subject", "python")))
        self.assertEqual(self.entries(), [saved])

    def test_replaying_a_seeded_retracted_entry_returns_it_without_reactivation(self):
        source = self.normalize_source(self.source)
        draft = self.normalize_draft(self.draft)
        seeded = self.make_entry(
            self.scope, source, draft, state="retracted",
            written_at="2026-10-19T05:01:00+00:00",
        )
        backend = self.backend_class(self.path)
        with backend.transaction() as connection:
            backend.insert_source(connection, source)
            backend.insert_entry(connection, seeded)
        before = self.file_snapshot()
        replay = self.store_class(self.path).remember(self.scope, self.source, self.draft)
        self.assertEqual(replay, seeded)
        self.assertEqual(replay.state, "retracted")
        self.assertEqual(self.entries(), [seeded])
        self.assertEqual(self.file_snapshot(), before)

    def test_reusing_source_id_with_different_content_role_or_time_is_a_conflict(self):
        store = self.store_class(self.path)
        saved = store.remember(self.scope, self.source, self.draft)
        before = self.file_snapshot()
        changed_sources = [
            replace(self.source, text="我更喜欢 Python。"),
            replace(self.source, role="tool"),
            replace(self.source, recorded_at="2026-10-20T13:00:00+08:00"),
        ]
        for source in changed_sources:
            draft = replace(self.draft, end=len(source.text), kind="episodic" if source.role == "tool" else "semantic")
            with self.subTest(source=source):
                with self.assertRaises(MemoryConflict):
                    store.remember(self.scope, source, draft)
                self.assertEqual(self.file_snapshot(), before)
        self.assertEqual(self.entries(), [saved])

    def test_same_source_candidate_cannot_silently_change_kind_or_valid_time(self):
        store = self.store_class(self.path)
        saved = store.remember(self.scope, self.source, self.draft)
        before = self.file_snapshot()
        for draft in (
            replace(self.draft, kind="procedural"),
            replace(self.draft, valid_from="2026-10-20T13:00:00+08:00"),
        ):
            with self.subTest(draft=draft):
                with self.assertRaises(MemoryConflict):
                    store.remember(self.scope, self.source, draft)
                self.assertEqual(self.file_snapshot(), before)
        self.assertEqual(self.entries(), [saved])

    def test_same_key_conditions_conflict_but_different_conditions_stay_independent(self):
        store = self.store_class(self.path)
        saved = store.remember(self.scope, self.source, self.draft)
        later_source = replace(self.source, source_id="message_002", text="我喜欢 Java。")
        later_draft = replace(self.draft, end=len(later_source.text))
        before = self.file_snapshot()
        with self.assertRaises(MemoryConflict):
            store.remember(self.scope, later_source, later_draft)
        self.assertEqual(self.file_snapshot(), before)
        backend = self.backend_class(self.path)
        with backend.transaction() as connection:
            self.assertIsNone(backend.get_source(connection, self.scope, "message_002"))
        self.assertEqual(self.entries(), [saved])
        independent = store.remember(
            self.scope, later_source,
            replace(later_draft, conditions=(("mode", "work"),)),
        )
        self.assertNotEqual(independent.memory_id, saved.memory_id)
        self.assertEqual({entry.memory_id for entry in self.entries()}, {saved.memory_id, independent.memory_id})

    def test_same_source_id_and_key_are_isolated_by_both_user_and_project(self):
        store = self.store_class(self.path)
        scopes = [
            self.scope, replace(self.scope, user_id="user_B"),
            replace(self.scope, project_id="project_B"),
        ]
        saved = []
        for index, scope in enumerate(scopes):
            source = replace(self.source, scope=scope, text=f"范围 {index} 的原话。")
            draft = replace(self.draft, end=len(source.text))
            saved.append(store.remember(scope, source, draft))
        self.assertEqual(len({entry.memory_id for entry in saved}), 3)
        for scope, expected in zip(scopes, saved):
            with self.subTest(scope=scope):
                self.assertEqual(self.entries(scope), [expected])
                self.assertEqual(store.get(scope, expected.memory_id), expected)
                for other in saved:
                    if other.scope != scope:
                        self.assertIsNone(store.get(scope, other.memory_id))


if __name__ == "__main__":
    unittest.main()
