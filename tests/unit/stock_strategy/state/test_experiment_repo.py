from datetime import date
from pathlib import Path

from stock_core.storage.sqlite_engine import SQLiteEngine
from stock_strategy.state.experiment_repo import ExperimentRepository


def test_experiment_repository_record_and_rank(tmp_path: Path) -> None:
    db_file = tmp_path / "test_exp.db"
    engine = SQLiteEngine(db_path=db_file, auto_migrate=True)
    repo = ExperimentRepository(engine)

    # 插入两个实验
    exp1 = repo.record_experiment(
        strategy_class="MacroRotationV4Strategy",
        benchmark_symbol="000985.CSI",
        start_date=date(2015, 1, 5),
        end_date=date(2026, 8, 28),
        trading_days=2833,
        params={"ma_window": 20, "panic_threshold": 75.0},
        friction={"commission": 0.0001, "slippage": 0.0005},
        total_return=0.998,
        cagr=0.0635,
        max_drawdown=-0.3912,
        annual_volatility=0.1886,
        sharpe_ratio=0.34,
        calmar_ratio=0.16,
    )
    assert exp1.startswith("EXP-")

    exp2 = repo.record_experiment(
        strategy_class="MacroRotationV6Strategy",
        benchmark_symbol="000985.CSI",
        start_date=date(2015, 1, 5),
        end_date=date(2026, 8, 28),
        trading_days=2833,
        params={"ma_window": 20, "panic_threshold": 75.0, "valuation_threshold": 20.0},
        friction={"commission": 0.0001, "slippage": 0.0005},
        total_return=0.5798,
        cagr=0.0415,
        max_drawdown=-0.3885,
        annual_volatility=0.2001,
        sharpe_ratio=0.21,
        calmar_ratio=0.11,
    )
    assert exp2.startswith("EXP-")

    # 查询夏普比率排行榜
    ranked = repo.list_experiments(order_by="sharpe_ratio")
    assert len(ranked) == 2
    assert ranked[0]["experiment_id"] == exp1  # V4 夏普 0.34 > V6 0.21
    assert ranked[1]["experiment_id"] == exp2
