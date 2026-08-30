"""宏观风控策略数据装配：风险因子面板 × 指数日线 close 对齐。

信号面板以基准指数日线交易日为轴，左连接宏观双轨制风险因子
（``overheat_index`` / ``panic_index``）并向前填充；价格面板按标的投影
``trade_date x symbol x close``，供策略层信号生成与回测净值使用。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.macro_risk import load_latest_risk_factors
from stock_core.exceptions import DataValidationError
from stock_data.catalog import DataCatalog

_SIGNAL_COLUMNS = ("trade_date", "close", "panic_index", "overheat_index")
_INDEX_DATASET = "index_daily_bar"


def assemble_macro_panel(
    *,
    catalog: DataCatalog,
    benchmark_symbol: str,
    risk_root: Path | str = "data/analytics/macro_risk",
    start_date: date | None = None,
    end_date: date | None = None,
) -> pl.DataFrame:
    """装配宏观风控策略信号面板。

    Args:
        catalog: 本地 Curated 数据目录（tushare）。
        benchmark_symbol: 趋势基准指数代码（如 000985.CSI）。
        risk_root: 宏观风险产物根目录。
        start_date: 可选起始日期截断。
        end_date: 可选截止日期截断。

    Returns:
        ``trade_date / close / panic_index / overheat_index`` 面板，按 trade_date 升序。
    """
    _run_dir, factors, _manifest = load_latest_risk_factors(risk_root)
    if factors.is_empty() or not {"trade_date", "panic_index", "overheat_index"}.issubset(
        factors.columns
    ):
        raise DataValidationError("宏观风险因子面板缺少 trade_date/panic_index/overheat_index 列")

    close = catalog.load_bars(
        symbol=benchmark_symbol,
        dataset=_INDEX_DATASET,
        columns=["trade_date", "close"],
    )
    if close.is_empty():
        raise DataValidationError(f"指数日线为空: {benchmark_symbol}")

    extra_cols = [
        c
        for c in [
            "divergence_score_score",
            "composite_flow_score",
            "repurchase_score",
            "insider_net_score",
            "insider_sell_score",
            "unlock_amount_score",
            "cb_price_score",
            "copper_gold_score",
            "dim_flow",
            "dim_valuation",
            "dim_leverage",
            "dim_crowding",
            "dim_fear",
            "dim_euphoria",
            "dim_breadth",
            "dim_corporate",
            "dim_cross_asset",
            "smart_money_pct",
        ]
        if c in factors.columns
    ]
    factor_cols = ["trade_date", "panic_index", "overheat_index", *extra_cols]

    factors = (
        factors.select(factor_cols)
        .with_columns(pl.col("trade_date").cast(pl.Date))
        .sort("trade_date")
    )
    close = (
        close.select(["trade_date", "close"])
        .with_columns(
            pl.col("trade_date").cast(pl.Date),
            pl.col("close").cast(pl.Float64, strict=False),
        )
        .unique(subset=["trade_date"], keep="last")
        .sort("trade_date")
    )

    fill_exprs = [
        pl.col("panic_index").forward_fill(),
        pl.col("overheat_index").forward_fill(),
        *(pl.col(c).forward_fill() for c in extra_cols),
    ]

    panel = (
        close.join(factors, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(fill_exprs)
        .drop_nulls(subset=["panic_index", "overheat_index"])
    )
    if start_date is not None:
        panel = panel.filter(pl.col("trade_date") >= start_date)
    if end_date is not None:
        panel = panel.filter(pl.col("trade_date") <= end_date)
    return panel.select(["trade_date", "close", "panic_index", "overheat_index", *extra_cols])


def _adjust_etf_price(catalog: DataCatalog, bar: pl.DataFrame, sym: str) -> pl.DataFrame:
    """若存在 fund_adj 复权因子，将 ETF 原始收盘价转换为后复权收盘价。"""
    if bar.is_empty() or "close" not in bar.columns:
        return bar
    candidate_symbols = [sym]
    if "." not in sym:
        candidate_symbols.extend([f"{sym}.SH", f"{sym}.SZ"])
    else:
        candidate_symbols.append(sym.split(".")[0])

    adj_df = pl.DataFrame()
    try:
        adj_df = catalog.load_dataset("fund_adj", symbols=candidate_symbols)
    except Exception:
        pass

    if adj_df.is_empty() and catalog.data_source != "tushare":
        try:
            from stock_data.catalog import DataCatalog

            ts_cat = DataCatalog(runtime=catalog.runtime, data_source="tushare")
            adj_df = ts_cat.load_dataset("fund_adj", symbols=candidate_symbols)
        except Exception:
            pass

    if not adj_df.is_empty() and "trade_date" in adj_df.columns and "adj_factor" in adj_df.columns:
        adj_clean = (
            adj_df.select(
                [
                    pl.col("trade_date").cast(pl.Date),
                    pl.col("adj_factor").cast(pl.Float64, strict=False),
                ]
            )
            .drop_nulls(subset=["trade_date", "adj_factor"])
            .unique(subset=["trade_date"], keep="last")
        )
        bar = (
            bar.with_columns(pl.col("trade_date").cast(pl.Date))
            .join(adj_clean, on="trade_date", how="left")
            .with_columns(
                pl.when(pl.col("adj_factor").is_not_null() & (pl.col("adj_factor") > 0))
                .then(pl.col("close") * pl.col("adj_factor"))
                .otherwise(pl.col("close"))
                .alias("close")
            )
            .drop("adj_factor")
        )
    return bar


def load_price_panel(
    *,
    catalog: DataCatalog,
    symbols: Sequence[str],
    start_date: date | None = None,
    end_date: date | None = None,
) -> pl.DataFrame:
    """装配多标的指数日线价格面板（回测净值用）。

    对 ETF 标的自动加载 ``fund_adj`` 复权因子并计算后复权价，消除分红除权带来的收益低估。

    Returns:
        ``trade_date / symbol / close`` 长表，按 (trade_date, symbol) 升序。
    """
    frames = []
    for sym in symbols:
        is_etf = any(sym.startswith(prefix) for prefix in ("51", "15", "56", "58"))
        datasets = (
            ["fund_daily", _INDEX_DATASET, "stock_daily_bar"]
            if is_etf
            else [_INDEX_DATASET, "fund_daily", "stock_daily_bar"]
        )
        bar = pl.DataFrame()
        for ds in datasets:
            bar = catalog.load_bars(
                symbol=sym,
                dataset=ds,
                columns=["trade_date", "symbol", "close"],
            )
            if bar.is_empty() and catalog.data_source != "lixinger":
                from stock_data.catalog import DataCatalog

                lix_cat = DataCatalog(runtime=catalog.runtime, data_source="lixinger")
                bar = lix_cat.load_bars(
                    symbol=sym,
                    dataset=ds,
                    columns=["trade_date", "symbol", "close"],
                )
            if not bar.is_empty():
                if is_etf and ds == "fund_daily":
                    bar = _adjust_etf_price(catalog, bar, sym)
                frames.append(bar)
                break
    if not frames:
        return pl.DataFrame()

    panel = (
        pl.concat(frames, how="vertical_relaxed")
        .with_columns(
            pl.col("trade_date").cast(pl.Date),
            pl.col("close").cast(pl.Float64, strict=False),
        )
        .unique(subset=["trade_date", "symbol"], keep="last")
        .sort(["trade_date", "symbol"])
    )
    if start_date is not None:
        panel = panel.filter(pl.col("trade_date") >= start_date)
    if end_date is not None:
        panel = panel.filter(pl.col("trade_date") <= end_date)
    return panel.select(["trade_date", "symbol", "close"])


__all__ = ["assemble_macro_panel", "load_price_panel"]
