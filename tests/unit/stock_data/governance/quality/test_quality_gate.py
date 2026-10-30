"""QualityGate 单元测试。"""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from stock_core.exceptions import DataValidationError
from stock_data.governance.quality.gate import QualityGate, run_quality_gate


def test_quality_gate_on_valid_data(tmp_path: Path) -> None:
    now_utc = datetime.now(UTC)
    target_dir = tmp_path / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=08"
    target_dir.mkdir(parents=True, exist_ok=True)

    valid_df = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "trade_date": [date(2026, 8, 1)],
            "open": [10.0],
            "high": [11.0],
            "low": [9.5],
            "close": [10.5],
            "volume": [1000.0],
            "amount": [10500.0],
            "data_source": ["tushare"],
            "source_endpoint": ["stock_daily_bar"],
            "market": ["CN"],
            "exchange": ["SZSE"],
            "currency": ["CNY"],
            "adjustment": ["raw"],
            "schema_version": ["v2"],
            "updated_at": [now_utc],
        }
    )
    valid_df.write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    results = gate.validate_all()
    assert all(results.values())
    assert run_quality_gate(tmp_path)


def test_quality_gate_allows_percent_point_growth_rates(tmp_path: Path) -> None:
    target = tmp_path / "industry" / "chemical_monthly_survey.parquet"
    target.parent.mkdir(parents=True)
    pl.DataFrame(
        {
            "report_month": ["2026-07", "2026-08"],
            "product_name": ["钛白粉", "钛白粉"],
            "symbol": ["TiO2", "TiO2"],
            "inventory_mom_pct": [23.26, 0.34],
            "inventory_yoy_pct": [-22.01, None],
        }
    ).write_parquet(target)

    gate = QualityGate(tmp_path)

    assert gate.assert_industry_growth_rate_sanity(gate._active_parquet_files())


def test_quality_gate_fails_on_unit_mismatch(tmp_path: Path) -> None:
    now_utc = datetime.now(UTC)
    target_dir = tmp_path / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=08"
    target_dir.mkdir(parents=True, exist_ok=True)

    bad_df = pl.DataFrame(
        {
            "symbol": ["000001.SZ"] * 12,
            "trade_date": [date(2026, 8, 1)] * 12,
            "open": [10.0] * 12,
            "high": [11.0] * 12,
            "low": [9.5] * 12,
            "close": [10.5] * 12,
            "volume": [10.0] * 12,
            "amount": [10500.0] * 12,
            "data_source": ["tushare"] * 12,
            "source_endpoint": ["stock_daily_bar"] * 12,
            "market": ["CN"] * 12,
            "exchange": ["SZSE"] * 12,
            "currency": ["CNY"] * 12,
            "adjustment": ["raw"] * 12,
            "schema_version": ["v2"] * 12,
            "updated_at": [now_utc] * 12,
        }
    )
    bad_df.write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    assert not gate.assert_stock_daily_bar_units(gate._active_parquet_files())
    assert not run_quality_gate(tmp_path)


def test_quality_gate_fails_on_index_bar_missing_ohlc(tmp_path: Path) -> None:
    now_utc = datetime.now(UTC)
    target_dir = tmp_path / "tushare" / "market=CN" / "index_daily_bar" / "year=2026" / "month=08"
    target_dir.mkdir(parents=True, exist_ok=True)

    bad_df = pl.DataFrame(
        {
            "symbol": ["000300.SH"],
            "trade_date": [date(2026, 8, 1)],
            "open": [4000.0],
            "close": [4010.0],
            "volume": [1000.0],
            "amount": [4010000.0],
            "data_source": ["tushare"],
            "source_endpoint": ["index_daily_bar"],
            "market": ["CN"],
            "exchange": ["SSE"],
            "currency": ["CNY"],
            "adjustment": ["raw"],
            "schema_version": ["v2"],
            "updated_at": [now_utc],
        }
    )
    bad_df.write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    assert not gate.assert_schema_contracts(gate._active_parquet_files())


