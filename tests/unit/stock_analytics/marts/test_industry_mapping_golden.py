"""行业结构统一消费申万跨源黄金表测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.marts.shared.industry_structure.industry_mapping import (
    load_industry_l1_maps,
    load_stock_industry_map,
)
from stock_data.catalog import DataCatalog
from stock_data.pipeline.sw_industry_golden import materialize_sw_2021_industry_golden


def _config():
    from stock_reporting.interpretation.industry_structure.config import (
        FundamentalBlendConfig,
        IndustryStructureConfig,
        ScoreWeights,
    )

    return IndustryStructureConfig(
        schema_version=1,
        title="测试行业结构",
        artifact_root="data/analytics/industry_structure",
        main_window=20,
        short_windows=(5, 10),
        medium_windows=(60, 120),
        classification="SW2021",
        benchmark="000985.CSI",
        score_weights=ScoreWeights(),
        fundamental_blend=FundamentalBlendConfig(),
        datasets=(),
    )


def test_industry_mapping_prefers_golden_canonical_members(tmp_path: Path) -> None:
    ts_root = tmp_path / "tushare" / "market=CN"
    lx_root = tmp_path / "lixinger" / "market=CN"
    (ts_root / "index_classify").mkdir(parents=True)
    (ts_root / "index_member").mkdir(parents=True)
    (lx_root / "sw_2021_constituents").mkdir(parents=True)
    pl.DataFrame(
        {
            "index_code": ["801000.SI", "801001.SI"],
            "industry_name": ["一级", "二级"],
            "level": ["L1", "L2"],
            "industry_code": ["110000", "110100"],
            "parent_code": [None, "110000"],
            "src": ["SW2021", "SW2021"],
        }
    ).write_parquet(ts_root / "index_classify" / "data.parquet")
    pl.DataFrame(
        {
            "index_code": ["801000.SI"],
            "con_code": ["000001.SZ"],
            "in_date": [date(2020, 1, 1)],
            "out_date": [None],
        }
    ).write_parquet(ts_root / "index_member" / "data.parquet")
    pl.DataFrame(
        {
            "industryCode": ["110000"],
            "symbol": ["000002"],
            "updated_at": [date(2026, 9, 4)],
        }
    ).write_parquet(lx_root / "sw_2021_constituents" / "data.parquet")

    materialize_sw_2021_industry_golden(storage_dir=tmp_path)
    cat_ts = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    cat_lx = DataCatalog(data_source="lixinger", storage_dir=tmp_path)

    index_to_l1, industry_to_l1 = load_industry_l1_maps(cat_ts, _config())
    result = load_stock_industry_map(cat_ts, cat_lx, _config(), date(2026, 9, 4))

    assert index_to_l1["801000.SI"] == "801000.SI"
    assert industry_to_l1["110100"] == "801000.SI"
    assert result.sort("stock_key").to_dicts() == [
        {"stock_key": "000001", "industry_code": "801000.SI"},
        {"stock_key": "000002", "industry_code": "801000.SI"},
    ]
