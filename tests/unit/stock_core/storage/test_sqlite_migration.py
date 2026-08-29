import sqlite3
from pathlib import Path

from stock_core.storage.sqlite_migration import SQLiteMigrationRunner


def test_sqlite_migration_discovery(tmp_path: Path) -> None:
    # 构造假迁移目录
    m_dir = tmp_path / "migrations"
    m_dir.mkdir()
    (m_dir / "001_first.sql").write_text("CREATE TABLE t1 (id INT);", encoding="utf-8")
    (m_dir / "002_second.sql").write_text("CREATE TABLE t2 (id INT);", encoding="utf-8")
    (m_dir / "invalid_file.txt").write_text("dummy", encoding="utf-8")

    runner = SQLiteMigrationRunner(m_dir)
    discovered = runner.discover_migrations()
    assert len(discovered) == 2
    assert discovered[0][0] == 1
    assert discovered[1][0] == 2


def test_sqlite_migration_step_by_step(tmp_path: Path) -> None:
    m_dir = tmp_path / "migrations"
    m_dir.mkdir()
    (m_dir / "001_first.sql").write_text("CREATE TABLE t1 (id INT);", encoding="utf-8")
    (m_dir / "002_second.sql").write_text("CREATE TABLE t2 (id INT);", encoding="utf-8")

    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))

    runner = SQLiteMigrationRunner(m_dir)
    applied = runner.apply_pending_migrations(conn)
    assert applied == 2
    assert runner.get_current_version(conn) == 2

    # 重复运行不应再应用任何迁移
    applied_again = runner.apply_pending_migrations(conn)
    assert applied_again == 0

    # 动态追加 003 迁移
    (m_dir / "003_third.sql").write_text("CREATE TABLE t3 (id INT);", encoding="utf-8")
    applied_3 = runner.apply_pending_migrations(conn)
    assert applied_3 == 1
    assert runner.get_current_version(conn) == 3

    conn.close()
