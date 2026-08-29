from pathlib import Path

import pytest

from stock_core.storage.sqlite_engine import SQLiteEngine


def test_sqlite_engine_initialization_and_pragmas(tmp_path: Path) -> None:
    db_file = tmp_path / "test_state.db"
    engine = SQLiteEngine(db_path=db_file, auto_migrate=True)

    conn = engine.connect()
    cursor = conn.cursor()

    # 1. 验证 WAL 模式
    cursor.execute("PRAGMA journal_mode;")
    assert cursor.fetchone()[0].lower() == "wal"

    # 2. 验证外键开启
    cursor.execute("PRAGMA foreign_keys;")
    assert cursor.fetchone()[0] == 1

    # 3. 验证 user_version 升至 3 (当前包含 001, 002, 003 三个迁移)
    cursor.execute("PRAGMA user_version;")
    assert cursor.fetchone()[0] == 3

    # 4. 验证表存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='accounts';")
    assert cursor.fetchone() is not None

    conn.close()


def test_sqlite_engine_transaction_rollback(tmp_path: Path) -> None:
    db_file = tmp_path / "test_rollback.db"
    engine = SQLiteEngine(db_path=db_file, auto_migrate=True)

    # 正常插入
    with engine.transaction() as conn:
        conn.execute(
            "INSERT INTO accounts (account_id, account_name, strategy_key, total_capital, cash_available) VALUES (?, ?, ?, ?, ?)",
            ("acc_1", "测试账户", "macro_v4", 100000.0, 100000.0),
        )

    # 异常事务回滚
    def _failing_txn() -> None:
        with engine.transaction() as conn:
            conn.execute(
                "INSERT INTO accounts (account_id, account_name, strategy_key, total_capital, cash_available) VALUES (?, ?, ?, ?, ?)",
                ("acc_2", "待回滚账户", "macro_v4", 50000.0, 50000.0),
            )
            raise ValueError("模拟故障")

    with pytest.raises(ValueError, match="模拟故障"):
        _failing_txn()

    conn = engine.connect()
    cursor = conn.cursor()
    cursor.execute("SELECT account_id FROM accounts;")
    rows = [r[0] for r in cursor.fetchall()]
    assert "acc_1" in rows
    assert "acc_2" not in rows
    conn.close()