def test_quality_gate_fails_on_registered_date_and_numeric_schema_drift(tmp_path: Path) -> None:
    target_dir = tmp_path / "tushare" / "market=CN" / "cn_schedule"
    target_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "publish_date": ["20260814"],
            "title": ["经济数据"],
            "schema_version": ["v2"],
        }
    ).write_parquet(target_dir / "schedule.parquet")

    gate = QualityGate(tmp_path)
    assert not gate.assert_schema_contracts(gate._active_parquet_files())

    numeric_root = tmp_path / "numeric"
    target_dir = numeric_root / "yfinance" / "market=US" / "index_valuation"
    target_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "symbol": ["SPY"],
            "trade_date": [date(2026, 8, 14)],
            "forward_pe": ["20.0"],
        }
    ).write_parquet(target_dir / "data.parquet")

    numeric_gate = QualityGate(numeric_root)
    assert not numeric_gate.assert_schema_contracts(numeric_gate._active_parquet_files())


def test_quality_gate_allows_optional_cb_delist_date_to_be_missing(tmp_path: Path) -> None:
    target_dir = tmp_path / "tushare" / "market=CN" / "cb_basic"
    target_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "symbol": ["110001.SH"],
            "bond_short_name": ["测试转债"],
            "stk_code": ["600000.SH"],
            "list_date": [date(2026, 1, 1)],
            "exchange": ["SSE"],
        }
    ).write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    assert gate.assert_domain_input_quality(gate._active_parquet_files())


def test_quality_gate_checks_adjustment_for_fund_daily(tmp_path: Path) -> None:
    now_utc = datetime.now(UTC)
    target_dir = tmp_path / "tushare" / "market=CN" / "fund_daily" / "year=2026" / "month=08"
    target_dir.mkdir(parents=True, exist_ok=True)

    mixed_df = pl.DataFrame(
        {
            "symbol": ["510300.SH", "510500.SH"],
            "trade_date": [date(2026, 8, 1), date(2026, 8, 1)],
            "open": [4.0, 5.0],
            "high": [4.1, 5.1],
            "low": [3.9, 4.9],
            "close": [4.05, 5.05],
            "volume": [1000.0, 1000.0],
            "amount": [4050.0, 5050.0],
            "data_source": ["tushare", "tushare"],
            "source_endpoint": ["fund_daily", "fund_daily"],
            "market": ["CN", "CN"],
            "exchange": ["SSE", "SSE"],
            "currency": ["CNY", "CNY"],
            "adjustment": ["raw", "hfq"],
            "schema_version": ["v2", "v2"],
            "updated_at": [now_utc, now_utc],
        }
    )
    mixed_df.write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    assert not gate.assert_no_mixed_adjustment(gate._active_parquet_files())


def test_quality_gate_fails_on_duplicate_keys(tmp_path: Path) -> None:
    now_utc = datetime.now(UTC)
    target_dir = tmp_path / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=08"
    target_dir.mkdir(parents=True, exist_ok=True)

    dup_df = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ"],
            "trade_date": [date(2026, 8, 1), date(2026, 8, 1)],
            "open": [10.0, 10.0],
            "high": [11.0, 11.0],
            "low": [9.5, 9.5],
            "close": [10.5, 10.5],
            "volume": [1000.0, 1000.0],
            "amount": [10500.0, 10500.0],
            "data_source": ["tushare", "tushare"],
            "source_endpoint": ["stock_daily_bar", "stock_daily_bar"],
            "market": ["CN", "CN"],
            "exchange": ["SZSE", "SZSE"],
            "currency": ["CNY", "CNY"],
            "adjustment": ["raw", "raw"],
            "schema_version": ["v2", "v2"],
            "updated_at": [now_utc, now_utc],
        }
    )
    dup_df.write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    assert not gate.assert_no_duplicate_keys(gate._active_parquet_files())
    with pytest.raises(DataValidationError, match="质量门禁检测失败"):
        gate.validate_all()


