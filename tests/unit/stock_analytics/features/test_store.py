"""FeatureStore 单元测试。"""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_analytics.features.store import FeatureStore
from stock_core.exceptions import DataValidationError, StorageError


def test_feature_store_read_write_and_projection(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    assert store.get_market_daily().is_empty()

    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 1), date(2026, 8, 2)],
            "total_turnover": [1000000.0, 2000000.0],
            "adv_dec_ratio": [1.5, 0.8],
            "above_ma20_ratio": [0.65, 0.60],
        }
    )
    store.save_market_daily(df)

    # 1. 完整读取
    loaded = store.get_market_daily()
    assert len(loaded) == 2
    assert "total_turnover" in loaded.columns

    # 2. 列投影读取
    projected = store.get_market_daily(columns=["trade_date", "total_turnover"])
    assert projected.columns == ["trade_date", "total_turnover"]
    assert len(projected) == 2

    # 3. 日期过滤
    filtered = store.get_market_daily(start_date=date(2026, 8, 2), end_date=date(2026, 8, 2))
    assert len(filtered) == 1
    assert filtered["trade_date"][0] == date(2026, 8, 2)

    # 4. 最新日期
    assert store.get_latest_market_daily_date() == date(2026, 8, 2)


def test_feature_store_missing_market_daily_stays_empty(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")

    assert store.get_market_daily().is_empty()
    assert store.get_latest_market_daily_date() is None


def test_feature_store_corrupt_market_daily_raises_storage_error(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    store.market_daily_path.write_bytes(b"not a parquet file")

    with pytest.raises(StorageError, match="market_daily"):
        store.get_market_daily()
    with pytest.raises(StorageError, match="market_daily"):
        store.get_latest_market_daily_date()


def test_feature_store_rejects_market_daily_schema_drift(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    pl.DataFrame({"value": [1.0]}).write_parquet(store.market_daily_path)

    with pytest.raises(DataValidationError, match="trade_date"):
        store.get_market_daily()


def test_feature_store_corrupt_domain_mart_raises_storage_error(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    path = store.domain_mart_path("convertible_bond_daily")
    path.write_bytes(b"not a parquet file")

    with pytest.raises(StorageError, match="convertible_bond_daily"):
        store.get_domain_mart("convertible_bond_daily", date_column="trade_date")


def test_feature_store_rejects_domain_mart_date_schema_drift(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    path = store.domain_mart_path("convertible_bond_daily")
    pl.DataFrame({"value": [1.0]}).write_parquet(path)

    with pytest.raises(DataValidationError, match="trade_date"):
        store.get_domain_mart("convertible_bond_daily", date_column="trade_date")


def test_feature_values_corrupt_file_raises_storage_error(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    store.values.path.write_bytes(b"not a parquet file")

    with pytest.raises(StorageError, match="FeatureValueStore"):
        store.values.get()


def test_feature_values_rejects_schema_drift(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    pl.DataFrame({"feature_id": ["advance_ratio"]}).write_parquet(store.values.path)

    with pytest.raises(DataValidationError, match="feature_values"):
        store.values.get()


def test_feature_store_corrupt_metadata_raises_data_validation_error(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    metadata_path = store.mart_dir / "market_daily.metadata.json"
    metadata_path.write_text("not json", encoding="utf-8")

    with pytest.raises(DataValidationError, match="元数据"):
        store.get_market_daily_metadata()


def test_feature_store_merge_incremental(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")

    df1 = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 1)],
            "total_turnover": [1000.0],
        }
    )
    store.save_market_daily(df1, metadata={"definition_fingerprint": "v1"})

    df2 = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 2)],
            "total_turnover": [2000.0],
        }
    )
    store.save_market_daily(df2, overwrite=False, metadata={"definition_fingerprint": "v1"})

    merged = store.get_market_daily()
    assert len(merged) == 2
    assert merged["trade_date"].to_list() == [date(2026, 8, 1), date(2026, 8, 2)]


def test_feature_store_rejects_incremental_definition_mismatch(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    frame = pl.DataFrame({"trade_date": [date(2026, 8, 1)], "total_turnover": [1000.0]})
    store.save_market_daily(
        frame,
        metadata={"definition_fingerprint": "v1"},
    )

    with pytest.raises(ValueError, match="定义指纹"):
        store.save_market_daily(
            frame,
            metadata={"definition_fingerprint": "v2"},
        )


def test_feature_values_preserve_definition_versions(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")

    store.values.save(pl.DataFrame([_feature_row("v1", 0.4)]))
    store.values.save(pl.DataFrame([_feature_row("v2", 0.5)]))

    values = store.values.get(feature_ids=["advance_ratio"])
    assert len(values) == 2
    assert values["definition_version"].to_list() == ["v1", "v2"]


def test_feature_store_merge_keeps_both_sides_non_null_on_same_day(
    tmp_path: Path,
) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    metadata = {"definition_fingerprint": "v1"}

    store.save_market_daily(
        pl.DataFrame(
            {
                "trade_date": [date(2026, 8, 1), date(2026, 8, 2)],
                "total_turnover": [1000.0, None],
                "adv_dec_ratio": [1.5, 0.8],
            }
        ),
        metadata=metadata,
    )
    store.save_market_daily(
        pl.DataFrame(
            {
                "trade_date": [date(2026, 8, 1), date(2026, 8, 2)],
                "total_turnover": [None, 2000.0],
                "new_high_252d_ratio": [0.1, 0.2],
            }
        ),
        overwrite=False,
        metadata=metadata,
    )

    merged = store.get_market_daily()
    row_1 = merged.filter(pl.col("trade_date") == date(2026, 8, 1))
    row_2 = merged.filter(pl.col("trade_date") == date(2026, 8, 2))
    assert row_1["total_turnover"][0] == 1000.0  # incoming 为 null 不覆盖存量值
    assert row_2["total_turnover"][0] == 2000.0  # incoming 非空生效
    assert row_1["adv_dec_ratio"][0] == 1.5  # 存量列保留
    assert row_1["new_high_252d_ratio"][0] == 0.1  # 新列追加


def test_feature_values_merge_keeps_existing_when_incoming_null(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")

    store.values.save(pl.DataFrame([_feature_row("v1", 0.4)]))
    # 同键行的 null 增量不应覆盖已有有效值
    store.values.save(pl.DataFrame([_feature_row("v1", None)]))

    values = store.values.get(feature_ids=["advance_ratio"])
    assert len(values) == 1
    assert values["value_float"][0] == 0.4


def test_feature_values_purge_outside_syncs_wide_table_date_domain(
    tmp_path: Path,
) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")

    store.values.save(pl.DataFrame([_feature_row("v1", 0.4, date(2026, 8, 1))]))
    # overwrite 重建窄窗口（仅 8/2）时，范围外存量行应被清除
    store.values.save(
        pl.DataFrame([_feature_row("v1", 0.5, date(2026, 8, 2))]),
        purge_outside=(date(2026, 8, 2), date(2026, 8, 2)),
    )

    values = store.values.get(feature_ids=["advance_ratio"])
    assert values["observation_date"].to_list() == [date(2026, 8, 2)]


def test_feature_store_incremental_requires_metadata(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    frame = pl.DataFrame({"trade_date": [date(2026, 8, 1)], "total_turnover": [1000.0]})
    store.save_market_daily(frame, metadata={"definition_fingerprint": "v1"})

    with pytest.raises(ValueError, match="增量合并必须提供构建元数据"):
        store.save_market_daily(frame)


def test_feature_store_domain_mart_merge_deduplicates_by_domain_key(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    store.save_domain_mart(
        "convertible_bond_daily",
        pl.DataFrame({"trade_date": [date(2026, 8, 1)], "cb_price_median": [105.0]}),
        keys=["trade_date"],
        date_column="trade_date",
    )
    store.save_domain_mart(
        "convertible_bond_daily",
        pl.DataFrame(
            {
                "trade_date": [date(2026, 8, 1), date(2026, 8, 2)],
                "cb_price_median": [106.0, 107.0],
            }
        ),
        keys=["trade_date"],
        date_column="trade_date",
    )

    loaded = store.get_domain_mart("convertible_bond_daily", date_column="trade_date")
    assert loaded["trade_date"].to_list() == [date(2026, 8, 1), date(2026, 8, 2)]
    assert loaded["cb_price_median"].to_list() == [106.0, 107.0]


def test_feature_store_domain_mart_rejects_duplicate_or_non_finite_rows(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    duplicate = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 1), date(2026, 8, 1)],
            "cb_price_median": [105.0, 106.0],
        }
    )
    with pytest.raises(ValueError, match="重复主键"):
        store.save_domain_mart(
            "convertible_bond_daily",
            duplicate,
            keys=["trade_date"],
            date_column="trade_date",
        )

    non_finite = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 1)],
            "cb_price_median": [float("inf")],
        }
    )
    with pytest.raises(ValueError, match="非有限"):
        store.save_domain_mart(
            "convertible_bond_daily",
            non_finite,
            keys=["trade_date"],
            date_column="trade_date",
        )


