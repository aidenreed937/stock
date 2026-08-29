from datetime import date
from pathlib import Path

import pytest

from stock_core.storage.sqlite_engine import SQLiteEngine
from stock_strategy.state.portfolio_repo import PortfolioRepository


def test_portfolio_lifecycle_and_orders(tmp_path: Path) -> None:
    db_file = tmp_path / "test_portfolio.db"
    engine = SQLiteEngine(db_path=db_file, auto_migrate=True)
    repo = PortfolioRepository(engine)

    # 1. 创建账户
    acc = repo.get_or_create_account(
        account_id="live_main",
        account_name="实盘主账户",
        strategy_key="macro_rotation_v4_etf",
        initial_capital=100_000.0,
    )
    assert acc["account_id"] == "live_main"
    assert acc["cash_available"] == 100_000.0

    # 2. 买入 10,000 份 510880 @ 3.40 (金额 34,000，佣金 5.0)
    ord1 = repo.execute_order(
        account_id="live_main",
        symbol="510880.SH",
        symbol_name="红利ETF",
        trade_date=date(2026, 8, 29),
        direction="BUY",
        target_weight=0.5,
        target_shares=10000,
        filled_shares=10000,
        filled_price=3.40,
        commission=5.0,
        reason="测试建仓",
    )
    assert ord1.startswith("ORD-")

    # 验证持仓与现金扣减
    acc_after = repo.get_account("live_main")
    assert acc_after is not None
    # 现金扣减: 100000 - 34000 - 5 = 65995
    assert acc_after["cash_available"] == pytest.approx(65995.0)

    positions = repo.get_positions("live_main")
    assert len(positions) == 1
    pos = positions[0]
    assert pos["symbol"] == "510880.SH"
    assert pos["shares"] == 10000
    assert pos["cost_price"] == pytest.approx((34000 + 5) / 10000)

    # 3. 卖出 4,000 份 @ 3.50 (回款 14,000，佣金 2.0)
    ord2 = repo.execute_order(
        account_id="live_main",
        symbol="510880.SH",
        symbol_name="红利ETF",
        trade_date=date(2026, 8, 30),
        direction="SELL",
        target_weight=0.3,
        target_shares=4000,
        filled_shares=4000,
        filled_price=3.50,
        commission=2.0,
        reason="测试减仓",
    )
    assert ord2.startswith("ORD-")

    acc_sold = repo.get_account("live_main")
    assert acc_sold is not None
    # 现金增加: 65995 + 14000 - 2 = 79993
    assert acc_sold["cash_available"] == pytest.approx(79993.0)

    positions_after = repo.get_positions("live_main")
    assert len(positions_after) == 1
    assert positions_after[0]["shares"] == 6000


def test_portfolio_deposit(tmp_path: Path) -> None:
    db_file = tmp_path / "test_deposit.db"
    engine = SQLiteEngine(db_path=db_file, auto_migrate=True)
    repo = PortfolioRepository(engine)

    repo.get_or_create_account(
        account_id="live_main",
        account_name="主账户",
        strategy_key="macro_rotation_v4_etf",
        initial_capital=50_000.0,
    )

    acc = repo.deposit_cash("live_main", 20_000.0)
    assert acc["cash_available"] == 70_000.0
    assert acc["total_capital"] == 70_000.0