def test_quality_gate_uses_registered_event_keys(tmp_path: Path) -> None:
    target_dir = tmp_path / "tushare" / "market=CN" / "cn_schedule"
    target_dir.mkdir(parents=True, exist_ok=True)
    valid_df = pl.DataFrame(
        {
            "market": ["CN", "CN"],
            "month": ["202611", "202611"],
            "publish_date": ["20261109", "20261116"],
            "title": ["居民消费价格指数月度报告", "商品住宅销售价格指数月度报告"],
        }
    )
    path = target_dir / "data.parquet"
    valid_df.write_parquet(path)

    gate = QualityGate(tmp_path)
    assert gate.assert_no_duplicate_keys(gate._active_parquet_files())

    pl.concat([valid_df, valid_df.head(1)]).write_parquet(path)
    assert not gate.assert_no_duplicate_keys(gate._active_parquet_files())


def test_quality_gate_checks_domain_mart_date_keys_and_finite_values(tmp_path: Path) -> None:
    mart_dir = tmp_path / "mart"
    mart_dir.mkdir(parents=True)
    valid = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 1)],
            "cb_price_median": [108.0],
            "cb_valid_count": [100],
        }
    )
    valid.write_parquet(mart_dir / "convertible_bond_daily.parquet")

    gate = QualityGate(tmp_path)
    assert gate.assert_domain_mart_quality(gate._active_parquet_files())

    bad = valid.with_columns(pl.lit(float("inf")).alias("cb_price_median"))
    bad.write_parquet(mart_dir / "convertible_bond_daily.parquet")
    assert not gate.assert_domain_mart_quality(gate._active_parquet_files())


def test_quality_gate_checks_analysis_mart_keys(tmp_path: Path) -> None:
    mart_dir = tmp_path / "mart"
    mart_dir.mkdir(parents=True)
    pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 1)],
            "industry_code": ["801001.SI"],
            "close": [100.0],
        }
    ).write_parquet(mart_dir / "industry_daily.parquet")
    pl.DataFrame(
        {
            "as_of_date": [date(2026, 8, 1)],
            "industry_code": ["801001.SI"],
            "return_20d": [1.0],
        }
    ).write_parquet(mart_dir / "industry_panel_daily.parquet")
    pl.DataFrame(
        {
            "as_of_date": [date(2026, 8, 1)],
            "fact_id": ["metric.technical.return_20d"],
            "value_float": [1.0],
        }
    ).write_parquet(mart_dir / "market_temperature_derived_facts.parquet")

    gate = QualityGate(tmp_path)
    assert gate.assert_domain_mart_quality(gate._active_parquet_files())

    pl.DataFrame(
        {
            "as_of_date": [date(2026, 8, 1), date(2026, 8, 1)],
            "fact_id": ["duplicate", "duplicate"],
            "value_float": [1.0, 2.0],
        }
    ).write_parquet(mart_dir / "market_temperature_derived_facts.parquet")
    assert not gate.assert_domain_mart_quality(gate._active_parquet_files())


def test_quality_gate_checks_smart_money_mart_keys(tmp_path: Path) -> None:
    mart_dir = tmp_path / "mart"
    mart_dir.mkdir(parents=True)
    valid = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 28)],
            "insider_score": [79.8],
            "block_score": [0.0],
            "nat_score": [31.3],
            "smart_money_score": [37.0],
        }
    )
    valid.write_parquet(mart_dir / "smart_money_daily.parquet")

    gate = QualityGate(tmp_path)
    assert gate.assert_domain_mart_quality(gate._active_parquet_files())

    invalid = pl.concat([valid, valid])
    invalid.write_parquet(mart_dir / "smart_money_daily.parquet")
    assert not gate.assert_domain_mart_quality(gate._active_parquet_files())


def test_quality_gate_checks_domain_input_contracts(tmp_path: Path) -> None:
    target_dir = tmp_path / "tushare" / "market=CN" / "block_trade"
    target_dir.mkdir(parents=True)
    valid = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "trade_date": [date(2026, 8, 1)],
            "price": [10.0],
            "volume": [100.0],
            "amount": [1000.0],
        }
    )
    valid.write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    assert gate.assert_domain_input_quality(gate._active_parquet_files())

    invalid = valid.with_columns(pl.lit(-1.0).alias("amount"))
    invalid.write_parquet(target_dir / "data.parquet")
    assert not gate.assert_domain_input_quality(gate._active_parquet_files())


