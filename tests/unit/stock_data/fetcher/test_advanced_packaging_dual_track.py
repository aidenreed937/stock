"""测试先进封装专项数据管道双轨物理分层隔离 (Dual-Track Separation).

方案 A（官方真实财报事实表）：tsmc_advanced_packaging_revenue
- 100% 官方已结账季度财报事实，零未来函数，data_status='actual'，禁止虚构片数。
方案 B（前瞻智库预测表）：tsmc_cowos_capacity_estimates
- 真实公开智库研报，标记 agency='TrendForce'，绑定 published_date，严禁 actual 状态。
"""

import hashlib
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_data.core.settings import data_settings
from stock_data.fetcher.industry.semiconductor.models import (
    CowosCapacityEstimateRecord,
    TsmcAdvancedPackagingRevenueRecord,
)
from stock_data.fetcher.industry.semiconductor.parsers.adv_pkg_revenue import (
    load_tsmc_adv_pkg_revenue_raw_csv,
)
from stock_data.fetcher.industry.semiconductor.parsers.cowos_estimates import (
    load_cowos_capacity_estimates_raw_csv,
)
from stock_data.fetcher.industry.semiconductor.transforms import (
    build_cowos_capacity_estimates_curated_frame,
    build_tsmc_adv_pkg_revenue_curated_frame,
)
from stock_data.fetcher.industry.task_executor import execute_single_industry_task
from stock_data.governance.quality.gate import QualityGate


def test_tsmc_adv_pkg_revenue_parser_and_validation(tmp_path: Path) -> None:
    """验证方案 A 解析器：必须为 actual，且校验 SHA256。"""
    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 dummy TSMC management report")
    pdf_sha = hashlib.sha256(dummy_pdf.read_bytes()).hexdigest()

    csv_path = tmp_path / "tsmc_adv_pkg_revenue_raw.csv"
    lines = [
        "symbol,report_quarter,trade_date,release_date,net_revenue_ntd_bn,net_revenue_usd_bn,advanced_wafer_pct,hpc_platform_pct,packaging_testing_others_pct,data_status,source,source_url,collected_at,raw_content_sha256,raw_snapshot_path",
        f"2330.TW,2024Q4,2024-12-31,2025-01-16,868.46,26.88,0.74,0.53,0.08,actual,TSMC,https://tsmc.com,2026-09-10T00:00:00Z,{pdf_sha},{dummy_pdf.name}",
    ]
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    records = load_tsmc_adv_pkg_revenue_raw_csv(csv_path, project_root=tmp_path, verify_hash=True)
    assert len(records) == 1
    rec = records[0]
    assert rec.symbol == "2330.TW"
    assert rec.report_quarter == "2024Q4"
    assert rec.net_revenue_ntd_bn == 868.46
    assert rec.packaging_testing_others_pct == 0.08
    assert rec.packaging_testing_others_ntd_bn == round(868.46 * 0.08, 2)
    assert rec.data_status == "actual"


def test_tsmc_adv_pkg_revenue_rejects_non_actual(tmp_path: Path) -> None:
    """方案 A 严禁混入 forecast 或其他非 actual 记录。"""
    csv_path = tmp_path / "tsmc_adv_pkg_revenue_raw.csv"
    lines = [
        "symbol,report_quarter,trade_date,release_date,net_revenue_ntd_bn,net_revenue_usd_bn,advanced_wafer_pct,hpc_platform_pct,packaging_testing_others_pct,data_status,source,source_url,collected_at,raw_content_sha256,raw_snapshot_path",
        "2330.TW,2025Q4,2025-12-31,2026-01-15,1000.00,30.00,0.80,0.60,0.10,forecast,TSMC,https://tsmc.com,2026-09-10T00:00:00Z,,",
    ]
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="data_status 必须为 actual"):
        load_tsmc_adv_pkg_revenue_raw_csv(csv_path, project_root=tmp_path, verify_hash=False)


