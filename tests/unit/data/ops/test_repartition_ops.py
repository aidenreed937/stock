from datetime import date, datetime, timezone
from pathlib import Path
import polars as pl
import pytest

from stock.data.ops.repartition import repartition_all_curated


def test_repartition_all_curated_nonexistent_dir() -> None:
    # 路径不存在时优雅退出
    repartition_all_curated("/nonexistent/path/for/test")


def test_repartition_all_curated_success(tmp_path: Path) -> None:
    # 构造跨月份的脏分区数据，符合 Exact Schema
    base_dir = tmp_path / "curated"
    p = base_dir / "tushare" / "market=CN" / "stock_daily_bar" / "year=2024" / "month=01" / "data.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)

    now_utc = datetime.now(timezone.utc)
    df = pl.DataFrame(
        {
            "symbol": ["600519.SH", "600519.SH"],
            "trade_date": [date(2024, 1, 15), date(2024, 2, 15)],  # 2 月份数据混在 1 月分区
            "open": [1790.0, 1810.0],
            "high": [1810.0, 1830.0],
            "low": [1780.0, 1800.0],
            "close": [1800.0, 1820.0],
            "volume": [1000.0, 1000.0],
            "amount": [1800000.0, 1820000.0],
            "data_source": ["tushare", "tushare"],
            "source_endpoint": ["stock_daily_bar", "stock_daily_bar"],
            "market": ["CN", "CN"],
            "exchange": ["SSE", "SSE"],
            "currency": ["CNY", "CNY"],
            "adjustment": ["raw", "raw"],
            "schema_version": ["v2", "v2"],
            "updated_at": [now_utc, now_utc],
        }
    )
    df.write_parquet(p)

    repartition_all_curated(str(base_dir))

    # 验证自动拆分出了 month=01 和 month=02 两个新分区
    p1 = base_dir / "tushare" / "market=CN" / "stock_daily_bar" / "year=2024" / "month=01" / "data.parquet"
    p2 = base_dir / "tushare" / "market=CN" / "stock_daily_bar" / "year=2024" / "month=02" / "data.parquet"
    assert p1.exists()
    assert p2.exists()
    assert len(pl.read_parquet(p1)) == 1
    assert len(pl.read_parquet(p2)) == 1
