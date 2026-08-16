"""两融数值质量门禁与隔离测试。"""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import polars as pl
import pytest

from stock.core.contracts import DatasetKey
from stock.data.pipeline_stages import CuratedStorageStage, FetcherStage
from stock.data.quality.quarantine import QuarantineStore
from stock.data.storage.raw_store import RawDataStorage
from stock.exceptions import DataValidationError


def _complete_margin_frame() -> pl.DataFrame:
    target_date = date(2026, 8, 13)
    rows = []
    for exchange, rzye, rqye in (
        ("SSE", 100.0, 10.0),
        ("SZSE", 120.0, 12.0),
        ("BSE", 8.0, 1.0),
    ):
        rows.append(
            {
                "trade_date": target_date,
                "exchange_id": exchange,
                "rzye": rzye,
                "rzmre": 10.0,
                "rzche": 5.0,
                "rqye": rqye,
                "rqmcl": 30.0,
                "rzrqye": rzye + rqye,
                "rqyl": 40.0,
            }
        )
    return pl.DataFrame(rows)


def _margin_key(target_date: date) -> DatasetKey:
    return DatasetKey(
        provider="tushare",
        dataset="margin",
        endpoint="margin",
        start_date=target_date,
        end_date=target_date,
    )


def test_fetcher_stage_quarantines_margin_value_quality_failure(tmp_path: Path) -> None:
    fetcher = MagicMock()
    fetcher.fetch_daily_bars_df.return_value = _complete_margin_frame().with_columns(
        pl.when(pl.col("exchange_id") == "BSE")
        .then(pl.lit(-1.0))
        .otherwise(pl.col("rqyl"))
        .alias("rqyl")
    )
    raw_store = RawDataStorage(base_dir=tmp_path / "raw")
    stage = FetcherStage(
        fetcher,
        raw_store,
        data_source="tushare",
        quarantine=QuarantineStore(tmp_path / "quarantine"),
    )
    target_date = date(2026, 8, 13)

    with pytest.raises(DataValidationError, match="数值质量不合格"):
        stage.extract(
            symbol="margin",
            start_date=target_date,
            end_date=target_date,
            key=_margin_key(target_date),
            api_name="margin",
            endpoint_name="margin",
        )

    assert (tmp_path / "raw/tushare/market=CN/margin/data.parquet").exists()
    quarantine_path = tmp_path / "quarantine/endpoint=margin/records.parquet"
    assert quarantine_path.exists()
    assert (
        "margin_value_quality_failed"
        in pl.read_parquet(quarantine_path)["quarantine_reason"].to_list()[0]
    )


def test_curated_stage_rejects_margin_value_quality_failure() -> None:
    store = MagicMock()
    stage = CuratedStorageStage(store)
    target_date = date(2026, 8, 13)
    frame = _complete_margin_frame().with_columns(
        pl.when(pl.col("exchange_id") == "BSE")
        .then(pl.lit(12.0))
        .otherwise(pl.col("rzrqye"))
        .alias("rzrqye")
    )

    with pytest.raises(DataValidationError, match="数值质量不合格"):
        stage.load(_margin_key(target_date), frame, "margin")

    store.save_dataset.assert_not_called()