def test_cowos_estimates_parser_and_temporal_isolation(tmp_path: Path) -> None:
    """验证方案 B 解析器：严格隔离时态，严禁 actual。"""
    src_file = tmp_path / "trendforce.txt"
    src_file.write_text("TrendForce report content", encoding="utf-8")
    sha = hashlib.sha256(src_file.read_bytes()).hexdigest()

    csv_path = tmp_path / "cowos_capacity_estimates_raw.csv"
    lines = [
        "symbol,report_quarter,trade_date,agency,published_date,monthly_capacity_kwpm,lead_time_months,data_status,source,source_url,collected_at,raw_content_sha256,raw_snapshot_path",
        f"2330.TW,2024Q2,2024-06-30,TrendForce,2024-07-16,24.0,7.5,estimate,TrendForce,https://tf.com,2026-09-10T00:00:00Z,{sha},{src_file.name}",
        f"2330.TW,2025Q4,2025-12-31,TrendForce,2024-07-16,75.0,6.0,forecast,TrendForce,https://tf.com,2026-09-10T00:00:00Z,{sha},{src_file.name}",
    ]
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    records = load_cowos_capacity_estimates_raw_csv(
        csv_path, project_root=tmp_path, verify_hash=True
    )
    assert len(records) == 2
    assert records[0].data_status == "estimate"
    assert records[1].data_status == "forecast"


def test_cowos_estimates_rejects_actual_status(tmp_path: Path) -> None:
    """方案 B 绝对禁止标记为 actual。"""
    csv_path = tmp_path / "cowos_capacity_estimates_raw.csv"
    lines = [
        "symbol,report_quarter,trade_date,agency,published_date,monthly_capacity_kwpm,lead_time_months,data_status,source,source_url,collected_at,raw_content_sha256,raw_snapshot_path",
        "2330.TW,2024Q4,2024-12-31,TrendForce,2024-07-16,38.0,7.0,actual,TrendForce,https://tf.com,2026-09-10T00:00:00Z,,",
    ]
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="智库测算表绝对禁止标记为 actual"):
        load_cowos_capacity_estimates_raw_csv(csv_path, project_root=tmp_path, verify_hash=False)


def test_cowos_estimates_rejects_future_not_forecast(tmp_path: Path) -> None:
    """若 trade_date 晚于 published_date，必须强制为 forecast。"""
    csv_path = tmp_path / "cowos_capacity_estimates_raw.csv"
    lines = [
        "symbol,report_quarter,trade_date,agency,published_date,monthly_capacity_kwpm,lead_time_months,data_status,source,source_url,collected_at,raw_content_sha256,raw_snapshot_path",
        "2330.TW,2025Q4,2025-12-31,TrendForce,2024-07-16,75.0,6.0,estimate,TrendForce,https://tf.com,2026-09-10T00:00:00Z,,",
    ]
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="必须为 forecast"):
        load_cowos_capacity_estimates_raw_csv(csv_path, project_root=tmp_path, verify_hash=False)


def test_adv_pkg_revenue_transform_growth_rates() -> None:
    """测试方案 A 转换层：YoY 和 QoQ 为小数制。"""
    records = [
        TsmcAdvancedPackagingRevenueRecord(
            symbol="2330.TW",
            report_quarter="2023Q4",
            trade_date=date(2023, 12, 31),
            release_date=date(2024, 1, 18),
            net_revenue_ntd_bn=625.53,
            packaging_testing_others_pct=0.07,
        ),
        TsmcAdvancedPackagingRevenueRecord(
            symbol="2330.TW",
            report_quarter="2024Q1",
            trade_date=date(2024, 3, 31),
            release_date=date(2024, 4, 18),
            net_revenue_ntd_bn=592.64,
            packaging_testing_others_pct=0.08,
        ),
        TsmcAdvancedPackagingRevenueRecord(
            symbol="2330.TW",
            report_quarter="2024Q4",
            trade_date=date(2024, 12, 31),
            release_date=date(2025, 1, 16),
            net_revenue_ntd_bn=868.46,
            packaging_testing_others_pct=0.08,
        ),
    ]
    curated = build_tsmc_adv_pkg_revenue_curated_frame(records)
    assert curated.height == 3
    row_2024q4 = curated.filter(pl.col("report_quarter") == "2024Q4").to_dicts()[0]
    assert row_2024q4["revenue_qoq"] is not None
    assert abs(row_2024q4["revenue_qoq"]) < 2.0


