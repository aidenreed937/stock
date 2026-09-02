"""宏观风控策略绩效报告：资金曲线、指标对比与 Markdown 渲染。

职责：把 V3/V4/V5/V6 策略净值与基准（中证全指 / 沪深300 等）buy&hold 净值对齐到同一
交易日轴，计算绩效指标（累计净值、CAGR、最大回撤、年化波动、Sharpe、Calmar），
输出资金曲线 PNG、净值 CSV 与对比 Markdown 文档。
"""

from __future__ import annotations

from datetime import date
from math import sqrt
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from stock_data.catalog import DataCatalog
from stock_strategy.macro.assembly import assemble_macro_panel, load_price_panel
from stock_strategy.macro.report_render import (
    render_comparison_chart,
    render_comparison_markdown,
)
from stock_strategy.macro.runner import MacroRiskRunner
from stock_strategy.pool import create_strategy

_TRADING_DAYS_PER_YEAR = 252.0
_DEFAULT_CONFIG_PATH = Path("config/strategy/macro_risk.yaml")
_DEFAULT_RISK_ROOT = Path("data/analytics/macro_risk")
_DEFAULT_OUTPUT_DIR = Path("data/analytics/macro_strategy")

_DEFAULT_BENCHMARKS = (
    ("000985.CSI", "中证全指"),
    ("000300.SH", "沪深300"),
)


def load_benchmarks(
    config_path: Path | str = _DEFAULT_CONFIG_PATH,
) -> list[tuple[str, str]]:
    """读取配置文件中配置的横向对比基准列表。"""
    try:
        payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "benchmarks" in payload:
            items = payload["benchmarks"]
            if isinstance(items, list):
                res = []
                for b in items:
                    if isinstance(b, dict) and "symbol" in b:
                        res.append((str(b["symbol"]), str(b.get("name", b["symbol"]))))
                if res:
                    return res
    except Exception:
        pass
    return list(_DEFAULT_BENCHMARKS)


def load_all_strategy_specs(
    config_path: Path | str = _DEFAULT_CONFIG_PATH,
) -> dict[str, dict[str, Any]]:
    """读取配置文件中所有已注册宏观策略的配置字典。"""
    payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    strategies = payload.get("strategies", {})
    return {k: v for k, v in strategies.items() if isinstance(v, dict)}


