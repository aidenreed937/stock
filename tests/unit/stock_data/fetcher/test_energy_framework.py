"""全球能源多源采集与落盘框架单元测试。"""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_data.fetcher.energy import (
    DataStatus,
    EnergyCrossSourceAuditRecord,
    EnergyFlowType,
    EnergyProduct,
    GlobalMacroEnergyBaselineRecord,
    GlobalOilGasBalanceRecord,
    GlobalPowerGenerationRecord,
    GlobalRenewableCapacityRecord,
    convert_capacity_to_gw,
    convert_energy_to_ej,
    convert_gas_flow_to_bcm,
    convert_generation_to_twh,
    convert_oil_flow_to_kbpd,
    get_month_end_date,
    normalize_geo_code,
    parse_period_to_date,
    records_to_energy_audit_frame,
    records_to_macro_energy_baseline_frame,
    records_to_oil_gas_balance_frame,
    records_to_power_generation_frame,
    records_to_renewable_capacity_frame,
    save_curated_energy_fact,
    save_raw_energy_snapshot,
)
from stock_data.pipeline.energy_pipeline import init_energy_curated_store


def test_normalize_geo_code() -> None:
    """测试国家与地区编码标准化。"""
    assert normalize_geo_code("China") == "CHN"
    assert normalize_geo_code("PRC") == "CHN"
    assert normalize_geo_code("中国") == "CHN"
    assert normalize_geo_code("United States") == "USA"
    assert normalize_geo_code("Germany") == "DEU"
    assert normalize_geo_code("European Union") == "EU27"
    assert normalize_geo_code("Total World") == "WLD"
    assert normalize_geo_code("UnknownCountry") == "UNKNOWNCOUNTRY"


def test_unit_converters() -> None:
    """测试各类能源计量单位换算。"""
    # 发电量 -> TWh
    assert convert_generation_to_twh(1000, "GWh") == 1.0
    assert convert_generation_to_twh(1_000_000, "MWh") == 1.0
    assert convert_generation_to_twh(5.5, "TWh") == 5.5
    assert convert_generation_to_twh(10, "Billion_kWh") == 10.0

    # 装机容量 -> GW
    assert convert_capacity_to_gw(1000, "MW") == 1.0
    assert convert_capacity_to_gw(100, "Ten_Thousand_kW") == 1.0
    assert convert_capacity_to_gw(3.2, "GW") == 3.2

    # 石油流量 -> kbpd
    assert convert_oil_flow_to_kbpd(5000, "bpd") == 5.0
    assert convert_oil_flow_to_kbpd(12.5, "kbpd") == 12.5

    # 天然气流量 -> bcm
    assert convert_gas_flow_to_bcm(1000, "mcm") == 1.0
    assert pytest.approx(convert_gas_flow_to_bcm(100, "bcf"), 0.001) == 2.83168

    # 宏观综合能耗 -> EJ
    assert convert_energy_to_ej(1000, "PJ") == 1.0
    assert pytest.approx(convert_energy_to_ej(100, "Mtoe"), 0.001) == 4.1868

    with pytest.raises(ValueError, match="不支持的发电量单位"):
        convert_generation_to_twh(100, "UNKNOWN_UNIT")


def test_parse_period_to_date() -> None:
    """测试时间周期转换。"""
    assert parse_period_to_date("2025") == date(2025, 12, 31)
    assert parse_period_to_date("2025-02") == date(2025, 2, 28)
    assert parse_period_to_date("2024-02") == date(2024, 2, 29)  # 闰年
    assert parse_period_to_date("2025-08-30") == date(2025, 8, 30)
    assert get_month_end_date(2025, 7) == date(2025, 7, 31)


