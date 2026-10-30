"""TuShare/LiXinger 申万跨源黄金表测试。"""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from stock_data.catalog import DataCatalog
from stock_data.pipeline.sw_industry_golden import (
    build_sw_2021_industry_dimension,
    build_sw_2021_industry_member_golden,
    load_sw_2021_industry_members,
    materialize_sw_2021_industry_golden,
)


def _classify() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "index_code": ["801000.SI", "801001.SI", "801001.SI", "801002.SI"],
            "industry_name": ["一级", "二级", "二级重复", "三级"],
            "level": ["L1", "L2", "L2", "L3"],
            "industry_code": ["110000", "110100", "110100", "110101"],
            "parent_code": [None, "110000", "110000", "110100"],
            "src": ["SW2021"] * 4,
            "request_id": ["classify-request"] * 4,
        }
    )


def _members() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "index_code": ["801000.SI", "801001.SI", "801002.SI"],
            "con_code": ["000001.SZ", "000001.SZ", "000002.SZ"],
            "in_date": [date(2020, 1, 1)] * 3,
            "out_date": [None, None, date(2023, 1, 1)],
            "request_id": ["member-request"] * 3,
        }
    )


def _lixinger() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "industryCode": ["110000", "110200", "110101", "110000"],
            "symbol": ["000001", "000001", "000003", "000002"],
        }
    )


def test_dimension_keeps_union_and_coverage_status() -> None:
    result = build_sw_2021_industry_dimension(_classify(), _lixinger())

    assert set(result["industry_code"].to_list()) == {"110000", "110100", "110101", "110200"}
    assert result.filter(pl.col("industry_code") == "110000")["mapping_status"].item() == (
        "both_present"
    )
    assert set(result["src"].to_list()) == {"TUSHARE", "TUSHARE+LIXINGER", "LIXINGER"}


def test_member_golden_marks_conflict_and_lixinger_supplement() -> None:
    result = build_sw_2021_industry_member_golden(
        _classify(),
        _members(),
        _lixinger(),
        snapshot_date=date(2024, 1, 1),
    )

    conflict = result.filter((pl.col("symbol") == "000001") & (pl.col("level") == "L2"))
    assert conflict.height == 2
    assert set(conflict["source_status"].to_list()) == {"conflict_tushare_preferred"}
    assert conflict.filter(pl.col("is_canonical"))["src"].item() == "TUSHARE"
    assert (
        result.filter((pl.col("symbol") == "000003") & (pl.col("industry_code") == "110101"))[
            "source_status"
        ].item()
        == "lixinger_supplement"
    )
    assert result.filter(pl.col("src") == "LIXINGER").height == 4


def test_materialize_writes_derived_catalog_and_filters_current(tmp_path: Path) -> None:
    updated_at = datetime(2026, 9, 4, tzinfo=UTC)
    ts_root = tmp_path / "tushare" / "market=CN"
    lx_root = tmp_path / "lixinger" / "market=CN"
    (ts_root / "index_classify").mkdir(parents=True)
    (ts_root / "index_member").mkdir(parents=True)
    (lx_root / "sw_2021_constituents").mkdir(parents=True)
    _classify().with_columns(pl.lit(updated_at).alias("updated_at")).write_parquet(
        ts_root / "index_classify" / "data.parquet"
    )
    _members().write_parquet(ts_root / "index_member" / "data.parquet")
    _lixinger().with_columns(pl.lit(updated_at).alias("updated_at")).write_parquet(
        lx_root / "sw_2021_constituents" / "data.parquet"
    )

    result = materialize_sw_2021_industry_golden(storage_dir=tmp_path)

    assert result.dimension_path == (
        tmp_path / "derived" / "market=CN" / "sw_2021_industry_dimension_golden" / "data.parquet"
    )
    assert result.member_path == (
        tmp_path / "derived" / "market=CN" / "sw_2021_industry_member_golden" / "data.parquet"
    )
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    current = load_sw_2021_industry_members(
        catalog,
        as_of_date=date(2026, 9, 4),
        level="L1",
        canonical_only=True,
        columns=("symbol", "industry_code", "src"),
    )
    assert "000002" in current["symbol"].to_list()
    assert current["symbol"].n_unique() == current.height
