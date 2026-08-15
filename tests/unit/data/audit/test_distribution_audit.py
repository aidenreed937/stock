"""Curated 数据集数值分布与阶跃异动审计器单元测试。"""

from datetime import date
from pathlib import Path
import polars as pl
import pytest

from stock.data.audit.distribution_audit import CuratedDistributionAuditor, run_distribution_audit


def test_curated_distribution_auditor_clean_data(tmp_path: Path) -> None:
    """测试在完全正常的数据集上，审计器通过并输出统计量。"""
    # 构造 mock parquet 目录
    ds_dir = tmp_path / "tushare" / "market=CN" / "sw_daily" / "year=2026" / "month=08"
    ds_dir.mkdir(parents=True)

    df = pl.DataFrame({
        "symbol": ["801010.SI", "801080.SI", "801010.SI", "801080.SI"],
        "trade_date": [date(2026, 8, 11), date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 12)],
        "amount": [1.5e10, 5.0e10, 1.6e10, 5.2e10],
        "volume": [1e6, 2e6, 1.1e6, 2.1e6],
        "total_mv": [1e12, 5e12, 1.05e12, 5.1e12],
        "float_mv": [5e11, 2e12, 5.2e11, 2.05e12],
        "close": [1000.0, 2500.0, 1020.0, 2550.0],
    })
    df.write_parquet(ds_dir / "data.parquet")

    auditor = CuratedDistributionAuditor(base_dir=tmp_path)
    report = auditor.audit_dataset("sw_daily", data_source="tushare")

    assert report.passed is True
    assert report.total_rows == 4
    assert report.total_dates == 2
    assert "amount" in report.columns_summary
    assert report.columns_summary["amount"].step_jumps_count == 0
    assert report.columns_summary["amount"].negative_count == 0
    assert report.columns_summary["amount"].mean > 0

    fmt = auditor.format_report(report)
    assert "PASSED" in fmt
    assert "sw_daily" in fmt


def test_curated_distribution_auditor_detect_step_jump(tmp_path: Path) -> None:
    """测试审计器精准捕捉 10,000 倍单位阶跃异动。"""
    ds_dir = tmp_path / "tushare" / "market=CN" / "sw_daily" / "year=2026" / "month=08"
    ds_dir.mkdir(parents=True)

    # 8/11 为元单位 (3.25e10)，8/12 错为万元单位 (3.4e6，相当于 340 万)
    df = pl.DataFrame({
        "symbol": ["801010.SI", "801080.SI", "801010.SI", "801080.SI"],
        "trade_date": [date(2026, 8, 11), date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 12)],
        "amount": [1.5e10, 5.0e10, 1500.0, 5300.0],  # 8/12 发生了 ~10,000,000x 暴跌
        "volume": [1e6, 2e6, 1.1e6, 2.1e6],
        "total_mv": [1e12, 5e12, 1.05e12, 5.1e12],
        "float_mv": [5e11, 2e12, 5.2e11, 2.05e12],
        "close": [1000.0, 2500.0, 1020.0, 2550.0],
    })
    df.write_parquet(ds_dir / "data.parquet")

    auditor = CuratedDistributionAuditor(base_dir=tmp_path, max_step_ratio=10.0, min_step_ratio=0.1)
    report = auditor.audit_dataset("sw_daily", data_source="tushare")

    assert report.passed is False
    assert len(report.anomalies) > 0
    jump_anomalies = [a for a in report.anomalies if a.anomaly_type == "STEP_JUMP"]
    assert len(jump_anomalies) >= 1
    assert jump_anomalies[0].column == "amount"
    assert jump_anomalies[0].ratio is not None and jump_anomalies[0].ratio < 0.001


def test_curated_distribution_auditor_detect_negative_values(tmp_path: Path) -> None:
    """测试审计器捕捉非物理负值。"""
    ds_dir = tmp_path / "tushare" / "market=CN" / "daily_basic" / "year=2026" / "month=08"
    ds_dir.mkdir(parents=True)

    df = pl.DataFrame({
        "symbol": ["000001.SZ", "000002.SZ"],
        "trade_date": [date(2026, 8, 11), date(2026, 8, 11)],
        "total_mv": [-5000.0, 1e11],  # 负总市值
        "circ_mv": [1e10, 8e10],
        "turnover_rate": [1.5, 2.0],
    })
    df.write_parquet(ds_dir / "data.parquet")

    auditor = CuratedDistributionAuditor(base_dir=tmp_path)
    report = auditor.audit_dataset("daily_basic", data_source="tushare")

    assert report.passed is False
    neg_anomalies = [a for a in report.anomalies if a.anomaly_type == "NEGATIVE_VALUE"]
    assert len(neg_anomalies) == 1
    assert neg_anomalies[0].column == "total_mv"
