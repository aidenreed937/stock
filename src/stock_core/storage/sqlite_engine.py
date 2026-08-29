"""SQLite 核心持久化引擎。

负责：
1. 强制注入 WAL、busy_timeout、foreign_keys 等性能与一致性 PRAGMA；
2. 提供线程安全连接创建与原子事务上下文管理器；
3. 数据库初始化时自动触发版本迁移器 (MigrationRunner)。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from stock_core.storage.sqlite_migration import SQLiteMigrationRunner

_DEFAULT_DB_PATH = Path("data/state/quant_state.db")


class SQLiteEngine:
    """SQLite 数据库引擎。"""

    def __init__(
        self,
        db_path: Path | str | None = None,
        migrations_dir: Path | str | None = None,
        auto_migrate: bool = True,
    ) -> None:
        self.db_path = Path(db_path or _DEFAULT_DB_PATH)
        self.migrations_dir = Path(migrations_dir) if migrations_dir else None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        if auto_migrate:
            self.migrate()

    def connect(self) -> sqlite3.Connection:
        """创建并配置符合性能与一致性规范的 SQLite 连接。"""
        # check_same_thread=False 允许跨线程传递连接（配合 WAL）
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row

        # 注入 4 项强制规范 PRAGMA 参数
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA busy_timeout = 5000;")
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.close()

        return conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """原子事务上下文管理器，成功自动 commit，异常自动 rollback。"""
        conn = self.connect()
        try:
            conn.execute("BEGIN TRANSACTION;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate(self) -> int:
        """执行数据库 Schema 增量版本迁移。"""
        runner = SQLiteMigrationRunner(self.migrations_dir)
        with self.connect() as conn:
            return runner.apply_pending_migrations(conn)


_default_engine: SQLiteEngine | None = None


def get_sqlite_engine(
    db_path: Path | str | None = None,
    auto_migrate: bool = True,
) -> SQLiteEngine:
    """获取全局或指定路径的 SQLiteEngine 实例。"""
    global _default_engine
    if db_path is None:
        if _default_engine is None:
            _default_engine = SQLiteEngine(auto_migrate=auto_migrate)
        return _default_engine
    return SQLiteEngine(db_path=db_path, auto_migrate=auto_migrate)


__all__ = ["SQLiteEngine", "get_sqlite_engine"]
