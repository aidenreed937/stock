from datetime import date
import polars as pl
from stock.data.cleaner.bar_cleaner import BarDataCleaner


def test_bar_cleaner_handles_suspended_trading_day() -> None:
    cleaner = BarDataCleaner()
    # 构造包含正常停牌 (vol=0, close=10.0, open=0, high=0, low=0) 与非法价格的数据帧
    df = pl.DataFrame(
        {
            "symbol": ["600000.SH", "600001.SH", "600002.SH"],
            "trade_date": [date(2026, 8, 12), date(2026, 8, 12), date(2026, 8, 12)],
            "open": [0.0, 10.0, -1.0],
            "high": [0.0, 11.0, 10.0],
            "low": [0.0, 9.0, 8.0],
            "close": [10.0, 10.5, 9.0],
            "volume": [0.0, 1000.0, 1000.0],
            "amount": [0.0, 10500.0, 9000.0],
        }
    )

    cleaned = cleaner.clean(df)
    # 600000.SH 停牌记录被保留并填充开高低，600001.SH 正常保留，600002.SH 负价格被剔除
    assert len(cleaned) == 2
    symbols = cleaned["symbol"].to_list()
    assert "600000.SH" in symbols
    assert "600001.SH" in symbols
    assert "600002.SH" not in symbols

    suspended_row = cleaned.filter(pl.col("symbol") == "600000.SH")
    assert suspended_row["open"][0] == 10.0
    assert suspended_row["high"][0] == 10.0
    assert suspended_row["low"][0] == 10.0
    assert suspended_row["close"][0] == 10.0
    assert suspended_row["volume"][0] == 0.0
