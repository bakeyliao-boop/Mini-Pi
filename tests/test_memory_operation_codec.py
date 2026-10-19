"""MEM-02 辅助验收：规范请求内容与严格回执，不代替业务版本门禁。"""

from dataclasses import replace
from datetime import datetime
import json
import unittest
from unittest.mock import patch

from mini_pi.memory.codec import make_entry
from mini_pi.memory.errors import MemoryDataError, MemoryPolicyError
from mini_pi.memory.models import MemoryDraft, MemoryReceipt, MemoryScope, MemorySource
from mini_pi.memory.operation_codec import (
    dump_receipt, load_receipt, make_replace_receipt, replacement_fingerprint,
    validate_operation_input,
)


class MemoryOperationCodecTests(unittest.TestCase):
    def setUp(self):
        self.scope = MemoryScope("hyf", "mini-pi")
        self.source = MemorySource(
            "message_20", self.scope, "user", "从明天起，工作日早上学习。",
            "2026-10-19T14:00:00+08:00",
        )
        self.draft = MemoryDraft(
            "study_time", 0, len(self.source.text), "2026-10-20T00:00:00+08:00",
            conditions=(("weekday", "yes"), ("timezone", "Asia/Shanghai")),
        )
        self.entry = make_entry(
            self.scope, self.source, self.draft, version=2,
            written_at="2026-10-19T14:01:00+08:00",
        )
        self.digest = replacement_fingerprint(self.scope, self.source, self.draft, 1)

    def receipt(self):
        return make_replace_receipt(
            "replace-20", self.digest, 1, self.entry,
            written_at="2026-10-19T14:01:01+08:00",
        )

    def test_operation_input_rejects_bool_and_nonpositive_or_blank(self):
        for version in (True, False, 0, -1, "1", 1.0, None):
            with self.subTest(version=version), self.assertRaises(MemoryPolicyError):
                validate_operation_input(version, "request")
        for operation_id in ("", " \n", None, 1, [], True):
            with self.subTest(operation_id=operation_id), self.assertRaises(MemoryPolicyError):
                validate_operation_input(1, operation_id)
        validate_operation_input(1, " request ")

    def test_fingerprint_normalizes_equivalent_times_and_condition_order(self):
        normalized_source = replace(self.source, recorded_at="2026-10-19T06:00:00Z")
        normalized_draft = replace(
            self.draft, valid_from="2026-10-19T16:00:00.000000+00:00",
            conditions=tuple(reversed(self.draft.conditions)),
        )
        self.assertEqual(
            self.digest,
            replacement_fingerprint(self.scope, normalized_source, normalized_draft, 1),
        )
        self.assertRegex(self.digest, r"^[0-9a-f]{64}$")

    def test_fingerprint_covers_full_request_content(self):
        cases = [
            (self.scope, replace(self.source, source_id="message_21"), self.draft, 1),
            (self.scope, replace(self.source, text="从明天起，工作日晚上学习。"), self.draft, 1),
            (self.scope, replace(self.source, role="assistant"), self.draft, 1),
            (self.scope, replace(self.source, recorded_at="2026-10-19T14:00:01+08:00"), self.draft, 1),
            (self.scope, self.source, replace(self.draft, key="other"), 1),
            (self.scope, self.source, replace(self.draft, start=1), 1),
            (self.scope, self.source, replace(self.draft, end=self.draft.end - 1), 1),
            (self.scope, self.source, replace(self.draft, kind="episodic"), 1),
            (self.scope, self.source, replace(self.draft, valid_from="2026-10-21T00:00:00+08:00"), 1),
            (self.scope, self.source, replace(self.draft, conditions=(("weekday", "no"),)), 1),
            (self.scope, self.source, self.draft, 2),
        ]
        for scope in (MemoryScope("other", "mini-pi"), MemoryScope("hyf", "other")):
            cases.append((scope, replace(self.source, scope=scope), self.draft, 1))
        for index, request in enumerate(cases):
            with self.subTest(index=index):
                self.assertNotEqual(self.digest, replacement_fingerprint(*request))

    def test_fingerprint_does_not_strip_identity_or_source_text(self):
        variants = [
            replace(self.source, source_id=" message_20 "),
            replace(self.source, text=" " + self.source.text),
        ]
        for source in variants:
            with self.subTest(source=source):
                self.assertNotEqual(
                    self.digest, replacement_fingerprint(self.scope, source, self.draft, 1),
                )
        spaced = make_replace_receipt(" replace-20 ", self.digest, 1, self.entry)
        self.assertEqual(" replace-20 ", load_receipt(dump_receipt(spaced)).operation_id)

    def test_fingerprint_checks_shape_without_applying_source_admission(self):
        # 模型原话与片段不因此可入库，但计算指纹本身不隐藏业务门禁。
        digest = replacement_fingerprint(
            self.scope, replace(self.source, role="assistant"),
            replace(self.draft, start=1), 1,
        )
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        for version in (True, 0, "1"):
            with self.subTest(version=version), self.assertRaises(MemoryPolicyError):
                replacement_fingerprint(self.scope, self.source, self.draft, version)
        with self.assertRaises(MemoryPolicyError):
            replacement_fingerprint(MemoryScope("other", "mini-pi"), self.source, self.draft, 1)

    def test_receipt_assembly_uses_result_and_does_not_infer_transition(self):
        historical = replace(self.entry, state="retracted", version=7)
        receipt = make_replace_receipt("operation", self.digest, 1, historical)
        self.assertEqual(7, receipt.result_version)
        self.assertEqual(1, receipt.expected_version)
        self.assertEqual(historical.memory_id, receipt.result_memory_id)
        self.assertEqual(historical.source, receipt.source)
        self.assertEqual(historical.draft.key, receipt.key)
        self.assertEqual(historical.draft.conditions, receipt.conditions)
        self.assertEqual("retracted", historical.state)
        self.assertIsNotNone(datetime.fromisoformat(receipt.written_at).utcoffset())

    def test_receipt_roundtrip_and_representation_are_normalized(self):
        receipt = self.receipt()
        unnormalized = replace(
            receipt, source=self.source,
            conditions=tuple(reversed(receipt.conditions)),
            written_at="2026-10-19T14:01:01+08:00",
        )
        self.assertEqual(receipt, load_receipt(dump_receipt(unnormalized)))
        self.assertEqual(dump_receipt(receipt), dump_receipt(unnormalized))
        self.assertEqual("2026-10-19T06:01:01.000000+00:00", receipt.written_at)
        # 允许保留未来 retract 标签，不制造新事实或执行状态变化。
        retracted = replace(receipt, action="retract")
        self.assertEqual(retracted, load_receipt(dump_receipt(retracted)))

    def test_json_rejects_duplicate_fields_and_nonfinite_numbers(self):
        payload = dump_receipt(self.receipt())
        invalid = [
            '{"operation_id":"other",' + payload[1:],
            payload.replace('"user_id":"hyf"', '"user_id":"other","user_id":"hyf"', 1),
        ]
        for constant in ("NaN", "Infinity", "-Infinity"):
            invalid.append(payload.replace('"expected_version":1', f'"expected_version":{constant}'))
        for value in invalid:
            with self.subTest(payload=value), self.assertRaises(MemoryDataError):
                load_receipt(value)

    def test_saved_receipt_requires_exact_fields(self):
        data = json.loads(dump_receipt(self.receipt()))
        malformed = []
        for name in data:
            malformed.append({key: value for key, value in data.items() if key != name})
        malformed.append({**data, "unknown": "x"})
        malformed.append({**data, "scope": {**data["scope"], "unknown": "x"}})
        malformed.append({**data, "source": {**data["source"], "unknown": "x"}})
        malformed.append({**data, "source": {**data["source"], "scope": {"user_id": "hyf"}}})
        for index, value in enumerate(malformed):
            with self.subTest(index=index), self.assertRaises(MemoryDataError):
                load_receipt(json.dumps(value))

    def test_saved_receipt_rejects_invalid_values(self):
        data = json.loads(dump_receipt(self.receipt()))
        invalid = {
            "operation_id": (None, True, "", "  "),
            "action": ("update", None, 1, []),
            "request_hash": ("a" * 63, "A" * 64, "g" * 64, 1, None),
            "result_memory_id": ("a" * 65, "F" * 64, "x" * 64, False),
            "key": (None, "", 7),
            "expected_version": (True, 0, -1, 1.5, "1"),
            "result_version": (False, 0, -1, 1.5, "2"),
            "written_at": (None, 1, "2026-10-19T09:00:00", "not-a-time"),
            "conditions": ({}, None, ["x"], [["x"]], [["x", "a"], ["x", "b"]], [["x", 1]]),
            "scope": (None, [], {"user_id": 1, "project_id": "mini-pi"}),
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(MemoryDataError):
                    load_receipt(json.dumps({**data, field: value}))
        invalid_sources = [
            {**data["source"], "scope": {"user_id": "other", "project_id": "mini-pi"}},
            {**data["source"], "recorded_at": "2026-10-19T09:00:00"},
            {**data["source"], "recorded_at": None},
            {**data["source"], "text": 7},
            {**data["source"], "role": False},
        ]
        for source in invalid_sources:
            with self.subTest(source=source), self.assertRaises(MemoryDataError):
                load_receipt(json.dumps({**data, "source": source}))
        for payload in (None, 2, b"{}", "{}", "[]", "null", "{"):
            with self.subTest(payload=payload), self.assertRaises(MemoryDataError):
                load_receipt(payload)

    def test_in_memory_receipt_is_also_validated_before_dump(self):
        receipt = self.receipt()
        invalid = [
            replace(receipt, action="update"),
            replace(receipt, operation_id=""),
            replace(receipt, expected_version=True),
            replace(receipt, result_version=0),
            replace(receipt, request_hash="A" * 64),
            replace(receipt, result_memory_id="short"),
            replace(receipt, source=replace(receipt.source, scope=MemoryScope("other", "mini-pi"))),
            replace(receipt, conditions=(("x", "a"), ("x", "b"))),
            replace(receipt, written_at=None),
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(MemoryPolicyError):
                dump_receipt(value)
        with self.assertRaises(MemoryPolicyError):
            dump_receipt({})

    def test_helpers_do_not_perform_io_or_modify_inputs(self):
        original = (self.scope, self.source, self.draft, self.entry)
        with patch("builtins.open", side_effect=AssertionError("unexpected file IO")), patch(
            "sqlite3.connect", side_effect=AssertionError("unexpected database IO"),
        ):
            digest = replacement_fingerprint(self.scope, self.source, self.draft, 1)
            receipt = make_replace_receipt("operation", digest, 1, self.entry)
            restored = load_receipt(dump_receipt(receipt))
        self.assertEqual(receipt, restored)
        self.assertEqual(original, (self.scope, self.source, self.draft, self.entry))
        self.assertIsInstance(restored, MemoryReceipt)


if __name__ == "__main__":
    unittest.main()
