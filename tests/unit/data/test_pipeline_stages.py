from datetime import date
from pathlib import Path
from unittest.mock import MagicMock
import polars as pl
import pytest

from stock.core.contracts import DatasetKey, InstrumentId
from stock.data.cleaner.generic_cleaner import GenericCleaner
from stock.data.normalizer.generic_normalizer import GenericNormalizer
from stock.data.pipeline_stages import (
    CleanerStage,
    CuratedStorageStage,
    FetcherStage,
    NormalizerStage,
)
from stock.exceptions import DataValidationError


def test_fetcher_stage_clip_quarterly_dates(tmp_path: Path) -> None:
    fetcher = MagicMock()
    raw_store = MagicMock()
    stage = FetcherStage(fetcher, raw_store, data_source="tushare")

    df = pl.DataFrame(
        {
            "ts_code": ["600519.SH"] * 4,
            "quarter": ["2023Q4", "2024Q1", "2024Q2", "2024Q3"],
            "revenue": [10.0, 20.0, 30.0, 40.0],
        }
    )

    clipped = stage.clip_date_range(
        df, start_date=date(2024, 1, 1), end_date=date(2024, 6, 30), endpoint="income"
    )
    assert len(clipped) == 2
    assert clipped["quarter"].to_list() == ["2024Q1", "2024Q2"]


def test_fetcher_stage_clip_daily_dates(tmp_path: Path) -> None:
    fetcher = MagicMock()
    raw_store = MagicMock()
    stage = FetcherStage(fetcher, raw_store, data_source="tushare")

    df = pl.DataFrame(
        {
            "trade_date": ["20240101", "20240102", "20240103", "20240104"],
            "close": [10.0, 11.0, 12.0, 13.0],
        }
    )
    clipped = stage.clip_date_range(
        df, start_date=date(2024, 1, 2), end_date=date(2024, 1, 3), endpoint="stock_daily_bar"
    )
    assert len(clipped) == 2
    assert clipped["trade_date"].to_list() == ["20240102", "20240103"]


def test_fetcher_stage_validate_endpoint_frame_exceptions(tmp_path: Path) -> None:
    fetcher = MagicMock()
    raw_store = MagicMock()
    stage = FetcherStage(fetcher, raw_store, data_source="tushare")

    # 1. 缺少必需列
    df_missing = pl.DataFrame({"invalid_col": [1]})
    with pytest.raises(DataValidationError, match="缺少契约字段"):
        stage.validate_endpoint_frame(
            df_missing, start_date=date(2024, 1, 1), end_date=date(2024, 1, 2), endpoint="stock_daily_bar"
        )

    # 2. 主键空值
    df_null_pk = pl.DataFrame(
        {
            "ts_code": ["600519.SH", None],
            "trade_date": ["20240101", "20240102"],
            "open": [10.0, 10.0],
            "high": [11.0, 11.0],
            "low": [9.0, 9.0],
            "close": [10.5, 10.5],
            "vol": [100.0, 100.0],
            "amount": [1000.0, 1000.0],
        }
    )
    with pytest.raises(DataValidationError, match="主键存在空值"):
        stage.validate_endpoint_frame(
            df_null_pk, start_date=date(2024, 1, 1), end_date=date(2024, 1, 2), endpoint="stock_daily_bar"
        )

    # 3. 主键重复
    df_dup = pl.DataFrame(
        {
            "ts_code": ["600519.SH", "600519.SH"],
            "trade_date": ["20240101", "20240101"],
            "open": [10.0, 10.0],
            "high": [11.0, 11.0],
            "low": [9.0, 9.0],
            "close": [10.5, 10.5],
            "vol": [100.0, 100.0],
            "amount": [1000.0, 1000.0],
        }
    )
    with pytest.raises(DataValidationError, match="主键重复"):
        stage.validate_endpoint_frame(
            df_dup, start_date=date(2024, 1, 1), end_date=date(2024, 1, 2), endpoint="stock_daily_bar"
        )


def test_normalizer_stage_empty_and_inferred_metadata() -> None:
    stage = NormalizerStage(GenericNormalizer(), data_source="yfinance")

    # 空数据帧
    assert stage.normalize(pl.DataFrame(), None, "daily", "req_123").is_empty()

    # 无明确标的结构时根据数据源 yfinance 推断交易所与币种
    df_symbol = pl.DataFrame({"symbol": ["AAPL.US"], "trade_date": ["2024-01-01"]})
    res_us = stage.normalize(df_symbol, None, "daily", "req_123")
    assert res_us["market"][0] == "US"
    assert res_us["currency"][0] == "USD"
    assert res_us["source_endpoint"][0] == "daily"
    assert res_us["schema_version"][0] == "v2"

    # 有 InstrumentId 明确传入
    inst = InstrumentId(
        provider="tushare", symbol="600519.SH", market="CN", exchange="SSE", currency="CNY"
    )
    df_cn = pl.DataFrame({"ts_code": ["600519.SH"], "trade_date": ["20240101"]})
    res_cn = stage.normalize(df_cn, inst, "daily", "req_456")
    assert res_cn["market"][0] == "CN"
    assert res_cn["exchange"][0] == "SSE"
    assert res_cn["currency"][0] == "CNY"


def test_curated_storage_stage(tmp_path: Path) -> None:
    store = MagicMock()
    stage = CuratedStorageStage(store)

    key = DatasetKey(
        provider="tushare",
        dataset="income",
        endpoint="income",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 1),
    )
    df = pl.DataFrame({"symbol": ["600519.SH"], "end_date": ["20240331"]})
    stage.load(key, df, "income")
    store.save_dataset.assert_called_once_with(key, df)
