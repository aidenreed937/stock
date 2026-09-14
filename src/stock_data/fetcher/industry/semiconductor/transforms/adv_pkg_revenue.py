"""台积电官方先进封装与财务拆解 Curated 转换器 (AdvPkgRevenueTransform).

负责计算同比、环比（严格小数制），并生成结构化 Curated 事实表。
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from stock_data.fetcher.industry.semiconductor.models import TsmcAdvancedPackagingRevenueRecord
from stock_data.fetcher.industry.semiconductor.schemas import (
    TSMC_ADV_PKG_REVENUE_CURATED_SCHEMA,
    TSMC_ADV_PKG_REVENUE_RAW_SCHEMA,
)


def build_tsmc_adv_pkg_revenue_raw_frame(
    records: Sequence[TsmcAdvancedPackagingRevenueRecord],
) -> pl.DataFrame:
    """将台积电官方财务原始记录转为 RAW DataFrame。"""
    if not records:
        return pl.DataFrame(schema=TSMC_ADV_PKG_REVENUE_RAW_SCHEMA)

    data = [
        {
            "symbol": r.symbol,
            "report_quarter": r.report_quarter,
            "trade_date": r.trade_date,
            "release_date": r.release_date,
            "net_revenue_ntd_bn": r.net_revenue_ntd_bn,
            "net_revenue_usd_bn": r.net_revenue_usd_bn,
            "advanced_wafer_pct": r.advanced_wafer_pct,
            "hpc_platform_pct": r.hpc_platform_pct,
            "packaging_testing_others_pct": r.packaging_testing_others_pct,
            "data_status": r.data_status,
            "source": r.source,
            "source_url": r.source_url,
            "collected_at": r.collected_at,
            "raw_content_sha256": r.raw_content_sha256,
            "raw_snapshot_path": r.raw_snapshot_path,
        }
        for r in records
    ]
    df = pl.DataFrame(data)
    return df.cast(TSMC_ADV_PKG_REVENUE_RAW_SCHEMA)


def build_tsmc_adv_pkg_revenue_curated_frame(
    records: Sequence[TsmcAdvancedPackagingRevenueRecord],
) -> pl.DataFrame:
    """构建台积电官方先进封装与财务拆解 Curated 事实表。"""
    if not records:
        return pl.DataFrame(schema=TSMC_ADV_PKG_REVENUE_CURATED_SCHEMA)

    # 按 trade_date 升序排序
    sorted_records = sorted(records, key=lambda r: (r.symbol, r.trade_date))

    raw_df = build_tsmc_adv_pkg_revenue_raw_frame(sorted_records)

    # 使用 Polars 窗口计算 YoY (4 季度前) 与 QoQ (1 季度前)，小数制
    curated_df = (
        raw_df.sort(["symbol", "trade_date"])
        .with_columns(
            (
                (
                    pl.col("net_revenue_ntd_bn")
                    - pl.col("net_revenue_ntd_bn").shift(4).over("symbol")
                )
                / pl.col("net_revenue_ntd_bn").shift(4).over("symbol")
            )
            .round(4)
            .alias("revenue_yoy"),
            (
                (
                    pl.col("net_revenue_ntd_bn")
                    - pl.col("net_revenue_ntd_bn").shift(1).over("symbol")
                )
                / pl.col("net_revenue_ntd_bn").shift(1).over("symbol")
            )
            .round(4)
            .alias("revenue_qoq"),
            (pl.col("net_revenue_ntd_bn") * pl.col("packaging_testing_others_pct"))
            .round(2)
            .alias("packaging_testing_others_ntd_bn"),
            pl.lit("billion_ntd").alias("unit"),
        )
        .select(list(TSMC_ADV_PKG_REVENUE_CURATED_SCHEMA.keys()))
    )

    return curated_df.cast(TSMC_ADV_PKG_REVENUE_CURATED_SCHEMA)
