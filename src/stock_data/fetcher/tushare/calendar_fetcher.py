"""TuShare 交易日历抓取逻辑。"""

from datetime import date

import polars as pl

from stock_data.catalog import DataCatalog
from stock_data.fetcher.tushare.client import TuShareClient


def fetch_trade_cal_data(client: TuShareClient, start_date: date, end_date: date) -> list[date]:
    """优先从本地交易日历读取，缺口时查询 TuShare。"""
    try:
        df = DataCatalog(data_source="tushare").load_dataset("trade_cal")
        if not df.is_empty():
            date_col = (
                "cal_date"
                if "cal_date" in df.columns
                else ("trade_date" if "trade_date" in df.columns else "")
            )
            if date_col:
                if "is_open" in df.columns:
                    df = df.filter(pl.col("is_open").cast(pl.Int32, strict=False) == 1)
                raw_dates = df[date_col].to_list()
                dates = sorted(
                    {
                        value if isinstance(value, date) else date.fromisoformat(str(value))
                        for value in raw_dates
                        if value is not None
                    }
                )
                if dates and dates[0] <= start_date and dates[-1] >= end_date:
                    return [value for value in dates if start_date <= value <= end_date]
    except Exception:
        pass

    pandas_df = client.query(
        "trade_cal",
        exchange="",
        start_date=start_date.strftime("%Y%m%d"),
        end_date=end_date.strftime("%Y%m%d"),
        is_open="1",
    )
    if pandas_df.empty or "cal_date" not in pandas_df.columns:
        return []
    return sorted(
        [
            date(int(value[:4]), int(value[4:6]), int(value[6:8]))
            for value in pandas_df["cal_date"].to_list()
            if isinstance(value, str) and len(value) == 8
        ]
    )
