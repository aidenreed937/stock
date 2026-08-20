"""行业结构分析面板基础数据源加载与映射。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

import polars as pl

from stock_analytics.catalog_compat import load_dataset_compat
from stock_analytics.pipelines.industry_structure.industry_mapping import (
    _stock_industry_map_from_index_member,
    _stock_industry_map_from_lixinger_constituents,
    load_industry_l1_maps,
    load_stock_industry_map,
    map_l1_code,
)

if TYPE_CHECKING:
    from stock_core.contracts import MarketDataCatalog

__all__ = [
    "_stock_industry_map_from_index_member",
    "_stock_industry_map_from_lixinger_constituents",
    "load_benchmark_return_20d",
    "load_dataset",
    "load_financial_statement_history",
    "load_industry_l1_maps",
    "load_moneyflow_base_frame",
    "load_stock_amount_frame",
    "load_stock_industry_map",
    "map_l1_code",
]

_FS_DATASETS = (
    "sw_2021_fs_non_financial",
    "sw_2021_fs_bank",
    "sw_2021_fs_security",
    "sw_2021_fs_insurance",
)


def load_dataset(
    catalog: MarketDataCatalog,
    dataset: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    symbols: list[str] | None = None,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """从 DataCatalog 加载指定数据集，异常时返回空 DataFrame。"""
    try:
        return load_dataset_compat(
            catalog,
            dataset,
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            columns=columns,
        )
    except Exception:
        return pl.DataFrame()


def load_financial_statement_history(
    cat: MarketDataCatalog,
    as_of_date: date,
    *,
    start_date: date | None = None,
) -> pl.DataFrame:
    """加载非金融与三大金融行业的历史财务数据。"""
    effective_start = start_date or (as_of_date - timedelta(days=365 * 6))
    frames: list[pl.DataFrame] = []
    for dataset in _FS_DATASETS:
        raw = load_dataset(
            cat,
            dataset,
            start_date=effective_start,
            end_date=as_of_date,
            columns=[
                "symbol",
                "trade_date",
                "q",
                "revenue_growth_ttm",
                "revenue_ttm_yoy",
                "profit_growth_ttm",
                "profit_ttm_yoy",
                "roe_ttm",
            ],
        )
        extracted = _extract_fs_frame(raw)
        if not extracted.is_empty():
            frames.append(extracted)
    return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()


def load_moneyflow_base_frame(
    catalog: MarketDataCatalog,
    start_date: date,
    as_of_date: date,
) -> pl.DataFrame:
    """加载个股资金流基础数据。"""
    raw = load_dataset(
        catalog,
        "moneyflow",
        start_date=start_date,
        end_date=as_of_date,
        columns=[
            "symbol",
            "trade_date",
            "net_mf_amount",
            "buy_lg_amount",
            "buy_elg_amount",
            "sell_lg_amount",
            "sell_elg_amount",
        ],
    )
    required = {"symbol", "trade_date"}
    if raw.is_empty() or not required.issubset(raw.columns):
        return pl.DataFrame()
    buy_large = _sum_optional_columns(raw, ("buy_lg_amount", "buy_elg_amount"))
    sell_large = _sum_optional_columns(raw, ("sell_lg_amount", "sell_elg_amount"))
    return raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        "trade_date",
        optional_numeric_expr(raw, ("net_mf_amount",), "_net_amount"),
        (buy_large - sell_large).alias("_large_net_amount"),
    ).drop_nulls(subset=["stock_key", "trade_date"])


def load_stock_amount_frame(
    catalog: MarketDataCatalog,
    start_date: date,
    as_of_date: date,
) -> pl.DataFrame:
    """加载个股成交金额基础数据。"""
    raw = load_dataset(
        catalog,
        "stock_daily_bar",
        start_date=start_date,
        end_date=as_of_date,
        columns=["symbol", "trade_date", "amount"],
    )
    if raw.is_empty() or not {"symbol", "trade_date", "amount"}.issubset(raw.columns):
        return pl.DataFrame()
    return raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        "trade_date",
        pl.col("amount").cast(pl.Float64, strict=False).alias("_amount"),
    ).drop_nulls(subset=["stock_key", "trade_date"])


def load_benchmark_return_20d(
    catalog: MarketDataCatalog,
    benchmark: str,
    as_of_date: date,
) -> float | None:
    """加载基准指数20日区间收益率。"""
    for symbol in _benchmark_symbol_candidates(benchmark):
        frame = load_dataset(
            catalog,
            "index_daily",
            start_date=as_of_date - timedelta(days=120),
            end_date=as_of_date,
            symbols=[symbol],
            columns=["symbol", "trade_date", "close"],
        )
        if frame.is_empty() or not {"trade_date", "close"}.issubset(frame.columns):
            continue
        frame = frame.sort("trade_date").drop_nulls(subset=["close"])
        if frame.height <= 20:
            continue
        try:
            latest = float(frame["close"][-1])
            previous = float(frame["close"][-21])
        except (TypeError, ValueError):
            continue
        if previous <= 0:
            continue
        return (latest / previous - 1.0) * 100.0
    return None


def _benchmark_symbol_candidates(benchmark: str) -> tuple[str, ...]:
    normalized = benchmark.strip()
    if not normalized:
        return ()
    candidates = [normalized]
    if "." not in normalized:
        candidates.append(f"{normalized}.CSI")
    return tuple(dict.fromkeys(candidates))


def optional_numeric_expr(
    frame: pl.DataFrame,
    candidates: tuple[str, ...],
    alias: str,
) -> pl.Expr:
    """从候选列名中提取首个存在的数值列并重命名。"""
    column = _first_existing_column(frame, candidates)
    if column is None:
        return pl.lit(None, dtype=pl.Float64).alias(alias)
    return pl.col(column).cast(pl.Float64, strict=False).alias(alias)


def optional_text_expr(
    frame: pl.DataFrame,
    candidates: tuple[str, ...],
    alias: str,
) -> pl.Expr:
    """从候选列名中提取首个存在的字符串列并重命名。"""
    column = _first_existing_column(frame, candidates)
    if column is None:
        return pl.lit(None, dtype=pl.Utf8).alias(alias)
    return pl.col(column).cast(pl.String).alias(alias)


def date_column_expr(frame: pl.DataFrame, column: str, alias: str) -> pl.Expr:
    """将日期文本解析为 pl.Date 表达式。"""
    if column not in frame.columns:
        return pl.lit(None, dtype=pl.Date).alias(alias)
    return pl.col(column).map_elements(parse_date_value, return_dtype=pl.Date).alias(alias)


def parse_date_value(value: object) -> date | None:
    """通用日期解析函数。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    compact = text.replace("-", "")[:8]
    if len(compact) == 8 and compact.isdigit():
        return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
    return None


