"""申万行业日行情的 SW2021 层级归属补充。"""

from __future__ import annotations

import polars as pl

SW_DAILY_CLASSIFICATION_COLUMNS = (
    "classification",
    "industry_level",
    "industry_code",
    "industry_name",
    "parent_code",
    "classification_status",
)

_MAPPING_COLUMNS = {
    "index_code",
    "level",
    "industry_code",
    "src",
}


def normalize_sw_daily_identity(frame: pl.DataFrame) -> pl.DataFrame:
    """统一 sw_daily 的 symbol/ts_code/index_id 标识，兼容历史 RAW 混合列。"""
    if frame.is_empty():
        return frame
    normalized = frame
    aliases = [column for column in ("ts_code", "index_id", "code") if column in normalized.columns]
    if "symbol" not in normalized.columns:
        source = aliases[0] if aliases else None
        if source is not None:
            normalized = normalized.rename({source: "symbol"})
            aliases = aliases[1:]
    if "symbol" not in normalized.columns:
        return normalized
    expressions = [pl.col("symbol").cast(pl.Utf8, strict=False)]
    expressions.extend(pl.col(column).cast(pl.Utf8, strict=False) for column in aliases)
    normalized = normalized.with_columns(pl.coalesce(expressions).alias("symbol"))
    if aliases:
        normalized = normalized.drop(aliases)
    return normalized


def build_sw2021_index_map(index_classify: pl.DataFrame) -> pl.DataFrame:
    """从 index_classify 提取 SW2021 全层级行业指数映射。"""
    if index_classify.is_empty() or not _MAPPING_COLUMNS.issubset(index_classify.columns):
        return pl.DataFrame(
            schema={
                "symbol": pl.Utf8,
                "classification": pl.Utf8,
                "industry_level": pl.Utf8,
                "industry_code": pl.Utf8,
                "industry_name": pl.Utf8,
                "parent_code": pl.Utf8,
            }
        )

    optional_name = (
        pl.col("industry_name").cast(pl.Utf8, strict=False)
        if "industry_name" in index_classify.columns
        else pl.lit(None, dtype=pl.Utf8)
    )
    optional_parent = (
        pl.col("parent_code").cast(pl.Utf8, strict=False)
        if "parent_code" in index_classify.columns
        else pl.lit(None, dtype=pl.Utf8)
    )
    return (
        index_classify.filter(pl.col("src") == "SW2021")
        .select(
            pl.col("index_code").cast(pl.Utf8, strict=False).alias("symbol"),
            pl.lit("SW2021").alias("classification"),
            pl.col("level").cast(pl.Utf8, strict=False).alias("industry_level"),
            pl.col("industry_code").cast(pl.Utf8, strict=False).alias("industry_code"),
            optional_name.alias("industry_name"),
            optional_parent.alias("parent_code"),
        )
        .drop_nulls(subset=["symbol"])
        .unique(subset=["symbol"], keep="last")
    )


def enrich_sw_daily_frame(
    frame: pl.DataFrame,
    index_classify: pl.DataFrame | None,
) -> pl.DataFrame:
    """为 sw_daily 补充 SW2021 归属；未映射行情不被物理删除。"""
    if frame.is_empty():
        return frame

    enriched = normalize_sw_daily_identity(frame)
    has_symbol = "symbol" in enriched.columns
    if not has_symbol:
        enriched = enriched.with_columns(pl.lit(None, dtype=pl.Utf8).alias("symbol"))
        enriched = enriched.select(["symbol", *[c for c in enriched.columns if c != "symbol"]])

    existing = [column for column in SW_DAILY_CLASSIFICATION_COLUMNS if column in enriched.columns]
    if existing:
        enriched = enriched.drop(existing)

    mapping = build_sw2021_index_map(
        index_classify if index_classify is not None else pl.DataFrame()
    )
    if mapping.is_empty() or not has_symbol:
        status = "metadata_unavailable" if mapping.is_empty() else "unmapped"
        return enriched.with_columns(
            [
                pl.lit(None, dtype=pl.Utf8).alias(column)
                for column in SW_DAILY_CLASSIFICATION_COLUMNS[:-1]
            ]
            + [pl.lit(status).alias("classification_status")]
        )

    enriched = enriched.join(mapping, on="symbol", how="left")
    return enriched.with_columns(
        pl.when(pl.col("classification").is_not_null())
        .then(pl.lit("mapped"))
        .otherwise(pl.lit("unmapped"))
        .alias("classification_status")
    )
