"""申万行业轮动策略绩效报告：资金曲线、指标横向对账与 Markdown 研报。

职责：
把 4 类行业轮动策略净值与对比基准 (中证全指 / 沪深300) 对齐到同一交易日轴，
计算绩效指标（累计净值、CAGR、最大回撤、年化波动、Sharpe、Calmar），
输出资金曲线 PNG、净值 CSV 与横向对账 Markdown 研报。
"""

from __future__ import annotations

from datetime import date
from math import sqrt
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from stock_data.catalog import DataCatalog
from stock_strategy.industry.assembly import (
    assemble_industry_panel,
    load_industry_price_panel,
)
from stock_strategy.industry.report_render import (
    render_industry_comparison_chart,
    render_industry_comparison_markdown,
)
from stock_strategy.industry.runner import IndustryStrategyRunner
from stock_strategy.pool import create_strategy

_TRADING_DAYS_PER_YEAR = 252.0
_DEFAULT_CONFIG_PATH = Path("config/strategy/industry_rotation.yaml")
_DEFAULT_OUTPUT_DIR = Path("data/analytics/industry_strategy")

_DEFAULT_BENCHMARKS = (
    ("000985.CSI", "中证全指"),
    ("000300.SH", "沪深300"),
)


def load_industry_benchmarks(
    config_path: Path | str = _DEFAULT_CONFIG_PATH,
) -> list[tuple[str, str]]:
    """读取配置文件中配置的行业策略横向对比基准列表。"""
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


def load_all_industry_strategy_specs(
    config_path: Path | str = _DEFAULT_CONFIG_PATH,
) -> dict[str, dict[str, Any]]:
    """读取配置文件中所有已注册行业策略的配置字典。"""
    payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    strategies = payload.get("strategies", {})
    return {k: v for k, v in strategies.items() if isinstance(v, dict)}


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


