"""半导体 IDM 库存周转天数黄金事实转换器。"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.semiconductor.fx import derive_fx_normalized_amounts
from stock_data.fetcher.industry.semiconductor.models import SemiconductorInventoryRecord
from stock_data.fetcher.industry.semiconductor.schemas import (
    INVENTORY_CURATED_SCHEMA,
    INVENTORY_RAW_SCHEMA,
)
from stock_data.fetcher.industry.semiconductor.transforms.release_date import (
    require_raw_release_dates,
)

# 周期样本分组；005930.KS_DS 是 DS 半导体整体代理，纯 Memory 库存未披露。
MEMORY_SYMBOLS = frozenset({"MU", "000660.KS", "005930.KS_DS"})
ANALOG_AUTO_SYMBOLS = frozenset({"TXN", "ADI", "STM", "NXPI"})

#: 季度级 DOI 聚合（等权/加权）与库存相态所需的最少主体数。
#:
#: 7 家 IDM 面板的半数。季度主体数低于该值时，该季度视为**不完整**，
#: 季度级聚合值与相态一律留空——避免把单家公司的财务比率当作行业级口径输出。
#: 真实案例：2026Q3 仅 ADI 一家（财季→自然季映射所致），此前会输出一个
#: "7 家 IDM 加权"的 132.3 天，实为 ADI 单家值。
#:
#: 取 4 的边界校验：当前数据季度主体数分布为 {1: 1 期, 5: 13 期, 6: 17 期, 7: 12 期}，
#: 故 2~5 中任一取值都只会影响 2026Q3 这一期，不改动任何历史值。
#: 注意：本守卫只覆盖**季度级**口径；子行业级（memory 早年 13 个季度仅 1 家）不在本次范围。
MIN_INVENTORY_CONSTITUENTS = 4


def determine_inventory_regime(weighted_doi: float | None) -> str | None:
    """根据 IDM 加权存货周转天数判定库存周期相态。"""
    if weighted_doi is None:
        return None
    if weighted_doi >= 150.0:
        return "high_overstocked"
    if weighted_doi >= 130.0:
        return "elevated_destocking"
    if weighted_doi >= 105.0:
        return "normal_balanced"
    return "tight_restocking"


def empty_raw_inventory() -> pl.DataFrame:
    """构造库存 RAW 空事实表骨架。"""
    return pl.DataFrame(schema=INVENTORY_RAW_SCHEMA)


def records_to_raw_inventory_frame(
    records: Sequence[SemiconductorInventoryRecord],
) -> pl.DataFrame:
    """将库存记录模型转换为只保留源端字段的 RAW DataFrame。"""
    if not records:
        return empty_raw_inventory()

    now_iso = now_utc_iso()
    data = {
        "symbol": [record.symbol for record in records],
        "report_quarter": [record.report_quarter for record in records],
        "trade_date": [record.trade_date for record in records],
        "subsector": [record.subsector for record in records],
        "source_period_end": [record.source_period_end for record in records],
        "fiscal_period_raw": [record.fiscal_period for record in records],
        "inventory_usd_raw": [
            record.inventory_usd_raw or str(record.inventory_usd_million) for record in records
        ],
        "cost_of_revenue_usd_raw": [
            record.cost_of_revenue_usd_raw or str(record.cost_of_revenue_usd_million)
            for record in records
        ],
        "cost_of_revenue_annual_raw": [record.cost_of_revenue_annual_raw for record in records],
        "cost_of_revenue_derivation": [record.cost_of_revenue_derivation for record in records],
        "ds_revenue_krw_raw": [record.ds_revenue_krw_raw for record in records],
        "ds_operating_profit_krw_raw": [record.ds_operating_profit_krw_raw for record in records],
        "cost_of_revenue_source": [record.cost_of_revenue_source for record in records],
        "inventory_scope": [record.inventory_scope for record in records],
        "memory_inventory_status": [record.memory_inventory_status for record in records],
        "release_date": [record.release_date for record in records],
        "source": [record.source or "SEC_EDGAR_10Q_10K_20F_6K" for record in records],
        "source_url": [record.source_url for record in records],
        "unit": [record.unit or "million_usd" for record in records],
        "data_status": [record.data_status or "actual" for record in records],
        "collected_at": [record.collected_at or now_iso for record in records],
        "raw_content_sha256": [record.raw_content_sha256 for record in records],
        "raw_snapshot_path": [record.raw_snapshot_path for record in records],
    }
    return require_raw_release_dates(
        (
            pl.DataFrame(data, schema=INVENTORY_RAW_SCHEMA)
            .unique(subset=["report_quarter", "symbol"], keep="last")
            .sort(["report_quarter", "symbol"])
        ),
        "semiconductor_inventory_days",
    )


def build_inventory_raw_frame(
    raw_rows: pl.DataFrame | Sequence[SemiconductorInventoryRecord],
) -> pl.DataFrame:
    """将库存原始记录整理为不含 DOI 和综合统计的 RAW 帧。"""
    if not isinstance(raw_rows, pl.DataFrame):
        return records_to_raw_inventory_frame(raw_rows)
    if raw_rows.is_empty():
        return empty_raw_inventory()

    columns = [
        "symbol",
        "report_quarter",
        "trade_date",
        "subsector",
        "source_period_end",
        "fiscal_period_raw",
        "inventory_usd_raw",
        "cost_of_revenue_usd_raw",
        "cost_of_revenue_annual_raw",
        "cost_of_revenue_derivation",
        "ds_revenue_krw_raw",
        "ds_operating_profit_krw_raw",
        "cost_of_revenue_source",
        "inventory_scope",
        "memory_inventory_status",
        "release_date",
        "source",
        "source_url",
        "unit",
        "data_status",
        "collected_at",
        "raw_content_sha256",
        "raw_snapshot_path",
    ]
    df = raw_rows
    additions: list[pl.Expr] = []
    if "subsector" not in df.columns:
        additions.append(
            pl.when(pl.col("symbol").str.to_uppercase().is_in(list(MEMORY_SYMBOLS)))
            .then(pl.lit("memory"))
            .otherwise(pl.lit("analog_auto"))
            .alias("subsector")
        )
    if "source_period_end" not in df.columns:
        additions.append(pl.lit(None, dtype=pl.Date).alias("source_period_end"))
    if "fiscal_period_raw" not in df.columns:
        additions.append(pl.lit("").alias("fiscal_period_raw"))
    if "inventory_usd_raw" not in df.columns:
        additions.append(
            _string_expr_from_available(df, "inventory_usd_million").alias("inventory_usd_raw")
        )
    if "cost_of_revenue_usd_raw" not in df.columns:
        additions.append(
            _string_expr_from_available(df, "cost_of_revenue_usd_million").alias(
                "cost_of_revenue_usd_raw"
            )
        )
    if "cost_of_revenue_annual_raw" not in df.columns:
        additions.append(pl.lit(None, dtype=pl.String).alias("cost_of_revenue_annual_raw"))
    if "cost_of_revenue_derivation" not in df.columns:
        additions.append(pl.lit("").alias("cost_of_revenue_derivation"))
    if "ds_revenue_krw_raw" not in df.columns:
        additions.append(pl.lit(None, dtype=pl.String).alias("ds_revenue_krw_raw"))
    if "ds_operating_profit_krw_raw" not in df.columns:
        additions.append(pl.lit(None, dtype=pl.String).alias("ds_operating_profit_krw_raw"))
    if "cost_of_revenue_source" not in df.columns:
        additions.append(pl.lit("").alias("cost_of_revenue_source"))
    if "inventory_scope" not in df.columns:
        additions.append(pl.lit("").alias("inventory_scope"))
    if "memory_inventory_status" not in df.columns:
        additions.append(pl.lit("").alias("memory_inventory_status"))
    if "source" not in df.columns:
        additions.append(pl.lit("SEC_EDGAR_10Q_10K_20F_6K").alias("source"))
    if "source_url" not in df.columns:
        additions.append(pl.lit("").alias("source_url"))
    if "unit" not in df.columns:
        additions.append(pl.lit("million_usd").alias("unit"))
    if "data_status" not in df.columns:
        additions.append(pl.lit("actual").alias("data_status"))
    if "collected_at" not in df.columns:
        additions.append(pl.lit("").alias("collected_at"))
    if "raw_content_sha256" not in df.columns:
        additions.append(pl.lit("").alias("raw_content_sha256"))
    if "raw_snapshot_path" not in df.columns:
        additions.append(pl.lit("").alias("raw_snapshot_path"))
    if additions:
        df = df.with_columns(additions)
    return require_raw_release_dates(
        (
            df.select(columns)
            .with_columns(
                [
                    pl.col(name).cast(dtype).alias(name)
                    for name, dtype in INVENTORY_RAW_SCHEMA.items()
                ]
            )
            .sort(["report_quarter", "symbol"])
        ),
        "semiconductor_inventory_days",
    )


def build_inventory_days_frame(
    raw_rows: pl.DataFrame | Sequence[SemiconductorInventoryRecord],
) -> pl.DataFrame:
    """从 IDM 财报 RAW 行计算个股 DOI、加权 DOI 与库存周期相态。"""
    df_raw = build_inventory_raw_frame(raw_rows)
    if df_raw.is_empty():
        return pl.DataFrame(schema=INVENTORY_CURATED_SCHEMA)

    inv_usd_series, cogs_usd_series = derive_fx_normalized_amounts(df_raw)
    df_raw = df_raw.with_columns(
        inv_usd_series,
        cogs_usd_series,
        pl.when(pl.col("symbol").str.to_uppercase().is_in(list(MEMORY_SYMBOLS)))
        .then(pl.lit("memory"))
        .otherwise(pl.lit("analog_auto"))
        .alias("subsector"),
    )
    df_curated_base = df_raw.with_columns(
        pl.when(pl.col("cost_of_revenue_usd_million") > 0)
        .then(
            (pl.col("inventory_usd_million") / pl.col("cost_of_revenue_usd_million") * 90.0).round(
                1
            )
        )
        .otherwise(None)
        .alias("doi_days")
    )
    analog_mask = pl.col("subsector") == "analog_auto"
    memory_mask = pl.col("subsector") == "memory"
    # 季度主体数充足性守卫：不足时季度级聚合与相态留空（见 MIN_INVENTORY_CONSTITUENTS）
    sufficient = pl.col("_n_constituents") >= MIN_INVENTORY_CONSTITUENTS

    q_agg = (
        df_curated_base.group_by("report_quarter")
        .agg(
            pl.col("inventory_usd_million").sum().alias("total_inventory_usd_million"),
            pl.col("cost_of_revenue_usd_million").sum().alias("total_cost_of_revenue_usd_million"),
            pl.col("doi_days").mean().round(1).alias("idm_equal_doi_days"),
            pl.col("inventory_usd_million").filter(analog_mask).sum().alias("analog_inv_sum"),
            pl.col("cost_of_revenue_usd_million")
            .filter(analog_mask)
            .sum()
            .alias("analog_cogs_sum"),
            pl.col("inventory_usd_million").filter(memory_mask).sum().alias("memory_inv_sum"),
            pl.col("cost_of_revenue_usd_million")
            .filter(memory_mask)
            .sum()
            .alias("memory_cogs_sum"),
            pl.len().alias("_n_constituents"),
        )
        .with_columns(
            pl.when(sufficient)
            .then(pl.col("idm_equal_doi_days"))
            .otherwise(None)
            .alias("idm_equal_doi_days"),
            pl.when(sufficient)
            .then(
                (
                    pl.col("total_inventory_usd_million")
                    / pl.col("total_cost_of_revenue_usd_million")
                    * 90.0
                ).round(1)
            )
            .otherwise(None)
            .alias("idm_weighted_doi_days"),
            pl.when(sufficient & (pl.col("analog_cogs_sum") > 0))
            .then((pl.col("analog_inv_sum") / pl.col("analog_cogs_sum") * 90.0).round(1))
            .otherwise(None)
            .alias("analog_weighted_doi_days"),
            pl.when(sufficient & (pl.col("memory_cogs_sum") > 0))
            .then((pl.col("memory_inv_sum") / pl.col("memory_cogs_sum") * 90.0).round(1))
            .otherwise(None)
            .alias("memory_weighted_doi_days"),
        )
        .with_columns(
            pl.col("idm_weighted_doi_days")
            .map_elements(determine_inventory_regime, return_dtype=pl.String)
            .alias("inventory_regime")
        )
        .drop(
            [
                "_n_constituents",
                "analog_inv_sum",
                "analog_cogs_sum",
                "memory_inv_sum",
                "memory_cogs_sum",
            ]
        )
    )

    return (
        df_curated_base.join(q_agg, on="report_quarter", how="left")
        .with_columns(
            pl.lit("days").alias("unit"),
            pl.lit(now_utc_iso()).alias("collected_at"),
        )
        .select(list(INVENTORY_CURATED_SCHEMA))
        .sort(["report_quarter", "symbol"])
    )


def _string_expr_from_available(df: pl.DataFrame, column: str) -> pl.Expr:
    if column not in df.columns:
        return pl.lit(None, dtype=pl.String)
    return pl.col(column).cast(pl.String)


def _numeric_expr_from_raw(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .cast(pl.String)
        .str.replace_all(r"[^\d.-]", "")
        .cast(pl.Float64, strict=False)
    )