def test_models_and_polars_converters() -> None:
    """测试 5 大黄金表记录转换与 Schema 校验。"""
    # 1. 油气供需平衡
    oil_rec = GlobalOilGasBalanceRecord(
        geo_code="SAU",
        trade_date=date(2025, 6, 30),
        period="2025-06",
        product=EnergyProduct.CRUDE_OIL,
        flow_type=EnergyFlowType.PRODUCTION,
        standard_value=9000.0,
        standard_unit="kbpd",
        source="JODI",
    )
    df_oil = records_to_oil_gas_balance_frame([oil_rec])
    assert df_oil.shape == (1, 14)
    assert df_oil["geo_code"][0] == "SAU"

    # 2. 全球发电量
    power_rec = GlobalPowerGenerationRecord(
        geo_code="CHN",
        trade_date=date(2025, 6, 30),
        period="2025-06",
        period_type="monthly",
        technology=EnergyProduct.SOLAR_PV,
        generation_twh=85.4,
        yoy_growth=0.32,
        share_percent=11.2,
        source="EMBER",
    )
    df_power = records_to_power_generation_frame([power_rec])
    assert df_power.shape == (1, 14)
    assert df_power["generation_twh"][0] == 85.4
    assert df_power["unit"][0] == "twh"

    # 3. 可再生能源装机
    cap_rec = GlobalRenewableCapacityRecord(
        geo_code="USA",
        year=2024,
        technology=EnergyProduct.WIND_TOTAL,
        capacity_gw=150.5,
        new_added_gw=12.3,
        source="IRENA",
    )
    df_cap = records_to_renewable_capacity_frame([cap_rec])
    assert df_cap.shape == (1, 11)
    assert df_cap["capacity_gw"][0] == 150.5
    assert df_cap["unit"][0] == "gw"

    # 4. 宏观长周期基准
    macro_rec = GlobalMacroEnergyBaselineRecord(
        geo_code="WLD",
        year=2024,
        energy_type=EnergyProduct.TOTAL_PRIMARY_ENERGY,
        flow_type=EnergyFlowType.CONSUMPTION,
        value_ej=620.0,
        source="EI",
    )
    df_macro = records_to_macro_energy_baseline_frame([macro_rec])
    assert df_macro.shape == (1, 8)
    assert df_macro["value_ej"][0] == 620.0

    # 5. 审计表
    audit_rec = EnergyCrossSourceAuditRecord(
        audit_date=date(2025, 8, 30),
        audit_rule="TOTAL_CONSISTENCY",
        geo_code="CHN",
        period="2024",
        product="SOLAR_PV",
        source_a="EMBER",
        value_a=580.0,
        source_b="EI",
        value_b=584.0,
        diff_percent=0.0068,
        discrepancy_status="PASS",
    )
    df_audit = records_to_energy_audit_frame([audit_rec])
    assert df_audit.shape == (1, 12)
    assert df_audit["discrepancy_status"][0] == "PASS"


def test_save_raw_and_curated_facts(tmp_path: Path) -> None:
    """测试 RAW 快照与 Curated 增量落盘。"""
    raw_dir = tmp_path / "raw"
    curated_dir = tmp_path / "curated"

    # 测试 RAW 快照保存
    snap_path = save_raw_energy_snapshot(
        source_name="jodi",
        snapshot_filename="test_snapshot.json",
        content={"status": "ok", "rows": 10},
        base_dir=raw_dir,
    )
    assert snap_path.exists()
    assert "jodi" in str(snap_path)

    # 测试 Curated 事实表增量持久化与去重
    rec1 = GlobalOilGasBalanceRecord(
        geo_code="CHN",
        trade_date=date(2025, 5, 31),
        period="2025-05",
        product="CRUDE_OIL",
        flow_type="IMPORT",
        standard_value=11000.0,
        standard_unit="kbpd",
    )
    rec2 = GlobalOilGasBalanceRecord(
        geo_code="CHN",
        trade_date=date(2025, 6, 30),
        period="2025-06",
        product="CRUDE_OIL",
        flow_type="IMPORT",
        standard_value=11200.0,
        standard_unit="kbpd",
    )
    df_batch1 = records_to_oil_gas_balance_frame([rec1])
    target_parquet = curated_dir / "global_oil_gas_balance.parquet"

    # 首次落盘
    count1 = save_curated_energy_fact(
        df_batch1,
        target_parquet,
        primary_keys=["geo_code", "period", "product", "flow_type", "source"],
        sort_keys=["trade_date", "geo_code"],
    )
    assert count1 == 1
    assert target_parquet.exists()
    assert target_parquet.with_suffix(".csv").exists()

    # 第二次增量落盘 (含重复 key 和新 key)
    rec1_updated = GlobalOilGasBalanceRecord(
        geo_code="CHN",
        trade_date=date(2025, 5, 31),
        period="2025-05",
        product="CRUDE_OIL",
        flow_type="IMPORT",
        standard_value=11050.0,  # 修订更新
        standard_unit="kbpd",
        data_status=DataStatus.REVISED,
    )
    df_batch2 = records_to_oil_gas_balance_frame([rec1_updated, rec2])
    count2 = save_curated_energy_fact(
        df_batch2,
        target_parquet,
        primary_keys=["geo_code", "period", "product", "flow_type", "source"],
        sort_keys=["trade_date", "geo_code"],
    )
    assert count2 == 2

    # 读取并验证去重与更新生效
    result_df = pl.read_parquet(target_parquet)
    assert result_df.height == 2
    row_may = result_df.filter(pl.col("period") == "2025-05")
    assert row_may["standard_value"][0] == 11050.0
    assert row_may["data_status"][0] == "revised"


def test_init_energy_curated_store(tmp_path: Path) -> None:
    """测试 5 大黄金表初始化。"""
    curated_dir = tmp_path / "curated" / "industry" / "energy"
    paths = init_energy_curated_store(curated_dir=curated_dir)

    expected_files = [
        "global_oil_gas_balance.parquet",
        "global_power_generation.parquet",
        "global_renewable_capacity.parquet",
        "global_energy_macro_baseline.parquet",
        "energy_cross_source_audit.parquet",
    ]
    for filename in expected_files:
        assert (curated_dir / filename).exists()
        assert (curated_dir / filename.replace(".parquet", ".csv")).exists()

    assert len(paths) == 5
