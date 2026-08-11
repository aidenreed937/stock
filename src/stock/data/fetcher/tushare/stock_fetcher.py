"""TuShare 股票行情与基本面数据 Fetcher 实现。"""

from datetime import date

import polars as pl

from stock.data.fetcher.tushare.client import TuShareClient
from stock.data.fetcher.tushare.registry import EndpointMeta, TUSHARE_API_REGISTRY
from stock.models.market import DailyBar


class TuShareStockFetcher:
    """TuShare 股票领域专用数据抓取组件。"""

    def __init__(self, client: TuShareClient | None = None) -> None:
        """初始化 TuShareStockFetcher。

        Args:
            client: TuShareClient 实例，若为 None 则自动创建。
        """
        self.client = client or TuShareClient()

    def fetch_daily_bars_df(
        self, symbol: str, start_date: date, end_date: date, endpoint: str = "daily"
    ) -> pl.DataFrame:
        """抓取指定股票或全市场在给定日期范围内的行情/基本面原始数据。

        Args:
            symbol: 股票代码（若为空字符串，则表示抓取全市场指定交易日的数据）。
            start_date: 开始日期。
            end_date: 结束日期。
            endpoint: API 接口名称（默认 daily）。

        Returns:
            pl.DataFrame: 包含 TuShare 原始响应字段的 Polars DataFrame。
        """
        meta = TUSHARE_API_REGISTRY.get(
            endpoint, EndpointMeta(api_name=endpoint, description=endpoint)
        )
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        query_kwargs: dict[str, str] = {}
        if symbol:
            query_kwargs["ts_code"] = symbol
            query_kwargs["start_date"] = start_str
            query_kwargs["end_date"] = end_str
        else:
            if start_date == end_date:
                query_kwargs["trade_date"] = start_str
            else:
                query_kwargs["start_date"] = start_str
                query_kwargs["end_date"] = end_str

        pandas_df = self.client.query(meta.api_name, **query_kwargs)

        if pandas_df.empty:
            return pl.DataFrame()

        return pl.from_pandas(pandas_df)

    def fetch_daily_bars(
        self, symbol: str, start_date: date, end_date: date
    ) -> list[DailyBar]:
        """抓取日 K 线数据并转换为 DailyBar 模型列表。

        Args:
            symbol: 股票代码。
            start_date: 开始日期。
            end_date: 结束日期。

        Returns:
            list[DailyBar]: 转换后的模型列表。
        """
        df = self.fetch_daily_bars_df(symbol, start_date, end_date)
        if df.is_empty():
            return []

        # 简单转换兼容 DailyBar
        bars: list[DailyBar] = []
        for row in df.iter_rows(named=True):
            trade_date_val = row.get("trade_date")
            if isinstance(trade_date_val, str):
                parsed_date = date(
                    int(trade_date_val[:4]),
                    int(trade_date_val[4:6]),
                    int(trade_date_val[6:8]),
                )
            elif isinstance(trade_date_val, date):
                parsed_date = trade_date_val
            else:
                parsed_date = date.today()

            bars.append(
                DailyBar(
                    symbol=row.get("ts_code", symbol),
                    trade_date=parsed_date,
                    open=float(row.get("open", 0.0)),
                    high=float(row.get("high", 0.0)),
                    low=float(row.get("low", 0.0)),
                    close=float(row.get("close", 0.0)),
                    volume=float(row.get("vol", 0.0)),
                    amount=float(row.get("amount", 0.0)) * 1000.0,
                )
            )
        return bars

    def fetch_trade_cal(
        self, start_date: date, end_date: date
    ) -> list[date]:
        """获取指定日期范围内的 A 股有效开市交易日列表。

        Args:
            start_date: 开始日期。
            end_date: 结束日期。

        Returns:
            list[date]: 开市交易日列表（按升序排列）。
        """
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        pandas_df = self.client.query(
            "trade_cal",
            exchange="",
            start_date=start_str,
            end_date=end_str,
            is_open="1",
        )

        if pandas_df.empty or "cal_date" not in pandas_df.columns:
            return []

        open_dates: list[date] = []
        for d_str in pandas_df["cal_date"].to_list():
            if isinstance(d_str, str) and len(d_str) == 8:
                open_dates.append(
                    date(int(d_str[:4]), int(d_str[4:6]), int(d_str[6:8]))
                )
        return sorted(open_dates)
