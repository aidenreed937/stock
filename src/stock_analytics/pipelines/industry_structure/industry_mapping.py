"""行业结构个股到申万一级行业的映射加载。"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

import polars as pl

from stock_analytics.catalog_compat import load_dataset_compat

if TYPE_CHECKING:
    from stock_core.contracts import MarketDataCatalog
    from stock_reporting.interpretation.industry_structure.config import IndustryStructureConfig


def _load_dataset(
    catalog: MarketDataCatalog,
    dataset: str,
    *,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    try:
        return load_dataset_compat(catalog, dataset, columns=columns)
    except Exception:
        return pl.DataFrame()


def load_industry_l1_maps(
    catalog: MarketDataCatalog,
    config: IndustryStructureConfig,
) -> tuple[dict[str, str], dict[str, str]]:
    """加载指数/行业代码到申万一级代码的映射字典。"""
    raw = _load_dataset(
        catalog,
        "index_classify",
        columns=["index_code", "industry_code", "level", "src"],
    )
    if raw.is_empty() or not {"index_code", "industry_code", "level"}.issubset(raw.columns):
        return {}, {}
    frame = _classify_frame(raw, config.classification)
    if frame.is_empty():
        return {}, {}
    l1_by_industry_code = _l1_by_industry_code(frame)
    index_to_l1: dict[str, str] = {}
    industry_to_l1: dict[str, str] = {}
    for row in frame.to_dicts():
        index_code = str(row.get("index_code") or "")
        industry_code = str(row.get("industry_code") or "")
        if not industry_code:
            continue
        l1_key = f"{industry_code[:2]}0000" if len(industry_code) >= 2 else industry_code
        l1_code = l1_by_industry_code.get(industry_code) or l1_by_industry_code.get(l1_key)
        if not l1_code:
            continue
        industry_to_l1[industry_code] = l1_code
        if index_code:
            index_to_l1[index_code] = l1_code
            if "." in index_code:
                index_to_l1[index_code.split(".")[0]] = l1_code
    return index_to_l1, industry_to_l1


def load_stock_industry_map(
    cat_ts: MarketDataCatalog,
    cat_lx: MarketDataCatalog,
    config: IndustryStructureConfig,
    as_of_date: date,
) -> pl.DataFrame:
    """加载个股到申万一级行业的归属映射表。"""
    index_to_l1, industry_to_l1 = load_industry_l1_maps(cat_ts, config)
    frames: list[pl.DataFrame] = []
    ts_map = _stock_industry_map_from_index_member(cat_ts, as_of_date, index_to_l1)
    if not ts_map.is_empty():
        frames.append(ts_map.with_columns(pl.lit(0).alias("_source_priority")))
    if _is_current_industry_date(cat_ts, as_of_date):
        lx_map = _stock_industry_map_from_lixinger_constituents(cat_lx, industry_to_l1)
        if not lx_map.is_empty():
            frames.append(lx_map.with_columns(pl.lit(1).alias("_source_priority")))
    if not frames:
        return pl.DataFrame(schema={"stock_key": pl.Utf8, "industry_code": pl.Utf8})
    return (
        pl.concat(frames, how="vertical_relaxed")
        .drop_nulls(subset=["stock_key", "industry_code"])
        .sort(["stock_key", "_source_priority", "industry_code"])
        .unique(subset=["stock_key"], keep="first", maintain_order=True)
        .select("stock_key", "industry_code")
    )


def prepare_stock_industry_members(
    catalog: MarketDataCatalog,
    index_to_l1: dict[str, str],
) -> pl.DataFrame:
    """一次归一成分变更记录，供批次内多个基准日复用。"""
    raw = _load_dataset(
        catalog,
        "index_member",
        columns=["index_code", "con_code", "in_date", "out_date"],
    )
    if raw.is_empty() or not {"index_code", "con_code"}.issubset(raw.columns):
        return pl.DataFrame(schema={"stock_key": pl.Utf8, "in_date": pl.Date, "out_date": pl.Date})
    return raw.select(
        pl.col("con_code").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        pl.col("index_code")
        .cast(pl.String)
        .map_elements(lambda value: map_l1_code(value, index_to_l1), return_dtype=pl.Utf8)
        .alias("industry_code"),
        _date_column_expr(raw, "in_date", "in_date"),
        _date_column_expr(raw, "out_date", "out_date"),
    ).drop_nulls(subset=["stock_key", "industry_code"])


def stock_industry_map_from_prepared_members(
    members: pl.DataFrame,
    as_of_date: date,
) -> pl.DataFrame:
    """从已归一成分变更记录切出指定基准日映射。"""
    if members.is_empty():
        return pl.DataFrame(schema={"stock_key": pl.Utf8, "industry_code": pl.Utf8})
    return (
        members.filter(
            ((pl.col("in_date").is_null()) | (pl.col("in_date") <= as_of_date))
            & ((pl.col("out_date").is_null()) | (pl.col("out_date") > as_of_date))
        )
        .sort(["stock_key", "industry_code"])
        .unique(subset=["stock_key"], keep="first", maintain_order=True)
        .select("stock_key", "industry_code")
    )


def _is_current_industry_date(catalog: MarketDataCatalog, as_of_date: date) -> bool:
    """仅在申万行情最新日允许使用无日期的静态成分补充。"""
    try:
        latest_dates = catalog.latest_trade_dates(dataset="sw_daily", n=1)
    except Exception:
        return False
    if not latest_dates:
        return False
    return parse_date_value(latest_dates[0]) == as_of_date


def _stock_industry_map_from_index_member(
    catalog: MarketDataCatalog,
    as_of_date: date,
    index_to_l1: dict[str, str],
) -> pl.DataFrame:
    raw = _load_dataset(
        catalog,
        "index_member",
        columns=["index_code", "con_code", "in_date", "out_date"],
    )
    if raw.is_empty() or not {"index_code", "con_code"}.issubset(raw.columns) or not index_to_l1:
        return pl.DataFrame()
    base = raw.select(
        pl.col("con_code").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        pl.col("index_code").cast(pl.String).alias("index_code"),
        _date_column_expr(raw, "in_date", "in_date"),
        _date_column_expr(raw, "out_date", "out_date"),
    ).filter(
        ((pl.col("in_date").is_null()) | (pl.col("in_date") <= pl.lit(as_of_date)))
        & ((pl.col("out_date").is_null()) | (pl.col("out_date") > pl.lit(as_of_date)))
    )
    return base.with_columns(
        pl.col("index_code")
        .map_elements(lambda value: map_l1_code(value, index_to_l1), return_dtype=pl.Utf8)
        .alias("industry_code")
    ).select("stock_key", "industry_code")


def _stock_industry_map_from_lixinger_constituents(
    catalog: MarketDataCatalog,
    industry_to_l1: dict[str, str],
) -> pl.DataFrame:
    raw = _load_dataset(catalog, "sw_2021_constituents", columns=["symbol", "industryCode"])
    if raw.is_empty() or not {"symbol", "industryCode"}.issubset(raw.columns) or not industry_to_l1:
        return pl.DataFrame()
    return raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        pl.col("industryCode")
        .cast(pl.String)
        .map_elements(lambda value: map_l1_code(value, industry_to_l1), return_dtype=pl.Utf8)
        .alias("industry_code"),
    )


def map_l1_code(value: object, mapping: dict[str, str]) -> str | None:
    """将行业代码通过映射表归一化为申万一级代码。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return mapping.get(text) or mapping.get(text.split(".")[0])


def _date_column_expr(frame: pl.DataFrame, column: str, alias: str) -> pl.Expr:
    if column not in frame.columns:
        return pl.lit(None, dtype=pl.Date).alias(alias)
    return pl.col(column).map_elements(parse_date_value, return_dtype=pl.Date).alias(alias)


def parse_date_value(value: object) -> date | None:
    """解析日期、日期时间或紧凑日期文本。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    compact = text.replace("-", "")[:8]
    if len(compact) == 8 and compact.isdigit():
        return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
    return None


def _classify_frame(raw: pl.DataFrame, classification: str) -> pl.DataFrame:
    if "src" not in raw.columns:
        return raw
    return raw.filter(pl.col("src") == classification)


def _l1_by_industry_code(frame: pl.DataFrame) -> dict[str, str]:
    return {
        str(row["industry_code"]): str(row["index_code"])
        for row in frame.filter(pl.col("level") == "L1").to_dicts()
        if row.get("industry_code") and row.get("index_code")
    }
