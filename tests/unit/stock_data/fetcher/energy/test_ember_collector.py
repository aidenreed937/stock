"""Ember 全球发电与电力采集器单元测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import polars as pl

from stock_data.fetcher.energy.ember import EmberClient, EmberCollector, EmberParser
from stock_data.fetcher.energy.taxonomy import EnergyProduct

SAMPLE_EMBER_CSV = """Area,ISO 3 code,Year,Area type,Continent,Ember region,EU,OECD,G20,G7,ASEAN,Category,Subcategory,Variable,Unit,Value,YoY absolute change,YoY % change
China,CHN,2023,Country or economy,Asia,Asia,0.0,0.0,1.0,0.0,0.0,Electricity generation,Fuel,Solar,TWh,584.15,157.06,36.77
China,CHN,2023,Country or economy,Asia,Asia,0.0,0.0,1.0,0.0,0.0,Electricity generation,Fuel,Wind,TWh,885.87,123.18,16.15
China,CHN,2023,Country or economy,Asia,Asia,0.0,0.0,1.0,0.0,0.0,Electricity generation,Aggregate fuel,Clean,%,35.26,1.2,3.52
China,CHN,2023,Country or economy,Asia,Asia,0.0,0.0,1.0,0.0,0.0,Capacity,Fuel,Solar,GW,609.49,216.88,55.24
United States,USA,2023,Country or economy,North America,North America,0.0,1.0,1.0,1.0,0.0,Electricity generation,Fuel,Solar,TWh,238.12,33.56,16.41
"""


def test_ember_parser_extracts_generation_and_capacity() -> None:
    """测试 EmberParser 能够正确区分发电量与装机容量并完成技术映射。"""
    gen_records, cap_records = EmberParser.parse_yearly_csv(SAMPLE_EMBER_CSV)

    assert len(gen_records) == 4
    assert len(cap_records) == 1

    # 验证中国光伏发电量
    chn_solar = next(
        r for r in gen_records if r.geo_code == "CHN" and r.technology == EnergyProduct.SOLAR_PV
    )
    assert chn_solar.generation_twh == 584.15
    assert chn_solar.yoy_growth == 0.3677
    assert chn_solar.unit == "twh"
    assert chn_solar.source == "EMBER"

    # 验证清洁能源占比
    chn_clean = next(
        r
        for r in gen_records
        if r.geo_code == "CHN" and r.technology == EnergyProduct.CLEAN_ENERGY_TOTAL
    )
    assert chn_clean.share_percent == 35.26

    # 验证装机容量
    chn_cap = cap_records[0]
    assert chn_cap.geo_code == "CHN"
    assert chn_cap.technology == EnergyProduct.SOLAR_PV
    assert chn_cap.capacity_gw == 609.49
    assert chn_cap.new_added_gw == 216.88
    assert chn_cap.unit == "gw"


def test_ember_collector_collect_and_save(tmp_path: Path) -> None:
    """测试 EmberCollector 端到端流程与落盘。"""
    raw_dir = tmp_path / "raw"
    curated_dir = tmp_path / "curated"

    with patch.object(EmberClient, "fetch_yearly_data", return_value=SAMPLE_EMBER_CSV):
        collector = EmberCollector(raw_dir=raw_dir, curated_dir=curated_dir)
        results = collector.collect_and_save()

        assert "global_power_generation" in results
        assert "global_renewable_capacity" in results
        assert results["global_power_generation"] == 4
        assert results["global_renewable_capacity"] == 1

        # 检查落盘文件
        gen_pq = curated_dir / "global_power_generation.parquet"
        cap_pq = curated_dir / "global_renewable_capacity.parquet"
        assert gen_pq.exists()
        assert cap_pq.exists()

        df_gen = pl.read_parquet(gen_pq)
        assert df_gen.height == 4
        assert "unit" in df_gen.columns
        assert df_gen["unit"].to_list() == ["twh", "twh", "twh", "twh"]