def _extract_fs_frame(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty() or not {"symbol", "trade_date"}.issubset(frame.columns):
        return pl.DataFrame()
    if "q" in frame.columns:
        try:
            return frame.select(
                pl.col("symbol").cast(pl.String).alias("industry_code"),
                "trade_date",
                pl.col("q")
                .struct.field("ps")
                .struct.field("toi")
                .struct.field("ttm_y2y")
                .cast(pl.Float64, strict=False)
                .alias("revenue_growth_ttm"),
                pl.col("q")
                .struct.field("ps")
                .struct.field("np")
                .struct.field("ttm_y2y")
                .cast(pl.Float64, strict=False)
                .alias("profit_growth_ttm"),
                pl.col("q")
                .struct.field("m")
                .struct.field("roe")
                .struct.field("ttm")
                .cast(pl.Float64, strict=False)
                .alias("roe_ttm"),
            ).drop_nulls(subset=["industry_code", "trade_date"])
        except Exception:
            return _extract_fs_frame_from_columns(frame)
    return _extract_fs_frame_from_columns(frame)


def _extract_fs_frame_from_columns(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.select(
        pl.col("symbol").cast(pl.String).alias("industry_code"),
        "trade_date",
        optional_numeric_expr(
            frame,
            (
                "revenue_growth_ttm",
                "revenue_ttm_yoy",
                "ps.toi.ttm_y2y",
                "ps.toi.c_y2y",
                "toi_ttm_yoy",
            ),
            "revenue_growth_ttm",
        ),
        optional_numeric_expr(
            frame,
            (
                "profit_growth_ttm",
                "profit_ttm_yoy",
                "ps.np.ttm_y2y",
                "ps.np.c_y2y",
                "np_ttm_yoy",
            ),
            "profit_growth_ttm",
        ),
        optional_numeric_expr(frame, ("roe_ttm", "m.roe.ttm", "roe.ttm", "roe"), "roe_ttm"),
    ).drop_nulls(subset=["industry_code", "trade_date"])


def _sum_optional_columns(frame: pl.DataFrame, columns: tuple[str, ...]) -> pl.Expr:
    expressions = [
        pl.col(column).cast(pl.Float64, strict=False).fill_null(0.0)
        for column in columns
        if column in frame.columns
    ]
    if not expressions:
        return pl.lit(0.0)
    return sum(expressions, start=pl.lit(0.0))


def _first_existing_column(frame: pl.DataFrame, candidates: tuple[str, ...]) -> str | None:
    return next((column for column in candidates if column in frame.columns), None)