def test_quality_gate_checks_foundry_units_and_proxy_status(tmp_path: Path) -> None:
    target_dir = tmp_path / "industry"
    target_dir.mkdir(parents=True)
    valid = pl.DataFrame(
        {
            "report_quarter": ["2026Q2"],
            "trade_date": [date(2026, 6, 30)],
            "tsmc_utilization_pct": [None],
            "tsmc_wafer_shipments_12in_kpcs": [4336.0],
            "tsmc_capacity_12in_kpcs": [None],
            "tsmc_utilization_status": ["unavailable"],
            "smic_utilization_pct": [93.7],
            "smic_monthly_capacity_8inch_kw": [1096.5],
            "smic_wafer_shipment_kw": [2869.495],
            "smic_utilization_status": ["reported"],
            "source": ["TSMC_IR/SMIC_IR"],
            "source_url": ["tsmc;smic"],
            "release_date": [date(2026, 8, 13)],
            "data_status": ["actual"],
            "collected_at": ["2026-08-13T00:00:00Z"],
            "tsmc_source_url": ["https://investor.tsmc.com/report.pdf"],
            "tsmc_release_date": [date(2026, 7, 16)],
            "smic_source_url": ["https://www.smics.com/report"],
            "smic_release_date": [date(2026, 8, 13)],
            "foundry_proxy_utilization_pct": [None],
            "foundry_weighted_utilization_pct": [None],
            "proxy_method": ["none"],
            "proxy_status": ["partial"],
            "utilization_regime": [None],
        }
    ).with_columns(
        pl.col("tsmc_utilization_pct").cast(pl.Float64),
        pl.col("tsmc_capacity_12in_kpcs").cast(pl.Float64),
        pl.col("foundry_proxy_utilization_pct").cast(pl.Float64),
        pl.col("foundry_weighted_utilization_pct").cast(pl.Float64),
    )
    path = target_dir / "foundry_capacity_utilization.parquet"
    valid.write_parquet(path)

    gate = QualityGate(tmp_path)
    files = gate._active_parquet_files()
    assert gate.assert_schema_contracts(files)
    assert gate.assert_foundry_quality(files)
    assert gate.assert_no_duplicate_keys(files)

    invalid = valid.with_columns(pl.lit(111.0).alias("tsmc_utilization_pct")).with_columns(
        pl.lit("reported").alias("tsmc_utilization_status")
    )
    invalid.write_parquet(path)
    assert not gate.assert_foundry_quality(files)


def test_quality_gate_checks_repurchase_vol_alias(tmp_path: Path) -> None:
    target_dir = tmp_path / "tushare" / "market=CN" / "repurchase" / "year=2020" / "month=04"
    target_dir.mkdir(parents=True)
    valid = pl.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "ann_date": [date(2020, 4, 1)],
            "proc": ["预案"],
            "vol": [100.0],
            "amount": [1000.0],
        }
    )
    valid.write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    assert gate.assert_domain_input_quality(gate._active_parquet_files())

    invalid = valid.with_columns(pl.lit(-1.0).alias("vol"))
    invalid.write_parquet(target_dir / "data.parquet")
    assert not gate.assert_domain_input_quality(gate._active_parquet_files())