def test_cowos_estimates_transform_and_regimes() -> None:
    """测试方案 B 转换层：相态判定与容量增速。"""
    records = [
        CowosCapacityEstimateRecord(
            symbol="2330.TW",
            report_quarter="2023Q4",
            trade_date=date(2023, 12, 31),
            agency="TrendForce",
            published_date=date(2024, 7, 16),
            monthly_capacity_kwpm=13.5,
            lead_time_months=8.0,
            data_status="estimate",
        ),
        CowosCapacityEstimateRecord(
            symbol="2330.TW",
            report_quarter="2024Q4",
            trade_date=date(2024, 12, 31),
            agency="TrendForce",
            published_date=date(2024, 7, 16),
            monthly_capacity_kwpm=38.0,
            lead_time_months=7.0,
            data_status="forecast",
        ),
    ]
    curated = build_cowos_capacity_estimates_curated_frame(records)
    assert curated.height == 2
    row_2024q4 = curated.filter(pl.col("report_quarter") == "2024Q4").to_dicts()[0]
    assert row_2024q4["capacity_yoy"] is not None
    assert row_2024q4["bottleneck_regime"] == "severe_bottleneck_expansion"


def test_dual_track_physical_separation_in_disk() -> None:
    """验证方案 A 与方案 B 物理落盘与质量门禁。"""
    res_a = execute_single_industry_task("tsmc_advanced_packaging_revenue", force_refresh=True)
    assert int(res_a) >= 10
    assert res_a.status in ("SUCCESS", "NO_CHANGE")

    res_b = execute_single_industry_task("tsmc_cowos_capacity_estimates", force_refresh=True)
    assert int(res_b) >= 5
    assert res_b.status in ("SUCCESS", "NO_CHANGE")

    assert data_settings.curated_root is not None
    curated_dir = Path(data_settings.curated_root)
    file_a = (
        curated_dir
        / "industry"
        / "semiconductor"
        / "capacity"
        / "tsmc_advanced_packaging_revenue.parquet"
    )
    if not file_a.exists():
        file_a = curated_dir / "industry" / "tsmc_advanced_packaging_revenue.parquet"
    file_b = (
        curated_dir
        / "industry"
        / "semiconductor"
        / "capacity"
        / "tsmc_cowos_capacity_estimates.parquet"
    )
    if not file_b.exists():
        file_b = curated_dir / "industry" / "tsmc_cowos_capacity_estimates.parquet"

    assert file_a.exists(), f"方案 A 黄金表缺失: {file_a}"
    assert file_b.exists(), f"方案 B 预测表缺失: {file_b}"

    df_a = pl.read_parquet(file_a)
    assert set(df_a["data_status"].unique().to_list()) == {"actual"}
    assert "monthly_capacity_kwpm" not in df_a.columns

    df_b = pl.read_parquet(file_b)
    assert "actual" not in df_b["data_status"].unique().to_list()
    assert "monthly_capacity_kwpm" in df_b.columns
    assert "published_date" in df_b.columns

    gate = QualityGate(str(curated_dir))
    assert gate.assert_schema_contracts([file_a, file_b]) is True
    assert gate.assert_no_duplicate_keys([file_a, file_b]) is True
    assert gate.assert_tsmc_adv_pkg_revenue_quality([file_a]) is True
    assert gate.assert_cowos_capacity_estimates_quality([file_b]) is True
    assert gate.assert_industry_growth_rate_sanity([file_a, file_b]) is True
