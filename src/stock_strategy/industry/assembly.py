"""申万行业策略数据装配层：5 大中观因子面板 × 行业日线 × 宏观风控雷达。

职责：
1. 装配全周期申万 31 行业量化因子面板；
2. 左连接宏观双轨制指标 (panic_index / overheat_index) 与基准指数 MA20 趋势；
3. 输出多资产回测所需的标的价格面板 (trade_date x symbol x close)。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.industry_structure import load_latest_industry_factors
from stock_core.exceptions import DataValidationError
from stock_data.catalog import DataCatalog


def assemble_industry_panel(
    *,
    catalog: DataCatalog | None = None,
    benchmark_symbol: str = "000985.CSI",
    factor_root: Path | str = "data/analytics/industry_structure",
    macro_risk_root: Path | str = "data/analytics/macro_risk",
    start_date: date | None = None,
    end_date: date | None = None,
) -> pl.DataFrame:
    """装配申万 31 行业策略研究信号面板。"""
    cat = catalog or DataCatalog(data_source="tushare")

    # 1. 加载 5 大中观因子面板
    _run_dir, factors, _manifest = load_latest_industry_factors(factor_root)
    if factors.is_empty() or "trade_date" not in factors.columns:
        raise DataValidationError("行业因子面板为空或缺少 trade_date 列")

    factors = factors.with_columns(pl.col("trade_date").cast(pl.Date)).sort(
        ["trade_date", "industry_code"]
    )

    # 2. 读取宏观风险雷达 (若存在)
    macro_p = Path(macro_risk_root) / "latest" / "risk_factors.parquet"
    if macro_p.exists():
        try:
            macro_df = (
                pl.read_parquet(macro_p)
                .select(["trade_date", "panic_index", "overheat_index"])
                .with_columns(pl.col("trade_date").cast(pl.Date))
                .sort("trade_date")
            )
            factors = factors.join(macro_df, on="trade_date", how="left")
        except Exception:
            factors = factors.with_columns(
                [
                    pl.lit(50.0).alias("panic_index"),
                    pl.lit(50.0).alias("overheat_index"),
                ]
            )
    else:
        factors = factors.with_columns(
            [
                pl.lit(50.0).alias("panic_index"),
                pl.lit(50.0).alias("overheat_index"),
            ]
        )

    # 3. 读取基准日线并计算 MA20 趋势
    bench_bars = cat.load_bars(
        symbol=benchmark_symbol,
        dataset="index_daily_bar",
        columns=["trade_date", "close"],
    )
    if not bench_bars.is_empty():
        bench_df = (
            bench_bars.select(["trade_date", "close"])
            .with_columns(
                pl.col("trade_date").cast(pl.Date),
                pl.col("close").cast(pl.Float64, strict=False),
            )
            .sort("trade_date")
            .with_columns(
                pl.col("close").rolling_mean(window_size=20).alias("benchmark_ma20"),
            )
            .rename({"close": "benchmark_close"})
        )
        factors = factors.join(bench_df, on="trade_date", how="left")
    else:
        factors = factors.with_columns(
            [
                pl.lit(100.0).alias("benchmark_close"),
                pl.lit(100.0).alias("benchmark_ma20"),
            ]
        )

    if start_date is not None:
        factors = factors.filter(pl.col("trade_date") >= start_date)
    if end_date is not None:
        factors = factors.filter(pl.col("trade_date") <= end_date)

    return factors.sort(["trade_date", "industry_code"])


def load_industry_price_panel(
    catalog: DataCatalog | None = None,
    *,
    symbols: Sequence[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pl.DataFrame:
    """加载 31 行业历史日收盘价格长表 (trade_date x symbol x close)。"""
    cat = catalog or DataCatalog(data_source="tushare")
    mart_file = cat.runtime.data_root / "curated" / "mart" / "industry_daily.parquet"
    if not mart_file.exists():
        raise DataValidationError(f"未找到行业行情表: {mart_file}")

    df = pl.read_parquet(mart_file).select(
        [
            pl.col("trade_date").cast(pl.Date),
            pl.col("industry_code").alias("symbol"),
            pl.col("close").cast(pl.Float64, strict=False),
        ]
    )

    if symbols:
        df = df.filter(pl.col("symbol").is_in(list(symbols)))
    if start_date is not None:
        df = df.filter(pl.col("trade_date") >= start_date)
    if end_date is not None:
        df = df.filter(pl.col("trade_date") <= end_date)

    return df.sort(["trade_date", "symbol"])


__all__ = ["assemble_industry_panel", "load_industry_price_panel"]