def load_strategy_spec(name: str, config_path: Path | str = _DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """读取单个宏观策略的运行配置（benchmark / symbols / initial_weights / ma_window）。"""
    all_specs = load_all_strategy_specs(config_path)
    return all_specs.get(name, {})


def nav_from_close(
    close: pl.DataFrame,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pl.DataFrame:
    """把基准指数 close 序列转为 buy&hold 净值（首日归一为 1）。"""
    frame = (
        close.select(["trade_date", "close"])
        .filter(pl.col("close").is_not_null() & (pl.col("close") > 0))
        .sort("trade_date")
    )
    if start_date is not None:
        frame = frame.filter(pl.col("trade_date") >= start_date)
    if end_date is not None:
        frame = frame.filter(pl.col("trade_date") <= end_date)
    if frame.is_empty():
        return pl.DataFrame(
            {"trade_date": pl.Series([], dtype=pl.Date), "nav": pl.Series([], dtype=pl.Float64)}
        )
    first_close = float(frame["close"][0])
    return frame.select(
        [
            pl.col("trade_date"),
            (pl.col("close") / first_close).alias("nav"),
        ]
    )


def compute_metrics(nav_series: pl.DataFrame) -> dict[str, float]:
    """计算单个策略/基准全周期的核心绩效指标。"""
    if nav_series.is_empty() or len(nav_series) < 2:
        return {
            "total_return": 0.0,
            "cagr": 0.0,
            "max_drawdown": 0.0,
            "annualized_volatility": 0.0,
            "sharpe_ratio": 0.0,
            "calmar_ratio": 0.0,
            "final_nav": 1.0,
        }
    navs = nav_series["nav"].to_list()
    final_nav = float(navs[-1])
    first_nav = float(navs[0]) if navs[0] > 0 else 1.0
    total_return = (final_nav / first_nav) - 1.0

    n_days = len(navs)
    years = n_days / _TRADING_DAYS_PER_YEAR
    cagr = (final_nav / first_nav) ** (1.0 / years) - 1.0 if years > 0 and final_nav > 0 else 0.0

    peak = navs[0]
    max_dd = 0.0
    for v in navs:
        peak = max(peak, v)
        dd = (v - peak) / peak if peak > 0 else 0.0
        max_dd = min(max_dd, dd)

    daily_rets = [(navs[i] / navs[i - 1] - 1.0) for i in range(1, n_days)]
    if daily_rets:
        mean_ret = sum(daily_rets) / len(daily_rets)
        var = sum((r - mean_ret) ** 2 for r in daily_rets) / len(daily_rets)
        std = sqrt(var)
        ann_vol = std * sqrt(_TRADING_DAYS_PER_YEAR)
    else:
        ann_vol = 0.0

    risk_free_rate = 0.015
    excess_cagr = cagr - risk_free_rate
    sharpe = (excess_cagr / ann_vol) if ann_vol > 1e-8 else 0.0
    calmar = (cagr / abs(max_dd)) if abs(max_dd) > 1e-8 else 0.0

    return {
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "annualized_volatility": ann_vol,
        "sharpe_ratio": sharpe,
        "calmar_ratio": calmar,
        "final_nav": final_nav,
    }


def compute_stats(nav_series: pl.DataFrame) -> dict[str, Any]:
    """向后兼容的绩效指标计算函数。"""
    res = compute_metrics(nav_series)
    return {
        "final_nav": res["final_nav"],
        "total_return": res["total_return"],
        "annual_return": res["cagr"],
        "max_drawdown": res["max_drawdown"],
        "annual_volatility": res["annualized_volatility"],
        "sharpe": res["sharpe_ratio"],
        "calmar": res["calmar_ratio"] if abs(res["max_drawdown"]) > 1e-8 else None,
        "cagr": res["cagr"],
        "sharpe_ratio": res["sharpe_ratio"],
        "calmar_ratio": res["calmar_ratio"],
        "annualized_volatility": res["annualized_volatility"],
    }


def _runner_for(spec: dict[str, Any]) -> tuple[MacroRiskRunner, str]:
    """由 spec 实例化 MacroRiskRunner，透明透传 thresholds 参数。"""
    benchmark = str(spec.get("benchmark_symbol", "000985.CSI"))
    symbols = tuple(spec.get("symbols", [benchmark]))
    raw_weights = spec.get("initial_weights", {s: 1.0 / len(symbols) for s in symbols})
    initial_weights = {str(k): float(v) for k, v in raw_weights.items()}

    friction = dict(spec.get("friction", {}))
    commission_rate = float(friction.get("commission_rate", spec.get("commission_rate", 0.0)))
    slippage_rate = float(friction.get("slippage_rate", spec.get("slippage_rate", 0.0)))
    rebalance_deadband = float(
        friction.get("rebalance_deadband", spec.get("rebalance_deadband", 0.0))
    )

    strategy_kwargs: dict[str, Any] = {
        "symbols": symbols,
        "initial_weights": initial_weights,
        "benchmark_symbol": benchmark,
    }
    for k, v in spec.items():
        if k not in {
            "strategy_class",
            "symbols",
            "initial_weights",
            "benchmark_symbol",
            "friction",
            "panel_extra_cols",
            "thresholds",
        }:
            strategy_kwargs[k] = v

    if "thresholds" in spec and isinstance(spec["thresholds"], dict):
        for tk, tv in spec["thresholds"].items():
            strategy_kwargs[tk] = tv

    strategy = create_strategy(
        str(spec["strategy_class"]),
        **strategy_kwargs,
    )
    runner = MacroRiskRunner(
        strategy,
        symbols=symbols,
        initial_weights=initial_weights,
        strategy_name=spec["strategy_class"],
        data_source="tushare",
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
        rebalance_deadband=rebalance_deadband,
    )
    return runner, benchmark


def build_multi_strategy_comparison_report(
    *,
    output_dir: Path | str = _DEFAULT_OUTPUT_DIR,
    risk_root: Path | str = _DEFAULT_RISK_ROOT,
    config_path: Path | str = _DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    """生成配置文件中所有策略与基准的资金曲线、指标对比与 Markdown 文档。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    catalog = DataCatalog(data_source="tushare")

    strategy_specs = load_all_strategy_specs(config_path)
    series: dict[str, pl.DataFrame] = {}
    start: date | None = None
    end: date | None = None

    for name, spec in strategy_specs.items():
        runner, benchmark = _runner_for(spec)
        panel = assemble_macro_panel(
            catalog=catalog,
            benchmark_symbol=benchmark,
            risk_root=risk_root,
            extra_factor_cols=spec.get("panel_extra_cols", ()),
        )
        price_panel = load_price_panel(catalog=catalog, symbols=tuple(spec["symbols"]))
        nav = runner.backtest(panel, price_panel)
        series[name] = nav
        if start is None and not panel.is_empty():
            min_date = panel["trade_date"].min()
            max_date = panel["trade_date"].max()
            if isinstance(min_date, date):
                start = min_date
            if isinstance(max_date, date):
                end = max_date

    benchmarks_list = load_benchmarks(config_path)
    for symbol, label in benchmarks_list:
        close = catalog.load_bars(
            symbol=symbol,
            dataset="index_daily_bar",
            columns=["trade_date", "close"],
        )
        if not close.is_empty():
            b_nav = nav_from_close(close, start_date=start, end_date=end)
            series[label] = b_nav

    stats: dict[str, dict[str, float]] = {name: compute_metrics(df) for name, df in series.items()}

    png_path = out / "multi_strategy_comparison.png"
    render_comparison_chart(series, png_path, benchmarks_list=benchmarks_list)
    md_path = out / "multi_strategy_comparison.md"
    render_comparison_markdown(stats, start, end, out_path=md_path, benchmarks_list=benchmarks_list)

    wide_df = _align_wide(series)
    csv_path = out / "multi_strategy_nav.csv"
    wide_df.write_csv(csv_path)

    return {
        "series": series,
        "stats": stats,
        "png_path": png_path,
        "md_path": md_path,
        "csv_path": csv_path,
        "markdown": md_path,
        "png": png_path,
        "csv": csv_path,
    }


build_v3_v4_comparison_report = build_multi_strategy_comparison_report


def _align_wide(series: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """把多个策略/基准净值序列对齐为单个 trade_date 宽表。"""
    if not series:
        return pl.DataFrame()
    wide: pl.DataFrame | None = None
    for name, df in series.items():
        sub = df.select([pl.col("trade_date"), pl.col("nav").alias(name)])
        wide = sub if wide is None else wide.join(sub, on="trade_date", how="full", coalesce=True)
    if wide is None:
        return pl.DataFrame()
    return wide.sort("trade_date")


__all__ = [
    "build_multi_strategy_comparison_report",
    "build_v3_v4_comparison_report",
    "compute_metrics",
    "compute_stats",
    "load_all_strategy_specs",
    "load_benchmarks",
    "load_strategy_spec",
    "nav_from_close",
    "render_comparison_chart",
    "render_comparison_markdown",
]
