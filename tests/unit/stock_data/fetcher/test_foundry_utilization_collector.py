"""全球晶圆代工产能利用率 2-Tier ETL 处理器测试。"""

from datetime import date

import polars as pl

from stock_data.fetcher.industry.semiconductor.schemas import FOUNDRY_RAW_SCHEMA
from stock_data.fetcher.industry.semiconductor.transforms import (
    build_foundry_utilization_frame,
)


def test_foundry_utilization_2tier_etl() -> None:
    df_raw = pl.DataFrame(
        [
            {
                "report_quarter": "2023Q1",
                "trade_date": date(2023, 3, 31),
                "tsmc_utilization_raw": "70.0%",
                "smic_utilization_raw": "68.0%",
                "smic_monthly_capacity_raw": "780.0千片",
                "smic_wafer_shipment_raw": "1,590.0千片",
                "source": "SMIC_TSMC_IR",
                "source_url": "https://www.smics.com/test",
                "release_date": date(2023, 5, 12),
                "data_status": "actual",
                "collected_at": "2023-05-12T00:00:00Z",
                "raw_content_sha256": "sha-2023q1",
                "raw_snapshot_path": "semiconductors/foundry/2023q1.html.gz",
            },
            {
                "report_quarter": "2024Q3",
                "trade_date": date(2024, 9, 30),
                "tsmc_utilization_raw": "95.0%",
                "smic_utilization_raw": "85.2%",
                "smic_monthly_capacity_raw": "884.25千片",
                "smic_wafer_shipment_raw": "2,122.3千片",
                "source": "SMIC_TSMC_IR",
                "source_url": "https://www.smics.com/test",
                "release_date": date(2024, 11, 7),
                "data_status": "actual",
                "collected_at": "2024-11-07T00:00:00Z",
                "raw_content_sha256": "sha-2024q3",
                "raw_snapshot_path": "semiconductors/foundry/2024q3.html.gz",
            },
        ],
        schema=FOUNDRY_RAW_SCHEMA,
    )
    df = build_foundry_utilization_frame(df_raw)

    assert isinstance(df, pl.DataFrame)
    assert len(df) == 2
    assert "tsmc_utilization_pct" in df.columns
    assert "smic_utilization_pct" in df.columns
    assert "tsmc_utilization_raw" not in df.columns
    assert "smic_utilization_raw" not in df.columns
    assert "foundry_weighted_utilization_pct" in df.columns
    assert "utilization_regime" in df.columns
    assert "raw_content_sha256" not in df.columns
    assert "raw_snapshot_path" not in df.columns

    # 验证利用率在合理物理区间 [50%, 110%]
    u_vals = df["foundry_weighted_utilization_pct"]
    assert u_vals.min() >= 60.0
    assert u_vals.max() <= 110.0

    # 验证 2023Q1 处于 slump (萧条)
    row_2023q1 = df.filter(pl.col("report_quarter") == "2023Q1")
    assert row_2023q1["utilization_regime"][0] == "slump"


def test_foundry_proxy_is_not_fabricated_when_tsmc_utilization_is_unavailable() -> None:
    raw = pl.DataFrame(
        [
            {
                "report_quarter": "2026-Q2",
                "trade_date": date(2026, 6, 30),
                "tsmc_utilization_raw": None,
                "tsmc_wafer_shipments_12in_kpcs_raw": "4,336 kpcs 12 inch-equiv.",
                "tsmc_capacity_12in_kpcs_raw": None,
                "tsmc_utilization_status": "unavailable",
                "smic_utilization_raw": "93.7%",
                "smic_monthly_capacity_raw": "1,096,500 片",
                "smic_wafer_shipment_raw": "2,869,495",
                "smic_utilization_status": "reported",
                "source": "TSMC_IR/SMIC_IR",
                "source_url": "tsmc;smic",
                "release_date": date(2026, 8, 13),
                "data_status": "actual",
                "collected_at": "2026-08-13T00:00:00Z",
                "raw_content_sha256": "",
                "raw_snapshot_path": "",
                "tsmc_source_url": "https://investor.tsmc.com/report.pdf",
                "tsmc_release_date": date(2026, 7, 16),
                "tsmc_raw_content_sha256": "tsmc-sha",
                "tsmc_raw_snapshot_path": "tsmc/report.pdf",
                "smic_source_url": "https://www.smics.com/report",
                "smic_release_date": date(2026, 8, 13),
                "smic_raw_content_sha256": "smic-sha",
                "smic_raw_snapshot_path": "smic/report.pdf",
            }
        ],
        schema=FOUNDRY_RAW_SCHEMA,
    )

    curated = build_foundry_utilization_frame(raw)

    assert curated["tsmc_wafer_shipments_12in_kpcs"][0] == 4336.0
    assert curated["smic_monthly_capacity_8inch_kw"][0] == 1096.5
    assert curated["smic_wafer_shipment_kw"][0] == 2869.495
    assert curated["proxy_status"][0] == "partial"
    assert curated["foundry_proxy_utilization_pct"][0] is None
    assert curated["utilization_regime"][0] is None


def test_foundry_proxy_uses_shipment_area_weighting_when_both_shipments_available() -> None:
    """两家出货量齐备时，代理利用率按晶圆出货面积体量加权（12 寸=2.25×8 寸）。"""
    raw = pl.DataFrame(
        [
            {
                "report_quarter": "2026Q2",
                "trade_date": date(2026, 6, 30),
                "tsmc_utilization_raw": "98.0%",
                "tsmc_wafer_shipments_12in_kpcs_raw": "4,336 kpcs 12 inch-equiv.",
                "tsmc_capacity_12in_kpcs_raw": None,
                "tsmc_utilization_status": "legacy_baseline",
                "smic_utilization_raw": "93.7%",
                "smic_monthly_capacity_raw": "1,096,500 片",
                "smic_wafer_shipment_raw": "2,869,495",
                "smic_utilization_status": "reported",
                "source": "TSMC_IR/SMIC_IR",
                "source_url": "tsmc;smic",
                "release_date": date(2026, 8, 13),
                "data_status": "actual",
                "collected_at": "2026-08-13T00:00:00Z",
                "raw_content_sha256": "",
                "raw_snapshot_path": "",
                "tsmc_source_url": "https://investor.tsmc.com/report.pdf",
                "tsmc_release_date": date(2026, 7, 16),
                "tsmc_raw_content_sha256": "tsmc-sha",
                "tsmc_raw_snapshot_path": "tsmc/report.pdf",
                "smic_source_url": "https://www.smics.com/report",
                "smic_release_date": date(2026, 8, 13),
                "smic_raw_content_sha256": "smic-sha",
                "smic_raw_snapshot_path": "smic/report.pdf",
            }
        ],
        schema=FOUNDRY_RAW_SCHEMA,
    )

    curated = build_foundry_utilization_frame(raw)

    assert curated["proxy_method"][0] == "shipment_weighted_mean"
    assert curated["tsmc_utilization_status"][0] == "legacy_baseline"
    # (98.0 × 4336×2.25 + 93.7 × 2869.495) / (4336×2.25 + 2869.495) = 97.02
    assert curated["foundry_proxy_utilization_pct"][0] == 97.02
    assert curated["utilization_regime"][0] == "tight_overheated"
