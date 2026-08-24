"""市场温度计数据水位异常降级测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.market_temperature.fact_watermarks import collect_dataset_rows
from stock_reporting.interpretation.market_temperature.config import DatasetConfig


class _BrokenCatalog:
    data_source = "tushare"

    def __init__(self, **_: object) -> None:
        pass

    def latest_trade_dates(self, dataset: str, **_: object) -> list[date]:
        del dataset
        raise RuntimeError("watermark unavailable")

    def load_dataset(self, dataset: str, **_: object) -> pl.DataFrame:
        raise RuntimeError(f"dataset unavailable: {dataset}")


def _fact_row(
    payload: dict[str, object],
    *,
    value_text: str = "",
    sample_size: int | None = None,
) -> dict[str, object]:
    return {**payload, "value_text": value_text, "sample_size": sample_size}


def test_watermark_errors_preserve_required_and_optional_statuses(
    monkeypatch, tmp_path: Path
) -> None:
    import stock_data.catalog

    monkeypatch.setattr(stock_data.catalog, "DataCatalog", _BrokenCatalog)
    rows = collect_dataset_rows(
        [
            DatasetConfig(
                data_source="tushare",
                dataset="required_dataset",
                dimension="technical",
                required=True,
            ),
            DatasetConfig(
                data_source="tushare",
                dataset="optional_dataset",
                dimension="technical",
                required=False,
            ),
        ],
        date(2026, 8, 14),
        storage_dir=tmp_path,
        dataset_cache=None,
        fact_row=_fact_row,
    )

    assert [row["status"] for row in rows] == ["error", "unavailable"]
    assert all("RuntimeError" in str(row["note"]) for row in rows)
