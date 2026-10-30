"""申万行业成分版本化表测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock_data.catalog.index_member_versioned import load_index_member_for_classification
from stock_data.pipeline.index_member_versioned import (
    INDEX_MEMBER_VERSIONED_PRIMARY_KEYS,
    build_index_member_versioned,
    materialize_index_member_versioned,
)


def _members() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "index_code": ["801001.SI", "801002.SI", "801999.SI"],
            "con_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "in_date": ["20200101"] * 3,
            "out_date": [None] * 3,
            "is_new": ["Y"] * 3,
            "symbol": ["index_member"] * 3,
        }
    )


def test_versioned_members_preserve_shared_and_unresolved_codes() -> None:
    classify = pl.DataFrame(
        {
            "index_code": ["801001.SI", "801001.SI", "801002.SI"],
            "src": ["SW2014", "SW2021", "SW2021"],
        }
    )

    result = build_index_member_versioned(_members(), classify)

    assert result.height == 4
    assert set(result.get_column("src").to_list()) == {"SW2014", "SW2021", "UNRESOLVED"}
    assert result.filter(pl.col("index_code") == "801001.SI").get_column(
        "src_status"
    ).unique().to_list() == ["shared_code"]
    assert result.filter(pl.col("src") == "UNRESOLVED").get_column("src_status").to_list() == [
        "unresolved"
    ]
    assert len(result.unique(subset=list(INDEX_MEMBER_VERSIONED_PRIMARY_KEYS))) == result.height


def test_versioned_members_keep_distinct_src_in_primary_key() -> None:
    members = pl.DataFrame(
        {
            "index_code": ["801001.SI"],
            "con_code": ["000001.SZ"],
            "in_date": [date(2020, 1, 1)],
            "out_date": [None],
        }
    )
    classify = pl.DataFrame({"index_code": ["801001.SI", "801001.SI"], "src": ["SW2014", "SW2021"]})

    result = build_index_member_versioned(members, classify)

    assert result.height == 2
    assert set(result.get_column("src").to_list()) == {"SW2014", "SW2021"}


def test_load_versioned_members_filters_src() -> None:
    versioned = build_index_member_versioned(
        _members(),
        pl.DataFrame({"index_code": ["801001.SI"], "src": ["SW2021"]}),
    )

    class _Catalog:
        def load_dataset(self, dataset: str, **_: object) -> pl.DataFrame:
            return versioned if dataset == "index_member_versioned" else pl.DataFrame()

        def list_datasets(self) -> list[str]:
            return ["index_member_versioned"]

    result = load_index_member_for_classification(
        _Catalog(), classification="SW2021", columns=["index_code", "src"]
    )

    assert result.get_column("src").unique().to_list() == ["SW2021"]
    assert result.get_column("index_code").to_list() == ["801001.SI"]


def test_load_versioned_members_falls_back_to_raw_members() -> None:
    class _Catalog:
        def load_dataset(self, dataset: str, **_: object) -> pl.DataFrame:
            return _members() if dataset == "index_member" else pl.DataFrame()

    result = load_index_member_for_classification(_Catalog(), columns=["index_code", "con_code"])

    assert result.height == 3
    assert result.columns == ["index_code", "con_code"]


def test_data_catalog_dedup_keeps_src_dimension(tmp_path: Path) -> None:
    versioned = build_index_member_versioned(
        pl.DataFrame(
            {
                "index_code": ["801001.SI"],
                "con_code": ["000001.SZ"],
                "in_date": ["20200101"],
                "out_date": [None],
            }
        ),
        pl.DataFrame(
            {
                "index_code": ["801001.SI", "801001.SI"],
                "src": ["SW2014", "SW2021"],
            }
        ),
    )
    target = tmp_path / "tushare" / "market=CN" / "index_member_versioned" / "data.parquet"
    target.parent.mkdir(parents=True)
    versioned.write_parquet(target)

    from stock_data.catalog import DataCatalog

    loaded = DataCatalog(data_source="tushare", storage_dir=tmp_path).load_dataset(
        "index_member_versioned"
    )

    assert loaded.height == 2
    assert set(loaded.get_column("src").to_list()) == {"SW2014", "SW2021"}


def test_materialize_accepts_runtime_context(tmp_path: Path) -> None:
    from stock_data.core.runtime import DataRuntimeContext

    runtime = DataRuntimeContext.from_root(tmp_path / "runtime")
    runtime.ensure_directories()

    assert materialize_index_member_versioned(runtime=runtime, dry_run=True).is_empty()
