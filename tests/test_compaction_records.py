"""摘要记录格式检查。"""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mini_pi.models import Message
from mini_pi.session_records import check_compaction_data, find_compaction_record, read_session_records
from mini_pi.session_store import SessionStore


class CompactionRecordTests(unittest.TestCase):
    def test_find_compaction_returns_record_position_and_rejects_duplicates(self):
        record = {"type": "compaction", "data": {"summary": "测试失败"}}
        records = [{"type": "message"}, record, {"type": "message"}]
        self.assertEqual(find_compaction_record(records), (1, record))
        self.assertIsNone(find_compaction_record([{"type": "message"}]))
        with self.assertRaises(ValueError):
            find_compaction_record(records + [record])

    def test_reader_accepts_valid_compaction_but_history_stays_original(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            store = SessionStore(path, "run-a")
            store.append_item(Message("user", "原始任务"))
            data = {"summary": "测试失败", "session_id": "session-a", "history_count": 2,
                    "cut_index": 1, "history_fingerprint": "a" * 64}
            record = {"type": "compaction", "run_id": "run-a", "timestamp": "2026-10-29T00:00:00+08:00",
                      "data": data}
            with path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
            loaded = store.load()
            self.assertEqual(loaded.records[-1], record)
            self.assertEqual(loaded.history, [Message("user", "原始任务")])
            data["cut_index"] = 2
            with path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
            with self.assertRaisesRegex(ValueError, "第 3 行"):
                read_session_records(path)

    def test_valid_record_and_invalid_fields(self):
        valid = {"summary": "测试失败，待排查", "session_id": "session-a", "history_count": 5,
                 "cut_index": 4, "history_fingerprint": "a" * 64}
        self.assertIsNone(check_compaction_data(valid))
        invalid = []
        for key, value in (("summary", " "), ("session_id", ""), ("history_count", True),
                           ("history_count", 1), ("cut_index", 5), ("cut_index", True),
                           ("history_fingerprint", "z" * 64), ("history_fingerprint", "a" * 63)):
            record = deepcopy(valid)
            record[key] = value
            invalid.append(record)
        missing = deepcopy(valid)
        del missing["summary"]
        invalid.extend([missing, {**valid, "unexpected": "value"}, None])
        for record in invalid:
            with self.subTest(record=record), self.assertRaises(ValueError):
                check_compaction_data(record)


if __name__ == "__main__":
    unittest.main()
