"""SQLite 连接封装：建库、建表、轻量查询；库文件默认 db/secureeye.db。"""
import sqlite3
from pathlib import Path


class Database:
    """持有单一 sqlite3 连接（应用启动时初始化，进程内复用）。"""

    DEFAULT_NAME = "secureeye.db"
    # 历史库需补的列：列名 -> 列定义（与 _SCHEMA 保持同步）
    _ADDED_COLUMNS = {
        "system_prompt": "TEXT NOT NULL DEFAULT ''",
        "font_size": "INTEGER NOT NULL DEFAULT 14",
    }
    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS accounts (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        email         TEXT    NOT NULL UNIQUE,
        pwd_salt      BLOB    NOT NULL,
        pwd_hash      BLOB    NOT NULL,
        key_salt      BLOB    NOT NULL,
        data_key_enc  BLOB    NOT NULL,
        created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS model_config (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id    INTEGER NOT NULL UNIQUE REFERENCES accounts(id) ON DELETE CASCADE,
        base_url      TEXT    NOT NULL,
        model         TEXT    NOT NULL,
        api_key_enc   BLOB    NOT NULL,
        is_label      INTEGER NOT NULL DEFAULT 1,
        system_prompt TEXT    NOT NULL DEFAULT '',
        font_size     INTEGER NOT NULL DEFAULT 14,
        updated_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
    );
    """

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            path = Path(__file__).resolve().parent / Database.DEFAULT_NAME
        # check_same_thread=False：上层通过 asyncio.to_thread 串行访问（await 保证同一时刻仅一个线程）
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(Database._SCHEMA)
        self._migrate()
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")  # 降低写盘延迟

    def _migrate(self) -> None:
        """历史库补列：仅缺少时 ADD COLUMN。"""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(model_config)")}
        for name, definition in Database._ADDED_COLUMNS.items():
            if name not in cols:
                self._conn.execute(f"ALTER TABLE model_config ADD COLUMN {name} {definition}")
        self._conn.commit()

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self._conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._conn.execute(sql, params)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
