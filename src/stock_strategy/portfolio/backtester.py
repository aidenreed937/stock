"""因子组合分数回测核心（纯函数，无 IO）。

对组合分数面板（``trade_date x symbol x composite_score``）与价格面板执行
简化调仓回测：每个调仓周期按当日分数选取 top-N 等权多头组合，调仓日收盘
成交、次日生效，现金兜底；输出日度净值曲线与收益/风险统计（收益法、
未建模交易成本 / T+1 / 涨跌停，仅供研究参考）。

约定与简化：
- 分数越高代表越强的多头信号（方向已由组合管线对齐）；
- 调仓日 ``t`` 收盘以当日分数建仓，持仓收益自 ``t+1`` 起按新权重计算；
- 持仓标的价格缺失（停牌）时该标的当日收益按 0 计；
- 每日组合收益 = Σ 权重 × 日收益，权重之和小于 1 的余量为现金（收益 0）；
- 基准 = 全标的等权组合（同口径日收益，恒等权重）。
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import polars as pl

from stock_core.exceptions import DataValidationError

_TRADING_DAYS_PER_YEAR = 252.0


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """一次因子组合回测的结果。"""

    nav: pl.DataFrame
    benchmark_nav: pl.DataFrame
    stats: dict[str, float | int | None]
    benchmark_stats: dict[str, float | int | None]


def run_factor_backtest(
    scores: pl.DataFrame,
    prices: pl.DataFrame,
    *,
    rebalance_days: int = 5,
    top_n: int = 10,
) -> BacktestResult:
    """对组合分数面板与价格面板执行 top-N 等权调仓回测。

    Args:
        scores: 组合分数面板（列：trade_date / symbol / composite_score）。
        prices: 价格面板（列：trade_date / symbol / close，未复权）。
        rebalance_days: 调仓周期（交易日）。
        top_n: 每期持仓数量上限。

    Returns:
        BacktestResult: 净值序列与统计。

    Raises:
        DataValidationError: 输入为空、窗口不足或分数/价格重叠不足。
        ValueError: 参数不合法。
    """
    if rebalance_days <= 0:
        raise ValueError(f"rebalance_days 必须为正，当前: {rebalance_days}")
    if top_n <= 0:
        raise ValueError(f"top_n 必须为正，当前: {top_n}")

    score_wide = _to_wide(scores, "composite_score", required=True)
    price_wide = _to_wide(prices, "close", required=True)
    dates = score_wide["trade_date"].to_list()
    if len(dates) < 2:
        raise DataValidationError("回测窗口交易日不足 2 天，无法回测")

    symbols = score_wide.columns[1:]
    missing_prices = [sym for sym in symbols if sym not in price_wide.columns]
    if missing_prices and len(missing_prices) == len(symbols):
        raise DataValidationError("分数面板与价格面板无重叠标的，无法回测")

    nav, benchmark_nav = _run_simulation(
        score_wide, price_wide, dates, rebalance_days=rebalance_days, top_n=top_n
    )
    stats = _compute_stats(nav, rebalance_days)
    benchmark_stats = _compute_stats(benchmark_nav, rebalance_days)
    return BacktestResult(
        nav=nav, benchmark_nav=benchmark_nav, stats=stats, benchmark_stats=benchmark_stats
    )


def _to_wide(frame: pl.DataFrame, value_column: str, *, required: bool) -> pl.DataFrame:
    """把长表面板按 (trade_date, symbol) 旋转为 trade_date x symbol 宽表。"""
    if frame.is_empty() or not {"trade_date", "symbol", value_column}.issubset(frame.columns):
        if required:
            raise DataValidationError(
                f"回测输入缺少列或为空（需要 trade_date/symbol/{value_column}）"
            )
        return pl.DataFrame()
    df = (
        frame.select("trade_date", "symbol", value_column)
        .unique(subset=["trade_date", "symbol"], keep="last")
        .with_columns(pl.col("trade_date").cast(pl.Date))
        .sort(["trade_date", "symbol"])
    )
    wide = df.pivot(
        on="symbol",
        index="trade_date",
        values=value_column,
        aggregate_function="first",
    ).sort("trade_date")
    return wide


def _run_simulation(
    score_wide: pl.DataFrame,
    price_wide: pl.DataFrame,
    dates: list[object],
    *,
    rebalance_days: int,
    top_n: int,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """逐日模拟调仓并输出组合与基准净值序列。"""
    rebalance_idx = set(range(0, len(dates), rebalance_days))
    symbols = score_wide.columns[1:]
    benchmark_symbols = [sym for sym in symbols if sym in price_wide.columns]
    price_rows = {day: i for i, day in enumerate(price_wide["trade_date"].to_list())}

    weights: dict[str, float] = {}
    pending_weights: dict[str, float] = {}
    nav_values: list[float] = []
    bench_values: list[float] = []
    nav = 1.0
    bench = 1.0

    for i, day in enumerate(dates):
        if i in rebalance_idx:
            pending_weights = _select_weights(score_wide, day, symbols, top_n)
        daily_ret = _portfolio_return(price_wide, price_rows, day, weights)
        bench_ret = _benchmark_return(price_wide, price_rows, day, benchmark_symbols)
        nav *= 1.0 + daily_ret
        bench *= 1.0 + bench_ret
        nav_values.append(nav)
        bench_values.append(bench)
        if i in rebalance_idx:
            weights = pending_weights

    return (
        pl.DataFrame({"trade_date": dates, "nav": nav_values}),
        pl.DataFrame({"trade_date": dates, "nav": bench_values}),
    )


def _select_weights(
    score_wide: pl.DataFrame,
    day: object,
    symbols: list[str],
    top_n: int,
) -> dict[str, float]:
    """在调仓日按组合分数选取 top-N 标的并返回等权权重（现金兜底）。"""
    row = score_wide.filter(pl.col("trade_date") == day)
    if row.is_empty():
        return {}
    picks: list[tuple[str, float]] = []
    for sym in symbols:
        value = row[0, sym]
        if value is not None:
            picks.append((sym, float(value)))
    picks.sort(key=lambda item: item[1], reverse=True)
    selected = [sym for sym, _ in picks[:top_n]]
    if not selected:
        return {}
    weight = 1.0 / top_n
    return dict.fromkeys(selected, weight)


def _portfolio_return(
    price_wide: pl.DataFrame,
    price_rows: dict[object, int],
    day: object,
    weights: dict[str, float],
) -> float:
    """组合当日收益：Σ 权重 × 标的日收益（缺失价格按 0）。"""
    if day not in price_rows or not weights:
        return 0.0
    idx = price_rows[day]
    if idx == 0:
        return 0.0
    prev_idx = idx - 1
    total = 0.0
    for sym, weight in weights.items():
        if sym not in price_wide.columns:
            continue
        prev_close = price_wide[prev_idx, sym]
        curr_close = price_wide[idx, sym]
        if prev_close is None or curr_close is None:
            continue
        total += weight * (float(curr_close) / float(prev_close) - 1.0)
    return total


def _benchmark_return(
    price_wide: pl.DataFrame,
    price_rows: dict[object, int],
    day: object,
    symbols: list[str],
) -> float:
    """基准（观察池等权）当日收益。"""
    if day not in price_rows or not symbols:
        return 0.0
    idx = price_rows[day]
    if idx == 0:
        return 0.0
    prev_idx = idx - 1
    weight = 1.0 / len(symbols)
    total = 0.0
    for sym in symbols:
        prev_close = price_wide[prev_idx, sym]
        curr_close = price_wide[idx, sym]
        if prev_close is None or curr_close is None:
            continue
        total += weight * (float(curr_close) / float(prev_close) - 1.0)
    return total


def _compute_stats(
    nav_frame: pl.DataFrame,
    rebalance_days: int,
) -> dict[str, float | int | None]:
    """从净值序列计算收益/风险统计。"""
    nav_values = [float(v) for v in nav_frame["nav"].to_list()]
    n_days = max(len(nav_values) - 1, 0)
    if not nav_values:
        return {}

    daily = (
        [nav_values[i] / nav_values[i - 1] - 1.0 for i in range(1, len(nav_values))]
        if len(nav_values) > 1
        else []
    )
    total_return = nav_values[-1] - 1.0
    annual_return = (
        nav_values[-1] ** (_TRADING_DAYS_PER_YEAR / n_days) - 1.0 if n_days > 0 else None
    )

    vol: float | None = None
    if len(daily) > 1:
        mean = sum(daily) / len(daily)
        variance = sum((d - mean) ** 2 for d in daily) / (len(daily) - 1)
        vol = sqrt(variance) * sqrt(_TRADING_DAYS_PER_YEAR)

    sharpe = annual_return / vol if annual_return is not None and vol and vol > 0 else None

    max_drawdown: float = 0.0
    peak = nav_values[0]
    for value in nav_values:
        peak = max(peak, value)
        drawdown = 1.0 - value / peak
        max_drawdown = max(max_drawdown, drawdown)
    calmar = annual_return / max_drawdown if annual_return is not None and max_drawdown else None

    n_periods = max(len(nav_values) // rebalance_days, 0)
    wins = 0
    measurable = 0
    for j in range(rebalance_days, len(nav_values), rebalance_days):
        start_idx = j - rebalance_days
        period_ret = nav_values[j] / nav_values[start_idx] - 1.0
        measurable += 1
        if period_ret > 0:
            wins += 1
    win_rate = wins / measurable if measurable else None

    return {
        "n_trading_days": n_days,
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_volatility": vol,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "period_win_rate": win_rate,
        "n_periods": n_periods,
    }


__all__ = ["BacktestResult", "run_factor_backtest"]
