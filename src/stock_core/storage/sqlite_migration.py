"""SQLite 数据库 Schema 独立版本迁移引擎。

基于 PRAGMA user_version 实现轻量、零外部依赖的原子增量迁移。
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from stock_core.utils.logger import logger

_MIGRATION_FILE_PATTERN = re.compile(r"^(?P<version>\d+)_(?P<desc>.+)\.sql$")
_DEFAULT_MIGRATIONS_DIR = Path("schema/sqlite/migrations")


class SQLiteMigrationRunner:
    """SQLite 增量迁移执行器。"""

    def __init__(self, migrations_dir: Path | str | None = None) -> None:
        self.migrations_dir = Path(migrations_dir or _DEFAULT_MIGRATIONS_DIR)

    def get_current_version(self, conn: sqlite3.Connection) -> int:
        """获取当前数据库 user_version 版本号。"""
        cursor = conn.cursor()
        cursor.execute("PRAGMA user_version;")
        row = cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def discover_migrations(self) -> list[tuple[int, str, Path]]:
        """扫描迁移目录，返回严格按版本号递增排序的 (version, desc, file_path) 列表。"""
        if not self.migrations_dir.is_dir():
            logger.warning("迁移目录不存在: %s", self.migrations_dir)
            return []

        migrations: list[tuple[int, str, Path]] = []
        for file in self.migrations_dir.glob("*.sql"):
            match = _MIGRATION_FILE_PATTERN.match(file.name)
            if match:
                version = int(match.group("version"))
                desc = match.group("desc")
                migrations.append((version, desc, file))

        # 按版本号严格升序排列
        migrations.sort(key=lambda item: item[0])
        return migrations

    def apply_pending_migrations(self, conn: sqlite3.Connection) -> int:
        """执行所有待升迁的脚本，返回已应用的迁移数量。"""
        current_version = self.get_current_version(conn)
        all_migrations = self.discover_migrations()

        pending = [m for m in all_migrations if m[0] > current_version]
        if not pending:
            return 0

        applied_count = 0
        for version, desc, sql_path in pending:
            sql_content = sql_path.read_text(encoding="utf-8")
            logger.info(
                "正在执行 SQLite 迁移 [%03d_%s] (当前版本: %d -> 目标版本: %d)...",
                version,
                desc,
                current_version,
                version,
            )

            # 在单一事务中执行脚本并更新 user_version
            try:
                # 开启显式事务
                conn.execute("BEGIN TRANSACTION;")
                conn.executescript(sql_content)
                conn.execute(f"PRAGMA user_version = {version};")
                conn.commit()
                current_version = version
                applied_count += 1
            except Exception as exc:
                conn.rollback()
                logger.error(
                    "SQLite 迁移 [%03d_%s] 失败，事务已自动回滚: %s",
                    version,
                    desc,
                    exc,
                )
                raise RuntimeError(f"SQLite 数据库迁移失败: {sql_path.name}, 原因: {exc}") from exc

        logger.info("SQLite 数据库已成功同步至最新版本 (Version: %d)", current_version)
        return applied_count


__all__ = ["SQLiteMigrationRunner"]