def compute_metrics(
    nav_df: pl.DataFrame,
    risk_free_rate: float = 0.02,
) -> dict[str, float]:
    """计算标准绩效指标（累计净值、区间总收益、CAGR、最大回撤、年化波动、Sharpe、Calmar）。"""
    if nav_df.is_empty() or len(nav_df) < 2:
        return {
            "final_nav": 1.0,
            "total_return": 0.0,
            "cagr": 0.0,
            "max_drawdown": 0.0,
            "annual_volatility": 0.0,
            "sharpe_ratio": 0.0,
            "calmar_ratio": 0.0,
        }

    navs = [float(v) for v in nav_df["nav"].to_list()]
    n_days = len(navs)
    final_nav = navs[-1]
    total_return = (final_nav - 1.0) * 100.0

    years = n_days / _TRADING_DAYS_PER_YEAR
    cagr = ((final_nav ** (1.0 / years)) - 1.0) * 100.0 if years > 0 and final_nav > 0 else 0.0

    peak = navs[0]
    max_dd = 0.0
    for val in navs:
        peak = max(peak, val)
        dd = (peak - val) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    max_dd_pct = max_dd * 100.0

    daily_returns = [navs[i] / navs[i - 1] - 1.0 for i in range(1, n_days)]
    mean_ret = sum(daily_returns) / len(daily_returns) if daily_returns else 0.0
    var = (
        sum((r - mean_ret) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        if len(daily_returns) > 1
        else 0.0
    )
    daily_vol = sqrt(var) if var > 0 else 0.0
    annual_vol = daily_vol * sqrt(_TRADING_DAYS_PER_YEAR) * 100.0

    ann_ret_ratio = (cagr / 100.0) if years > 0 else (total_return / 100.0)
    ann_vol_ratio = annual_vol / 100.0
    sharpe = (ann_ret_ratio - risk_free_rate) / ann_vol_ratio if ann_vol_ratio > 0 else 0.0
    calmar = (cagr / max_dd_pct) if max_dd_pct > 0 else 0.0

    return {
        "final_nav": round(final_nav, 4),
        "total_return": round(total_return, 2),
        "cagr": round(cagr, 2),
        "max_drawdown": round(max_dd_pct, 2),
        "annual_volatility": round(annual_vol, 2),
        "sharpe_ratio": round(sharpe, 2),
        "calmar_ratio": round(calmar, 2),
    }


def build_multi_industry_comparison_report(
    output_dir: Path | str = _DEFAULT_OUTPUT_DIR,
    factor_root: Path | str = "data/analytics/industry_structure",
    macro_risk_root: Path | str = "data/analytics/macro_risk",
    config_path: Path | str = _DEFAULT_CONFIG_PATH,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """生成申万行业多策略与基准全周期资金曲线与对账报告。"""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    catalog = DataCatalog(data_source="tushare")

    benchmarks = load_industry_benchmarks(config_path)
    specs = load_all_industry_strategy_specs(config_path)

    # 1. 装配数据面板
    panel = assemble_industry_panel(
        catalog=catalog,
        factor_root=factor_root,
        macro_risk_root=macro_risk_root,
        start_date=start_date,
        end_date=end_date,
    )
    price_panel = load_industry_price_panel(
        catalog=catalog,
        start_date=start_date,
        end_date=end_date,
    )

    min_panel_d = panel["trade_date"].min()
    max_panel_d = panel["trade_date"].max()
    actual_start: date | None = (
        start_date
        if start_date is not None
        else (min_panel_d if isinstance(min_panel_d, date) else None)
    )
    actual_end: date | None = (
        end_date
        if end_date is not None
        else (max_panel_d if isinstance(max_panel_d, date) else None)
    )

    series_map: dict[str, pl.DataFrame] = {}
    stats_map: dict[str, dict[str, Any]] = {}

    # 2. 回测各基准
    for symbol, label in benchmarks:
        bars = catalog.load_bars(symbol=symbol, dataset="index_daily_bar")
        bench_nav = nav_from_close(bars, start_date=actual_start, end_date=actual_end)
        if not bench_nav.is_empty():
            series_map[label] = bench_nav
            stats_map[label] = compute_metrics(bench_nav)

    # 3. 回测各策略
    for key, spec in specs.items():
        cls_name = str(spec.get("strategy_class", ""))
        friction = spec.get("friction", {})
        comm = float(friction.get("commission_rate", 0.0001))
        slip = float(friction.get("slippage_rate", 0.0005))
        dead = float(friction.get("rebalance_deadband", 0.03))

        kwargs = {
            k: v
            for k, v in spec.items()
            if k not in ("strategy_class", "friction", "description", "name")
        }
        strat = create_strategy(cls_name, **kwargs)
        runner = IndustryStrategyRunner(
            strat,
            strategy_name=key,
            commission_rate=comm,
            slippage_rate=slip,
            rebalance_deadband=dead,
        )
        s_nav = runner.backtest(panel, price_panel)
        if not s_nav.is_empty():
            series_map[key] = s_nav
            stats_map[key] = compute_metrics(s_nav)

    # 4. 对齐交易日轴并生成统一 NAV DataFrame
    base_dates = panel["trade_date"].unique(maintain_order=True).sort()
    merged_nav = pl.DataFrame({"trade_date": base_dates})
    for name, df in series_map.items():
        sub = df.select(["trade_date", pl.col("nav").alias(name)])
        merged_nav = merged_nav.join(sub, on="trade_date", how="left")

    csv_path = out_dir / "multi_strategy_nav.csv"
    merged_nav.write_csv(csv_path)

    # 5. 渲染图表与研报
    png_path = out_dir / "multi_strategy_comparison.png"
    render_industry_comparison_chart(series_map, png_path, benchmarks_list=benchmarks)

    md_path = out_dir / "multi_strategy_comparison.md"
    min_val = merged_nav["trade_date"].min()
    max_val = merged_nav["trade_date"].max()
    min_d = min_val if isinstance(min_val, date) else None
    max_d = max_val if isinstance(max_val, date) else None
    md_content = render_industry_comparison_markdown(
        stats_map,
        start=min_d,
        end=max_d,
        out_path=md_path,
        benchmarks_list=benchmarks,
        image_rel_path="multi_strategy_comparison.png",
    )

    return {
        "stats": stats_map,
        "csv": str(csv_path),
        "png": str(png_path),
        "markdown": str(md_path),
        "markdown_content": md_content,
    }


__all__ = [
    "build_multi_industry_comparison_report",
    "compute_metrics",
    "load_all_industry_strategy_specs",
    "load_industry_benchmarks",
]