def test_quality_gate_checks_semiconductor_inventory_derivations(tmp_path: Path) -> None:
    target_dir = tmp_path / "industry"
    target_dir.mkdir(parents=True)
    valid = pl.DataFrame(
        {
            "symbol": ["TXN", "ADI", "STM", "NXPI"],
            "report_quarter": ["2026Q1"] * 4,
            "trade_date": [date(2026, 3, 31)] * 4,
            "inventory_usd_million": [3910.0, 1767.1, 3173.0, 2450.0],
            "cost_of_revenue_usd_million": [1840.0, 1115.3, 2050.0, 1430.0],
            "release_date": [
                date(2026, 4, 24),
                date(2026, 2, 18),
                date(2026, 4, 15),
                date(2026, 4, 28),
            ],
            "unit": ["days"] * 4,
            "data_status": ["actual"] * 4,
            "doi_days": [191.2, 142.6, 139.3, 154.2],
            "total_inventory_usd_million": [11300.1] * 4,
            "total_cost_of_revenue_usd_million": [6435.3] * 4,
            "idm_equal_doi_days": [156.8] * 4,
            "idm_weighted_doi_days": [158.0] * 4,
            "inventory_regime": ["high_overstocked"] * 4,
        }
    )
    path = target_dir / "semiconductor_inventory_days.parquet"
    valid.write_parquet(path)

    gate = QualityGate(tmp_path)
    files = gate._active_parquet_files()
    assert gate.assert_inventory_quality(files)

    invalid = valid.with_columns(pl.lit(180.0).alias("doi_days"))
    invalid.write_parquet(path)
    assert not gate.assert_inventory_quality(files)


def test_quality_gate_checks_under_covered_inventory_quarter(tmp_path: Path) -> None:
    """季度主体数不足时季度级聚合力应为空；若带值则门禁必须拦截。"""
    target_dir = tmp_path / "industry"
    target_dir.mkdir(parents=True)
    under = pl.DataFrame(
        {
            "symbol": ["ADI"],
            "report_quarter": ["2026Q3"],
            "trade_date": [date(2026, 9, 30)],
            "inventory_usd_million": [1767.1],
            "cost_of_revenue_usd_million": [1115.3],
            "release_date": [date(2026, 8, 19)],
            "unit": ["days"],
            "data_status": ["actual"],
            "doi_days": [142.6],
            "total_inventory_usd_million": [1767.1],
            "total_cost_of_revenue_usd_million": [1115.3],
            "idm_equal_doi_days": pl.Series([None], dtype=pl.Float64),
            "idm_weighted_doi_days": pl.Series([None], dtype=pl.Float64),
            "inventory_regime": pl.Series([None], dtype=pl.String),
        }
    )
    path = target_dir / "semiconductor_inventory_days.parquet"
    under.write_parquet(path)

    gate = QualityGate(tmp_path)
    files = gate._active_parquet_files()
    # 单家主体、聚合留空 → 合法
    assert gate.assert_inventory_quality(files)

    # 单家主体却输出季度级聚合值与相态 → 必须拦截
    leaked = under.with_columns(
        pl.lit(142.6).alias("idm_equal_doi_days"),
        pl.lit(142.6).alias("idm_weighted_doi_days"),
        pl.lit("elevated_destocking").alias("inventory_regime"),
    )
    leaked.write_parquet(path)
    assert not gate.assert_inventory_quality(files)


def test_quality_gate_fails_on_mixed_adjustment(tmp_path: Path) -> None:
    now_utc = datetime.now(UTC)
    target_dir = tmp_path / "tushare" / "market=CN" / "stock_daily_bar" / "year=2026" / "month=08"
    target_dir.mkdir(parents=True, exist_ok=True)

    mixed_df = pl.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ"],
            "trade_date": [date(2026, 8, 1), date(2026, 8, 1)],
            "open": [10.0, 10.0],
            "high": [11.0, 11.0],
            "low": [9.5, 9.5],
            "close": [10.5, 10.5],
            "volume": [1000.0, 1000.0],
            "amount": [10500.0, 10500.0],
            "data_source": ["tushare", "tushare"],
            "source_endpoint": ["stock_daily_bar", "stock_daily_bar"],
            "market": ["CN", "CN"],
            "exchange": ["SZSE", "SZSE"],
            "currency": ["CNY", "CNY"],
            "adjustment": ["raw", "hfq"],  # 混合复权
            "schema_version": ["v2", "v2"],
            "updated_at": [now_utc, now_utc],
        }
    )
    mixed_df.write_parquet(target_dir / "data.parquet")

    gate = QualityGate(tmp_path)
    assert not gate.assert_no_mixed_adjustment(gate._active_parquet_files())
