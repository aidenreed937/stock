"""基础化工期货日线行情采集器与转换器单元测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.chemicals.collectors.futures_price import (
    FuturesPriceCollector,
)
from stock_data.fetcher.industry.chemicals.schemas import (
    CHEMICAL_FUTURES_DAILY_RAW_SCHEMA,
    CHEMICAL_FUTURES_DAILY_SCHEMA,
)
from stock_data.fetcher.industry.chemicals.transforms.futures_price import (
    build_futures_price_curated_frame,
)


def test_futures_price_collector_offline_by_default(tmp_path: Path) -> None:
    """验证 FuturesPriceCollector 默认离线安全，不请求网络。"""
    collector = FuturesPriceCollector(raw_dir=tmp_path, enable_network=False)
    result = collector.collect_result(
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
    )
    assert result.status in {"EMPTY", "SUCCESS", "NO_CHANGE"}
    assert collector.collection_errors == []


def test_futures_price_raw_to_curated_transform() -> None:
    """验证从原始记录构建 RAW 与 Curated DataFrame。"""
    raw_df = pl.DataFrame(
        [
            {
                "trade_date": date(2026, 8, 31),
                "symbol": "SA0",
                "name": "纯碱主力",
                "open_raw": "1450.0",
                "high_raw": "1475.0",
                "low_raw": "1440.0",
                "close_raw": "1468.0",
                "settle_raw": "1465.0",
                "volume_raw": "500000",
                "open_interest_raw": "800000",
                "turnover_raw": "7340000000",
                "change_raw": "18.0",
                "change_pct_raw": "1.24",
                "source": "Sina_Futures",
                "source_url": "https://finance.sina.com.cn/futures/",
                "release_date": date(2026, 8, 31),
                "collected_at": "2026-09-01T00:00:00Z",
                "raw_content_sha256": "sha-test",
                "raw_snapshot_path": "chemicals/futures_daily/SA0_20260831.csv",
            }
        ],
        schema=CHEMICAL_FUTURES_DAILY_RAW_SCHEMA,
    )
    curated = build_futures_price_curated_frame(raw_df)
    assert curated.schema == CHEMICAL_FUTURES_DAILY_SCHEMA
    assert curated["trade_date"][0] == date(2026, 8, 31)
    assert curated["symbol"][0] == "SA0"
    assert curated["close"][0] == 1468.0
    assert curated["settle"][0] == 1465.0
    assert curated["volume"][0] == 500000.0
    assert curated["open_interest"][0] == 800000.0


def test_futures_price_collector_parses_csv(tmp_path: Path) -> None:
    """测试 FuturesPriceCollector 从本地 RAW CSV 解析日线数据。"""
    daily_dir = tmp_path / "chemicals" / "futures_daily"
    daily_dir.mkdir(parents=True)
    sa_csv = daily_dir / "SA.csv"
    sa_csv.write_text(
        "symbol,contract,trade_date,open,high,low,close,settle,volume,open_interest,exchange,source,release_date\n"
        "SA,SA0,2026-08-31,1450.0,1475.0,1440.0,1468.0,1465.0,500000,800000,CZCE,exchange_czce,2026-08-31\n",
        encoding="utf-8",
    )

    collector = FuturesPriceCollector(raw_dir=tmp_path)
    records = collector.collect_symbol("SA")
    assert len(records) == 1
    assert records[0].symbol == "SA"
    assert records[0].contract == "SA0"
    assert records[0].trade_date == date(2026, 8, 31)
    assert records[0].close == 1468.0
    assert records[0].open_interest == 800000.0

    df = collector.build_curated_frame(symbols=["SA"])
    assert not df.is_empty()
    assert df["close"][0] == 1468.0
    assert df["settle"][0] == 1465.0