def test_feature_store_reads_new_daily_marts_by_date(tmp_path: Path) -> None:
    store = FeatureStore(mart_dir=tmp_path / "mart")
    day_1 = date(2026, 8, 1)
    day_2 = date(2026, 8, 2)

    store.save_industry_daily(
        pl.DataFrame(
            {
                "trade_date": [day_1, day_2],
                "industry_code": ["801001.SI", "801001.SI"],
                "close": [100.0, 101.0],
            }
        ),
        overwrite=True,
    )
    store.save_industry_panel_daily(
        pl.DataFrame(
            {
                "as_of_date": [day_1, day_2],
                "industry_code": ["801001.SI", "801001.SI"],
                "industry_name": ["行业1", "行业1"],
            }
        ),
        overwrite=True,
    )
    store.save_market_temperature_derived_facts(
        pl.DataFrame(
            {
                "fact_id": ["metric.technical.return_20d"],
                "category": ["metric_value"],
                "dimension": ["technical"],
                "data_source": ["mart"],
                "dataset": ["market_daily"],
                "as_of_date": [day_1],
                "metric_date": [day_1],
                "window": [0],
                "metric_id": ["return_20d"],
                "value_float": [1.0],
                "value_text": ["1"],
                "unit": ["raw"],
                "sample_size": [10],
                "source": ["test"],
                "status": ["ok"],
                "note": ["test"],
            }
        ),
        overwrite=True,
    )

    assert store.industry_daily_path.exists()
    assert store.industry_panel_daily_path.exists()
    assert store.market_temperature_derived_facts_path.exists()
    assert store.get_industry_daily(start_date=day_2)["trade_date"].to_list() == [day_2]
    assert store.get_industry_panel_daily(start_date=day_2).height == 1
    assert store.get_market_temperature_derived_facts(day_1)["metric_id"].to_list() == [
        "return_20d"
    ]


def _feature_row(
    version: str, value: float | None, observation_date: date = date(2026, 8, 1)
) -> dict[str, object]:
    return {
        "feature_id": "advance_ratio",
        "kind": "indicator",
        "entity_type": "market",
        "entity_id": "CN",
        "frequency": "1d",
        "observation_date": observation_date,
        "available_at": "2026-08-17T00:00:00+00:00",
        "unit": "ratio",
        "value_float": value,
        "value_str": None,
        "sample_size": None,
        "status": "ok",
        "definition_version": version,
        "source_watermark": "{}",
        "input_fingerprint": version,
    }
