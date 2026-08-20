from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import polars as pl
import pytest

from stock_core.contracts import DatasetKey, InstrumentId
from stock_core.exceptions import DataValidationError
from stock_data.governance.quality.quarantine import QuarantineStore
from stock_data.pipeline.normalizer.generic_normalizer import GenericNormalizer
from stock_data.pipeline.stages import (
    CuratedStorageStage,
    FetcherStage,
    NormalizerStage,
)
from stock_data.storage.raw_store import RawDataStorage


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


def test_fetcher_stage_clip_financial_statement_by_report_period() -> None:
    stage = FetcherStage(MagicMock(), MagicMock(), data_source="tushare")
    df = pl.DataFrame(
        {
            "ts_code": ["600519.SH", "600519.SH"],
            "ann_date": ["20260425", "20260725"],
            "end_date": ["20260331", "20260630"],
            "revenue": [10.0, 20.0],
        }
    )

    clipped = stage.clip_date_range(
        df, start_date=date(2026, 3, 31), end_date=date(2026, 3, 31), endpoint="balancesheet"
    )

    assert len(clipped) == 1
    assert clipped["end_date"].to_list() == ["20260331"]


def test_fetcher_stage_keeps_announcement_date_for_pit_quarterly_task() -> None:
    stage = FetcherStage(MagicMock(), MagicMock(), data_source="tushare")
    df = pl.DataFrame(
        {
            "ts_code": ["600519.SH", "600519.SH"],
            "ann_date": ["20260425", "20260725"],
            "end_date": ["20260331", "20260630"],
            "p_change_min": [1.0, 2.0],
        }
    )

    clipped = stage.clip_date_range(
        df, start_date=date(2026, 4, 1), end_date=date(2026, 6, 30), endpoint="forecast"
    )

    assert len(clipped) == 1
    assert clipped["ann_date"].to_list() == ["20260425"]


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
            df_missing,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 2),
            endpoint="stock_daily_bar",
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
            df_null_pk,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 2),
            endpoint="stock_daily_bar",
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
            df_dup,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 2),
            endpoint="stock_daily_bar",
        )


def test_fetcher_stage_validates_normalized_margin_primary_key() -> None:
    stage = FetcherStage(MagicMock(), MagicMock(), data_source="tushare")
    mixed_date_df = pl.DataFrame(
        {
            "trade_date": ["20240102", "2024-01-02"],
            "exchange_id": ["SSE", "SSE"],
            "rzye": [100.0, 100.0],
        }
    )

    with pytest.raises(DataValidationError, match="主键重复"):
        stage.validate_endpoint_frame(
            mixed_date_df,
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
            endpoint="margin",
        )


def test_fetcher_stage_allows_nullable_block_trade_counterparty_keys() -> None:
    stage = FetcherStage(MagicMock(), MagicMock(), data_source="tushare")
    frame = pl.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20140821"],
            "price": [84.0],
            "vol": [3.3],
            "amount": [277.2],
            "buyer": [None],
            "seller": [None],
        }
    )

    stage.validate_endpoint_frame(
        frame,
        start_date=date(2014, 8, 1),
        end_date=date(2014, 8, 31),
        endpoint="block_trade",
    )


def test_fetcher_stage_validates_yfinance_history_contract() -> None:
    stage = FetcherStage(MagicMock(), MagicMock(), data_source="yfinance")
    frame = pl.DataFrame(
        {
            "symbol": ["AAPL"],
            "trade_date": [date(2026, 8, 17)],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
        }
    )

    stage.validate_endpoint_frame(
        frame,
        start_date=date(2026, 8, 17),
        end_date=date(2026, 8, 17),
        endpoint="stock_daily_bar",
    )


def test_fetcher_stage_validates_fred_series_contract() -> None:
    stage = FetcherStage(MagicMock(), MagicMock(), data_source="fred")
    frame = pl.DataFrame(
        {
            "symbol": ["FEDFUNDS"],
            "trade_date": [date(2026, 8, 17)],
            "value": [4.33],
        }
    )

    stage.validate_endpoint_frame(
        frame,
        start_date=date(2026, 8, 17),
        end_date=date(2026, 8, 17),
        endpoint="FEDFUNDS",
    )


def test_fetcher_stage_saves_unclipped_raw_before_returning_clipped_frame() -> None:
    fetcher = MagicMock()
    raw_store = MagicMock()
    raw_store.load_dataset.return_value = None
    stage = FetcherStage(fetcher, raw_store, data_source="tushare")
    source_df = pl.DataFrame(
        {
            "ts_code": ["600519.SH", "600519.SH", "600519.SH"],
            "trade_date": ["20240101", "20240102", "20240103"],
            "open": [10.0, 11.0, 12.0],
            "high": [10.5, 11.5, 12.5],
            "low": [9.5, 10.5, 11.5],
            "close": [10.2, 11.2, 12.2],
            "vol": [100.0, 110.0, 120.0],
            "amount": [1000.0, 1100.0, 1200.0],
        }
    )
    fetcher.fetch_daily_bars_df.return_value = source_df
    key = DatasetKey(
        provider="tushare",
        dataset="stock_daily_bar",
        endpoint="stock_daily_bar",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
    )

    result = stage.extract(
        symbol="600519.SH",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
        key=key,
        api_name="daily",
        endpoint_name="stock_daily_bar",
    )

    saved_df = raw_store.save_dataset.call_args.args[1]
    assert saved_df.to_dict(as_series=False) == source_df.to_dict(as_series=False)
    assert result["trade_date"].to_list() == ["20240102"]


