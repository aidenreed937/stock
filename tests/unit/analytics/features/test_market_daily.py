"""MarketDailyBuilder 单元测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock.analytics.features.builders.market_daily import MarketDailyBuilder
from stock.analytics.features.store import FeatureStore
from stock.data.catalog import DataCatalog


def _prepare_mock_catalog_data(storage_dir: Path) -> None:
    # 1. stock_daily_bar
    bar_dir = storage_dir / "tushare/market=CN/stock_daily_bar/year=2026/month=08"
    bar_dir.mkdir(parents=True, exist_ok=True)
    bars_data = []
    for d in range(1, 15):
        t_date = date(2026, 8, d)
        bars_data.extend(
            [
                {
                    "symbol": "000001.SZ",
                    "trade_date": t_date,
                    "close": 10.0 + d * 0.1,
                    "amount": 100000.0,
                    "schema_version": "v2",
                    "market": "CN",
                },
                {
                    "symbol": "000002.SZ",
                    "trade_date": t_date,
                    "close": 20.0 - d * 0.05,
                    "amount": 200000.0,
                    "schema_version": "v2",
                    "market": "CN",
                },
            ]
        )
    pl.DataFrame(bars_data).write_parquet(bar_dir / "data.parquet")

    # 2. margin
    margin_dir = storage_dir / "tushare/market=CN/margin/year=2026/month=08"
    margin_dir.mkdir(parents=True, exist_ok=True)
    margin_data = []
    for d in range(1, 15):
        for ex in ("SSE", "SZSE", "BSE"):
            margin_data.append(
                {
                    "trade_date": date(2026, 8, d),
                    "exchange_id": ex,
                    "rzrqye": 500000.0,
                    "rzmre": 10000.0,
                    "schema_version": "v2",
                    "market": "CN",
                }
            )
    pl.DataFrame(margin_data).write_parquet(margin_dir / "data.parquet")

    # 3. daily_basic
    basic_dir = storage_dir / "tushare/market=CN/daily_basic/year=2026/month=08"
    basic_dir.mkdir(parents=True, exist_ok=True)
    basic_data = []
    for d in range(1, 15):
        t_date = date(2026, 8, d)
        basic_data.extend(
            [
                {
                    "symbol": "000001.SZ",
                    "trade_date": t_date,
                    "turnover_rate_f": 2.5,
                    "schema_version": "v2",
                    "market": "CN",
                },
                {
                    "symbol": "000002.SZ",
                    "trade_date": t_date,
                    "turnover_rate_f": 1.5,
                    "schema_version": "v2",
                    "market": "CN",
                },
            ]
        )
    pl.DataFrame(basic_data).write_parquet(basic_dir / "data.parquet")


def test_market_daily_builder_full(tmp_path: Path) -> None:
    _prepare_mock_catalog_data(tmp_path)
    catalog = DataCatalog(data_source="tushare", storage_dir=tmp_path)
    store = FeatureStore(mart_dir=tmp_path / "mart")

    builder = MarketDailyBuilder(catalog=catalog, store=store)
    df = builder.build(start_date=date(2026, 8, 1), end_date=date(2026, 8, 14), save=True)

    assert not df.is_empty()
    assert len(df) == 14
    assert "total_turnover" in df.columns
    assert "adv_dec_ratio" in df.columns
    assert "advance_ratio" in df.columns
    assert "above_ma20_ratio" in df.columns
    assert "margin_balance" in df.columns
    assert "margin_buy_ratio" in df.columns
    assert "market_turnover_rate" in df.columns

    # 验证 FeatureStore 已保存
    persisted = store.get_market_daily()
    assert len(persisted) == 14
    assert persisted["total_turnover"][0] == 300000.0
