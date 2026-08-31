"""IRENA (国际可再生能源署) 数据解析与采集器单元测试。"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from stock_data.fetcher.energy.irena import (
    IrenaCollector,
    IrenaParser,
    parse_irena_value_and_status,
)
from stock_data.fetcher.energy.taxonomy import DataStatus, EnergyProduct

SAMPLE_IRENA_CSV = """Country/area,Technology,Grid connection,Year,Value
China,Solar photovoltaic,OnGrid,2022,392610 o
China,Solar photovoltaic,OnGrid,2023,609490 o
China,Solar photovoltaic,OnGrid,2024,887000 u
China,Onshore wind energy,OnGrid,2023,410000 o
China,Onshore wind energy,OnGrid,2024,470000 o
United States of America,Solar photovoltaic,OnGrid,2023,139000 o
United States of America,Solar photovoltaic,OnGrid,2024,178000 e
Germany,Wind energy,Total,2023,69500 o
World,Total renewable energy,Total,2023,3870000 o
World,Total renewable energy,Total,2024,4350000 e
"""


def test_parse_irena_value_and_status() -> None:
    """测试 IRENA 原始数值与质量标志位提取。"""
    val, status = parse_irena_value_and_status("1234 o")
    assert val == 1234.0
    assert status == DataStatus.ACTUAL

    val, status = parse_irena_value_and_status("567.8 u")
    assert val == 567.8
    assert status == DataStatus.PROVISIONAL

    val, status = parse_irena_value_and_status("890 e")
    assert val == 890.0
    assert status == DataStatus.ESTIMATED

    val, status = parse_irena_value_and_status("1,234,567")
    assert val == 1234567.0
    assert status == DataStatus.ACTUAL

    val, status = parse_irena_value_and_status("..")
    assert val is None

    val, status = parse_irena_value_and_status("-")
    assert val is None


def test_irena_parser_csv_conversion() -> None:
    """测试 IRENA CSV 转换为标准 GlobalRenewableCapacityRecord 列表。"""
    records = IrenaParser.parse_csv(SAMPLE_IRENA_CSV)
    assert len(records) > 0

    # 提取 China Solar PV
    chn_solar = [
        r for r in records if r.geo_code == "CHN" and r.technology == EnergyProduct.SOLAR_PV
    ]
    assert len(chn_solar) == 3

    # 2022 年 (基期首年)
    assert chn_solar[0].year == 2022
    assert chn_solar[0].capacity_gw == 392.61
    assert chn_solar[0].unit == "gw"
    assert chn_solar[0].new_added_gw is None
    assert chn_solar[0].data_status == DataStatus.ACTUAL

    # 2023 年 (392.61 -> 609.49, 新增 216.88 GW, 增速约 55.24%)
    assert chn_solar[1].year == 2023
    assert chn_solar[1].capacity_gw == 609.49
    assert chn_solar[1].new_added_gw == 216.88
    assert chn_solar[1].yoy_growth == 0.5524

    # 2024 年 (609.49 -> 887.0, 新增 277.51 GW, provisional)
    assert chn_solar[2].year == 2024
    assert chn_solar[2].capacity_gw == 887.0
    assert chn_solar[2].new_added_gw == 277.51
    assert chn_solar[2].data_status == DataStatus.PROVISIONAL

    # 验证国家映射
    usa_solar = [r for r in records if r.geo_code == "USA"]
    assert len(usa_solar) == 2
    assert usa_solar[1].data_status == DataStatus.ESTIMATED

    deu_wind = [r for r in records if r.geo_code == "DEU"]
    assert len(deu_wind) == 1
    assert deu_wind[0].capacity_gw == 69.5

    wld_clean = [r for r in records if r.geo_code == "WLD"]
    assert len(wld_clean) == 2
    assert wld_clean[0].capacity_gw == 3870.0


def test_irena_collector_collect_and_save(tmp_path: Path) -> None:
    """测试 IrenaCollector 从原始快照读取并落盘至 Parquet 黄金表。"""
    raw_dir = tmp_path / "raw"
    curated_dir = tmp_path / "curated"

    irena_raw_dir = raw_dir / "irena"
    irena_raw_dir.mkdir(parents=True, exist_ok=True)
    sample_file = irena_raw_dir / "renewable_capacity_2026.csv"
    sample_file.write_text(SAMPLE_IRENA_CSV, encoding="utf-8")

    collector = IrenaCollector(raw_dir=raw_dir, curated_dir=curated_dir)
    res = collector.collect_and_save()

    assert "global_renewable_capacity" in res
    assert res["global_renewable_capacity"] == 10

    # 验证落盘的 Parquet 文件
    parquet_path = curated_dir / "global_renewable_capacity.parquet"
    assert parquet_path.exists()

    df = pl.read_parquet(parquet_path)
    assert df.height == 10
    assert "capacity_gw" in df.columns
    assert "new_added_gw" in df.columns
    assert "unit" in df.columns
    assert df["unit"][0] == "gw"
    assert set(df["geo_code"].unique()) == {"CHN", "USA", "DEU", "WLD"}