def test_fetcher_stage_quarantines_incomplete_margin_after_raw_save(tmp_path: Path) -> None:
    fetcher = MagicMock()
    fetcher.fetch_daily_bars_df.return_value = pl.DataFrame(
        {
            "trade_date": ["20260814"],
            "exchange_id": ["SSE"],
            "rzye": [100.0],
            "rqye": [1.0],
        }
    )
    raw_store = RawDataStorage(base_dir=tmp_path / "raw")
    stage = FetcherStage(
        fetcher,
        raw_store,
        data_source="tushare",
        quarantine=QuarantineStore(tmp_path / "quarantine"),
    )
    target_date = date(2026, 8, 14)
    key = DatasetKey(
        provider="tushare",
        dataset="margin",
        endpoint="margin",
        start_date=target_date,
        end_date=target_date,
    )

    with pytest.raises(DataValidationError, match="交易所覆盖不完整"):
        stage.extract(
            symbol="margin",
            start_date=target_date,
            end_date=target_date,
            key=key,
            api_name="margin",
            endpoint_name="margin",
        )

    raw_path = tmp_path / "raw/tushare/market=CN/margin/data.parquet"
    quarantine_path = tmp_path / "quarantine/endpoint=margin/records.parquet"
    assert raw_path.exists()
    assert raw_store.load_dataset(key) is None
    assert not raw_store.has_raw("tushare", "margin", target_date)
    assert quarantine_path.exists()
    assert (
        "incomplete_exchange_coverage"
        in pl.read_parquet(quarantine_path)["quarantine_reason"].to_list()[0]
    )


def test_curated_stage_rejects_incomplete_margin() -> None:
    store = MagicMock()
    stage = CuratedStorageStage(store)
    target_date = date(2026, 8, 14)
    key = DatasetKey(
        provider="tushare",
        dataset="margin",
        endpoint="margin",
        start_date=target_date,
        end_date=target_date,
    )
    df = pl.DataFrame(
        {
            "trade_date": [target_date],
            "exchange_id": ["SSE"],
            "rzye": [100.0],
        }
    )

    with pytest.raises(DataValidationError, match="交易所覆盖不完整"):
        stage.load(key, df, "margin")
    store.save_dataset.assert_not_called()


def test_fetcher_stage_refreshes_incompatible_lixinger_cache() -> None:
    fetcher = MagicMock()
    raw_store = MagicMock()
    raw_store.load_dataset.return_value = pl.DataFrame({"symbol": ["110000"], "constituents": [[]]})
    fresh_df = pl.DataFrame({"industryCode": ["110000"], "stockCode": ["600519"], "market": ["CN"]})
    fetcher.fetch_daily_bars_df.return_value = fresh_df
    stage = FetcherStage(fetcher, raw_store, data_source="lixinger")
    key = DatasetKey(
        provider="lixinger",
        dataset="sw_2021_constituents",
        endpoint="sw_2021_constituents",
        start_date=date(2026, 8, 15),
        end_date=date(2026, 8, 15),
    )

    result = stage.extract(
        symbol="",
        start_date=date(2026, 8, 15),
        end_date=date(2026, 8, 15),
        key=key,
        api_name="cn/industry/constituents/sw_2021",
        endpoint_name="sw_2021_constituents",
    )

    assert result.equals(fresh_df)
    raw_store.save_dataset.assert_called_once_with(key, fresh_df, replace_existing=True)


def test_fetcher_stage_accepts_normalized_lixinger_cache_aliases() -> None:
    stage = FetcherStage(MagicMock(), MagicMock(), data_source="lixinger")

    stage.validate_endpoint_frame(
        pl.DataFrame({"symbol": ["110000"], "trade_date": ["2024-01-02"], "pe_ttm.ew": [20.0]}),
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
        endpoint="sw_2021_fundamental",
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

    # yfinance 宏观端点的逻辑市场固定为 GLOBAL，不受标的后缀推断影响。
    macro_inst = InstrumentId(
        provider="yfinance",
        symbol="DX-Y.NYB",
        market="NYB",
        exchange="NYB_EXCHANGE",
        currency="USD",
    )
    df_macro = pl.DataFrame({"symbol": ["DX-Y.NYB"], "trade_date": ["20240801"]})
    res_macro = stage.normalize(
        df_macro,
        macro_inst,
        "macro_indicators",
        "req_macro",
        dataset="macro_indicators",
    )
    assert res_macro["market"][0] == "GLOBAL"
    assert res_macro["exchange"][0] == "GLOBAL"
    assert res_macro["currency"][0] == "USD"


def test_normalizer_stage_uses_margin_exchange_id_metadata() -> None:
    stage = NormalizerStage(GenericNormalizer(), data_source="tushare")

    result = stage.normalize(
        pl.DataFrame(
            {
                "trade_date": ["20240801"],
                "exchange_id": ["bse"],
                "rzye": [100.0],
            }
        ),
        None,
        "margin",
        "req_margin",
        dataset="margin",
    )

    assert result["market"][0] == "CN"
    assert result["exchange"][0] == "BSE"
    assert result["currency"][0] == "CNY"


def test_normalizer_stage_adds_stable_identity_for_period_macro_dataset() -> None:
    stage = NormalizerStage(GenericNormalizer(), data_source="tushare")

    result = stage.normalize(
        pl.DataFrame({"month": ["202607"], "m2": [300000.0]}),
        None,
        "cn_m",
        "req_macro",
        dataset="cn_m",
    )

    assert result["symbol"].to_list() == ["cn_m"]


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
