"""策略回测实验版本库仓储 (ExperimentRepository)。

支持跨时间、跨参数的 SQL 查询、灵敏度分析与最优参数排行榜。
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any

from stock_core.storage.sqlite_engine import SQLiteEngine, get_sqlite_engine


class ExperimentRepository:
    """策略回测实验仓储。"""

    def __init__(self, engine: SQLiteEngine | None = None) -> None:
        self.engine = engine or get_sqlite_engine()

    def record_experiment(
        self,
        *,
        strategy_class: str,
        benchmark_symbol: str,
        start_date: date | str,
        end_date: date | str,
        trading_days: int,
        params: dict[str, Any],
        friction: dict[str, Any],
        total_return: float,
        cagr: float,
        max_drawdown: float,
        annual_volatility: float,
        sharpe_ratio: float,
        calmar_ratio: float,
        total_turnover: float = 0.0,
        annual_trades: float = 0.0,
    ) -> str:
        """记录单次回测实验运行结果。"""
        exp_id = f"EXP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        with self.engine.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO backtest_experiments (
                    experiment_id, strategy_class, benchmark_symbol, start_date, end_date,
                    trading_days, params_json, friction_json, total_return, cagr,
                    max_drawdown, annual_volatility, sharpe_ratio, calmar_ratio,
                    total_turnover, annual_trades
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    exp_id,
                    strategy_class,
                    benchmark_symbol,
                    str(start_date),
                    str(end_date),
                    trading_days,
                    json.dumps(params, ensure_ascii=False),
                    json.dumps(friction, ensure_ascii=False),
                    total_return,
                    cagr,
                    max_drawdown,
                    annual_volatility,
                    sharpe_ratio,
                    calmar_ratio,
                    total_turnover,
                    annual_trades,
                ),
            )
            return exp_id

    def list_experiments(
        self,
        strategy_class: str | None = None,
        limit: int = 20,
        order_by: str = "sharpe_ratio",
    ) -> list[dict[str, Any]]:
        """获取回测实验排行榜。"""
        allowed_orders = {"sharpe_ratio", "cagr", "calmar_ratio", "max_drawdown", "run_timestamp"}
        order_col = order_by if order_by in allowed_orders else "sharpe_ratio"
        sort_dir = "ASC" if order_col == "max_drawdown" else "DESC"

        query = "SELECT * FROM backtest_experiments"
        params: list[Any] = []
        if strategy_class:
            query += " WHERE strategy_class = ?"
            params.append(strategy_class)

        query += f" ORDER BY {order_col} {sort_dir} LIMIT ?;"
        params.append(limit)

        with self.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]


__all__ = ["ExperimentRepository"]
