"""行业结构分析面板基础数据源加载与映射。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from stock.analytics.pipelines.industry_structure.config import IndustryStructureConfig
    from stock.data.catalog import DataCatalog

_FS_DATASETS = (
    "sw_2021_fs_non_financial",
    "sw_2021_fs_bank",
    "sw_2021_fs_security",
    "sw_2021_fs_insurance",
)


def load_dataset(
    catalog: DataCatalog,
    dataset: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    symbols: list[str] | None = None,
) -> pl.DataFrame:
    """从 DataCatalog 加载指定数据集，异常时返回空 DataFrame。"""
    try:
        return catalog.load_dataset(
            dataset,
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
        )
    except Exception:
        return pl.DataFrame()


def load_industry_l1_maps(
    catalog: DataCatalog,
    config: IndustryStructureConfig,
) -> tuple[dict[str, str], dict[str, str]]:
    """加载指数/行业代码到申万一级代码的映射字典。"""
    raw = load_dataset(catalog, "index_classify")
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
    cat_ts: DataCatalog,
    cat_lx: DataCatalog,
    config: IndustryStructureConfig,
    as_of_date: date,
) -> pl.DataFrame:
    """加载个股到申万一级行业的归属映射表。"""
    index_to_l1, industry_to_l1 = load_industry_l1_maps(cat_ts, config)
    frames: list[pl.DataFrame] = []
    ts_map = _stock_industry_map_from_index_member(cat_ts, as_of_date, index_to_l1)
    if not ts_map.is_empty():
        frames.append(ts_map.with_columns(pl.lit(0).alias("_source_priority")))
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


def load_financial_statement_history(cat: DataCatalog, as_of_date: date) -> pl.DataFrame:
    """加载非金融与三大金融行业的历史财务数据。"""
    frames: list[pl.DataFrame] = []
    for dataset in _FS_DATASETS:
        raw = load_dataset(
            cat,
            dataset,
            start_date=as_of_date - timedelta(days=365 * 6),
            end_date=as_of_date,
        )
        extracted = _extract_fs_frame(raw)
        if not extracted.is_empty():
            frames.append(extracted)
    return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()


def load_moneyflow_base_frame(
    catalog: DataCatalog,
    start_date: date,
    as_of_date: date,
) -> pl.DataFrame:
    """加载个股资金流基础数据。"""
    raw = load_dataset(catalog, "moneyflow", start_date=start_date, end_date=as_of_date)
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
    catalog: DataCatalog,
    start_date: date,
    as_of_date: date,
) -> pl.DataFrame:
    """加载个股成交金额基础数据。"""
    raw = load_dataset(catalog, "stock_daily_bar", start_date=start_date, end_date=as_of_date)
    if raw.is_empty() or not {"symbol", "trade_date", "amount"}.issubset(raw.columns):
        return pl.DataFrame()
    return raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        "trade_date",
        pl.col("amount").cast(pl.Float64, strict=False).alias("_amount"),
    ).drop_nulls(subset=["stock_key", "trade_date"])


def load_benchmark_return_20d(
    catalog: DataCatalog,
    benchmark: str,
    as_of_date: date,
) -> float | None:
    """加载基准指数20日区间收益率。"""
    if not benchmark:
        return None
    frame = load_dataset(
        catalog,
        "index_daily",
        start_date=as_of_date - timedelta(days=120),
        end_date=as_of_date,
        symbols=[benchmark],
    )
    if frame.is_empty() or not {"trade_date", "close"}.issubset(frame.columns):
        return None
    frame = frame.sort("trade_date").drop_nulls(subset=["close"])
    if frame.height <= 20:
        return None
    try:
        latest = float(frame["close"][-1])
        previous = float(frame["close"][-21])
    except (TypeError, ValueError):
        return None
    if previous <= 0:
        return None
    return (latest / previous - 1.0) * 100.0


def map_l1_code(value: object, mapping: dict[str, str]) -> str | None:
    """将行业代码通过映射表归一化为申万一级代码。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return mapping.get(text) or mapping.get(text.split(".")[0])


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


def _classify_frame(raw: pl.DataFrame, classification: str) -> pl.DataFrame:
    if "src" not in raw.columns:
        return raw
    return raw.filter(pl.col("src") == classification)


def _l1_by_industry_code(frame: pl.DataFrame) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in frame.filter(pl.col("level") == "L1").to_dicts():
        industry_code = str(row.get("industry_code") or "")
        index_code = str(row.get("index_code") or "")
        if industry_code and index_code:
            mapping[industry_code] = index_code
    return mapping


def _stock_industry_map_from_index_member(
    catalog: DataCatalog,
    as_of_date: date,
    index_to_l1: dict[str, str],
) -> pl.DataFrame:
    raw = load_dataset(catalog, "index_member")
    if raw.is_empty() or not {"index_code", "con_code"}.issubset(raw.columns) or not index_to_l1:
        return pl.DataFrame()
    as_of_text = as_of_date.strftime("%Y%m%d")
    base = raw.select(
        pl.col("con_code").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        pl.col("index_code").cast(pl.String).alias("index_code"),
        optional_text_expr(raw, ("in_date",), "in_date"),
        optional_text_expr(raw, ("out_date",), "out_date"),
    )
    base = base.filter(
        ((pl.col("in_date").is_null()) | (pl.col("in_date") <= as_of_text))
        & (
            (pl.col("out_date").is_null())
            | (pl.col("out_date") == "")
            | (pl.col("out_date") > as_of_text)
        )
    )
    return base.with_columns(
        pl.col("index_code")
        .map_elements(lambda value: map_l1_code(value, index_to_l1), return_dtype=pl.Utf8)
        .alias("industry_code")
    ).select("stock_key", "industry_code")


def _stock_industry_map_from_lixinger_constituents(
    catalog: DataCatalog,
    industry_to_l1: dict[str, str],
) -> pl.DataFrame:
    raw = load_dataset(catalog, "sw_2021_constituents")
    if raw.is_empty() or not {"symbol", "industryCode"}.issubset(raw.columns) or not industry_to_l1:
        return pl.DataFrame()
    return raw.select(
        pl.col("symbol").cast(pl.String).str.slice(0, 6).alias("stock_key"),
        pl.col("industryCode")
        .cast(pl.String)
        .map_elements(lambda value: map_l1_code(value, industry_to_l1), return_dtype=pl.Utf8)
        .alias("industry_code"),
    )


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
