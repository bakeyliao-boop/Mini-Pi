"""助手准备：短连接 SQLite I/O；不决定入库、覆盖、撤回或当前可用性。"""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from mini_pi.memory.codec import dump_entry, dump_source, load_entry, load_source
from mini_pi.memory.errors import MemoryDataError
from mini_pi.memory.models import Conditions, MemoryEntry, MemoryReceipt, MemoryScope, MemorySource
from mini_pi.memory.operation_codec import dump_receipt, load_receipt
from mini_pi.memory.validation_helpers import normalize_conditions


_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS sources (
        user_id TEXT NOT NULL, project_id TEXT NOT NULL, source_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (user_id, project_id, source_id)
    )""",
    """CREATE TABLE IF NOT EXISTS entries (
        user_id TEXT NOT NULL, project_id TEXT NOT NULL, memory_id TEXT NOT NULL,
        source_id TEXT NOT NULL, memory_key TEXT NOT NULL, conditions TEXT NOT NULL,
        version INTEGER NOT NULL CHECK (version > 0),
        state TEXT NOT NULL CHECK (state IN ('active', 'superseded', 'retracted')),
        payload TEXT NOT NULL,
        PRIMARY KEY (user_id, project_id, memory_id),
        UNIQUE (user_id, project_id, memory_key, conditions, version),
        FOREIGN KEY (user_id, project_id, source_id)
            REFERENCES sources (user_id, project_id, source_id)
    )""",
    """CREATE TABLE IF NOT EXISTS operation_receipts (
        user_id TEXT NOT NULL, project_id TEXT NOT NULL, operation_id TEXT NOT NULL,
        action TEXT NOT NULL CHECK (action IN ('replace', 'retract')),
        request_hash TEXT NOT NULL, memory_key TEXT NOT NULL, conditions TEXT NOT NULL,
        expected_version INTEGER NOT NULL CHECK (expected_version > 0),
        result_memory_id TEXT NOT NULL,
        result_version INTEGER NOT NULL CHECK (result_version > 0),
        source_id TEXT NOT NULL, payload TEXT NOT NULL,
        PRIMARY KEY (user_id, project_id, operation_id),
        FOREIGN KEY (user_id, project_id, result_memory_id)
            REFERENCES entries (user_id, project_id, memory_id),
        FOREIGN KEY (user_id, project_id, source_id)
            REFERENCES sources (user_id, project_id, source_id)
    )""",
)


def _scope_values(scope: MemoryScope) -> tuple[str, str]:
    if not isinstance(scope, MemoryScope) or any(
        not isinstance(value, str) or not value.strip()
        for value in (scope.user_id, scope.project_id)
    ):
        raise MemoryDataError("查询 scope 必须包含非空 user_id/project_id")
    return scope.user_id, scope.project_id


def _conditions(value: Conditions) -> str:
    return json.dumps(normalize_conditions(value), ensure_ascii=False, separators=(",", ":"))


class SQLiteMemoryBackend:
    def __init__(self, path: str | Path):
        # 仅登记路径；policy 拒绝之前不能创建目录、连接或数据库文件。
        self.path = Path(path).expanduser().resolve()

    @contextmanager
    def transaction(self):
        """一次短写事务；BaseException 也回滚，最后始终关闭连接。

        无后台线程；锁竞争立即显式失败。commit 成功不承诺跨存储事务或
        超出 SQLite/文件系统配置的断电持久化。同步数据库调用不是硬截止。
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, isolation_level=None, timeout=0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN IMMEDIATE")
            # 不使用 executescript：它可能提交当前事务，破坏下面的回滚边界。
            for statement in _SCHEMA:
                conn.execute(statement)
            yield conn
            conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _reader(self):
        # mode=ro 同时保证存在性检查后的删除竞争不会重新创建数据库。
        if not self.path.exists():
            yield None
            return
        conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, isolation_level=None, timeout=0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN")
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )}
            if not tables:
                # 首次写事务回滚可能留下空 SQLite 文件，尚无任何来源或记忆。
                yield None
            elif not {"sources", "entries"} <= tables:
                raise MemoryDataError("记忆数据库缺少必要表")
            else:
                yield conn
        except sqlite3.DatabaseError as error:
            raise MemoryDataError(f"记忆数据库无法读取：{error}") from error
        finally:
            if conn.in_transaction:
                conn.rollback()
            conn.close()

    def get_source(self, conn, scope: MemoryScope, source_id: str) -> MemorySource | None:
        row = conn.execute(
            "SELECT payload FROM sources WHERE user_id = ? AND project_id = ? AND source_id = ?",
            (*_scope_values(scope), source_id),
        ).fetchone()
        if row is None:
            return None
        source = load_source(row[0])
        if source.scope != scope or source.source_id != source_id:
            raise MemoryDataError("来源 payload 与查询范围/标识不一致")
        return source

    def insert_source(self, conn, source: MemorySource) -> None:
        payload = dump_source(source)
        normalized = load_source(payload)
        conn.execute(
            "INSERT INTO sources (user_id, project_id, source_id, payload) VALUES (?, ?, ?, ?)",
            (*_scope_values(normalized.scope), normalized.source_id, payload),
        )

    def _entry(self, conn, row, scope: MemoryScope) -> MemoryEntry | None:
        if row is None:
            return None
        entry = load_entry(row["payload"])
        if (
            entry.scope != scope or entry.memory_id != row["memory_id"]
            or entry.source.source_id != row["source_id"]
            or entry.draft.key != row["memory_key"]
            or _conditions(entry.draft.conditions) != row["conditions"]
            or entry.version != row["version"] or entry.state != row["state"]
        ):
            raise MemoryDataError("记忆 payload 与查询范围或索引列不一致")
        stored_source = self.get_source(conn, scope, entry.source.source_id)
        if stored_source is None or stored_source != entry.source:
            raise MemoryDataError("记忆 payload 与已保存来源不一致")
        return entry

    def find_candidate(self, conn, scope: MemoryScope, memory_id: str) -> MemoryEntry | None:
        row = conn.execute(
            "SELECT * FROM entries WHERE user_id = ? AND project_id = ? AND memory_id = ?",
            (*_scope_values(scope), memory_id),
        ).fetchone()
        return self._entry(conn, row, scope)

    def latest_entry(self, conn, scope: MemoryScope, key: str, conditions: Conditions) -> MemoryEntry | None:
        # 这是最新持久版本的 I/O 查询，不能代替历史有效性或撤回选择。
        row = conn.execute(
            """SELECT * FROM entries WHERE user_id = ? AND project_id = ?
            AND memory_key = ? AND conditions = ? ORDER BY version DESC LIMIT 1""",
            (*_scope_values(scope), key, _conditions(conditions)),
        ).fetchone()
        return self._entry(conn, row, scope)

    def insert_entry(self, conn, entry: MemoryEntry) -> None:
        payload = dump_entry(entry)
        normalized = load_entry(payload)
        source = self.get_source(conn, normalized.scope, normalized.source.source_id)
        if source is None or source != normalized.source:
            raise MemoryDataError("写入记忆前必须已保存相同来源")
        conn.execute(
            """INSERT INTO entries (user_id, project_id, memory_id, source_id,
            memory_key, conditions, version, state, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (*_scope_values(normalized.scope), normalized.memory_id, normalized.source.source_id,
             normalized.draft.key, _conditions(normalized.draft.conditions),
             normalized.version, normalized.state, payload),
        )

    def update_entry(self, conn, entry: MemoryEntry) -> None:
        """仅更新已存在条目的 state/valid_to；不判断何时应修改状态。

        原始来源、候选、版本和写入时间都保持不变；不能把此入口当成
        覆盖事实内容或隐式新增版本的通道。
        """
        payload = dump_entry(entry)
        normalized = load_entry(payload)
        existing = self.find_candidate(conn, normalized.scope, normalized.memory_id)
        if existing is None:
            raise MemoryDataError("不能更新不存在的记忆条目")
        immutable = ("memory_id", "scope", "source", "draft", "version", "written_at")
        if any(getattr(existing, field) != getattr(normalized, field) for field in immutable):
            raise MemoryDataError("元数据更新不能改写来源、候选、版本或写入时间")
        cursor = conn.execute(
            """UPDATE entries SET state = ?, payload = ?
            WHERE user_id = ? AND project_id = ? AND memory_id = ?""",
            (normalized.state, payload, *_scope_values(normalized.scope), normalized.memory_id),
        )
        if cursor.rowcount != 1:
            raise MemoryDataError("元数据更新必须恰好命中一条记忆")

    def entries_for_series(self, conn, scope: MemoryScope, key: str, conditions: Conditions) -> list[MemoryEntry]:
        """读取精确系列的全部版本；无状态或当前适用时间过滤。"""
        rows = conn.execute(
            """SELECT * FROM entries WHERE user_id = ? AND project_id = ?
            AND memory_key = ? AND conditions = ? ORDER BY version, memory_id""",
            (*_scope_values(scope), key, _conditions(conditions)),
        ).fetchall()
        return [self._entry(conn, row, scope) for row in rows]

    @staticmethod
    def _has_receipt_table(conn) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("operation_receipts",),
        ).fetchone() is not None

    def _verify_receipt_links(self, conn, receipt: MemoryReceipt) -> None:
        source = self.get_source(conn, receipt.scope, receipt.source.source_id)
        if source is None or source != receipt.source:
            raise MemoryDataError("回执来源与已保存来源不一致")
        result = self.find_candidate(conn, receipt.scope, receipt.result_memory_id)
        if result is None or (
            result.memory_id != receipt.result_memory_id
            or result.version != receipt.result_version
            or result.draft.key != receipt.key
            or result.draft.conditions != receipt.conditions
        ):
            raise MemoryDataError("回执的结果定位与已保存记忆不一致")
        if receipt.action == "replace" and result.source != receipt.source:
            raise MemoryDataError("替换回执的来源与结果来源不一致")

    def get_receipt(self, conn, scope: MemoryScope, operation_id: str) -> MemoryReceipt | None:
        _scope_values(scope)
        # 旧 MEM-01 两表库仍可只读诊断，不在读取路径执行建表迁移。
        if not self._has_receipt_table(conn):
            return None
        row = conn.execute(
            """SELECT * FROM operation_receipts
            WHERE user_id = ? AND project_id = ? AND operation_id = ?""",
            (*_scope_values(scope), operation_id),
        ).fetchone()
        if row is None:
            return None
        receipt = load_receipt(row["payload"])
        if (
            receipt.scope != scope or receipt.operation_id != row["operation_id"]
            or receipt.action != row["action"] or receipt.request_hash != row["request_hash"]
            or receipt.key != row["memory_key"]
            or _conditions(receipt.conditions) != row["conditions"]
            or receipt.expected_version != row["expected_version"]
            or receipt.result_memory_id != row["result_memory_id"]
            or receipt.result_version != row["result_version"]
            or receipt.source.source_id != row["source_id"]
        ):
            raise MemoryDataError("回执 payload 与查询范围或索引列不一致")
        self._verify_receipt_links(conn, receipt)
        return receipt

    def insert_receipt(self, conn, receipt: MemoryReceipt) -> None:
        payload = dump_receipt(receipt)
        normalized = load_receipt(payload)
        self._verify_receipt_links(conn, normalized)
        conn.execute(
            """INSERT INTO operation_receipts (user_id, project_id, operation_id,
            action, request_hash, memory_key, conditions, expected_version,
            result_memory_id, result_version, source_id, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (*_scope_values(normalized.scope), normalized.operation_id, normalized.action,
             normalized.request_hash, normalized.key, _conditions(normalized.conditions),
             normalized.expected_version, normalized.result_memory_id,
             normalized.result_version, normalized.source.source_id, payload),
        )

    def read_receipt(self, scope: MemoryScope, operation_id: str) -> MemoryReceipt | None:
        """只读回执诊断；不作业务重试决策，也不创建或迁移数据库。"""
        _scope_values(scope)
        with self._reader() as conn:
            if conn is None:
                return None
            return self.get_receipt(conn, scope, operation_id)

    def read_entry(self, scope: MemoryScope, memory_id: str) -> MemoryEntry | None:
        _scope_values(scope)
        with self._reader() as conn:
            if conn is None:
                return None
            return self.find_candidate(conn, scope, memory_id)

    def read_entries(self, scope: MemoryScope) -> list[MemoryEntry]:
        _scope_values(scope)
        with self._reader() as conn:
            if conn is None:
                return []
            rows = conn.execute(
                "SELECT * FROM entries WHERE user_id = ? AND project_id = ? ORDER BY memory_key, version, memory_id",
                _scope_values(scope),
            ).fetchall()
            return [self._entry(conn, row, scope) for row in rows]
