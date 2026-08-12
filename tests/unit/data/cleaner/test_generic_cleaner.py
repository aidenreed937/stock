"""GenericCleaner 单元测试。"""

from datetime import date
from unittest.mock import MagicMock

import polars as pl
from stock.data.cleaner.generic_cleaner import GenericCleaner
from stock.data.pipeline import MarketDataPipeline


def test_generic_cleaner_dedup_and_nulls():
    # 测试 GenericCleaner 去重与空值过滤
    df = pl.DataFrame(
        [
            {"ts_code": "600000.SH", "trade_date": "20260812", "pe": 10.5},
            {"ts_code": "600000.SH", "trade_date": "20260812", "pe": 11.0},  # 重复项
            {"ts_code": None, "trade_date": "20260812", "pe": 12.0},  # 主键包含 null
        ]
    )

    cleaner = GenericCleaner(primary_keys=["ts_code", "trade_date"])
    cleaned = cleaner.clean(df)

    assert len(cleaned) == 1
    assert cleaned["pe"][0] == 11.0


def test_generic_cleaner_preserve_negative_values():
    # 测试 GenericCleaner 允许负数值 (如亏损企业的净利润)
    df = pl.DataFrame(
        [
            {"ts_code": "000001.SZ", "end_date": "20260630", "n_income": -500000.0},
        ]
    )

    cleaner = GenericCleaner(primary_keys=["ts_code", "end_date"])
    cleaned = cleaner.clean(df)

    assert len(cleaned) == 1
    assert cleaned["n_income"][0] == -500000.0


def test_pipeline_auto_routing_generic_cleaner():
    # 测试 Pipeline 针对非 daily 接口自动匹配 GenericCleaner
    mock_fetcher = MagicMock()
    mock_store = MagicMock()
    mock_raw_store = MagicMock()
    mock_raw_store.load_raw.return_value = None

    pipeline = MarketDataPipeline(
        fetcher=mock_fetcher,
        store=mock_store,
        raw_store=mock_raw_store,
        endpoint="daily_basic",
    )

    assert isinstance(pipeline.cleaner, GenericCleaner)
