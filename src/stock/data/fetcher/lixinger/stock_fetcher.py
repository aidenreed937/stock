"""理杏仁 (Lixinger) 股票领域专用数据抓取组件。"""

from datetime import date, datetime, timedelta
from typing import Any

import polars as pl

from stock.config.loader import load_data_config
from stock.data.fetcher.lixinger.client import LixingerClient
from stock.data.fetcher.lixinger.registry import EndpointMeta, LIXINGER_API_REGISTRY
from stock.models.market import DailyBar
from stock.utils.logger import logger


class LixingerStockFetcher:
    """理杏仁股票领域专用数据抓取器。"""

    def __init__(self, client: LixingerClient | None = None) -> None:
        """初始化 LixingerStockFetcher。

        Args:
            client: LixingerClient 实例，若为 None 则自动创建。
        """
        self.client = client or LixingerClient()

    def fetch_daily_bars_df(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        endpoint: str = "cn/company/fundamental/non_financial",
        **kwargs: Any,
    ) -> pl.DataFrame:
        """抓取指定股票或全市场在给定日期范围内的行情/估值数据。

        Args:
            symbol: 股票代码（如 600519，或者带前缀/后缀）。
            start_date: 开始日期。
            end_date: 结束日期。
            endpoint: API 接口名称（默认 cn/company/fundamental/non_financial）。
            **kwargs: 额外的自定义请求参数。

        Returns:
            pl.DataFrame: 包含理杏仁原始响应字段的 Polars DataFrame。
        """
        meta = LIXINGER_API_REGISTRY.get(
            endpoint, EndpointMeta(api_name=endpoint, description=endpoint)
        )
        # 理杏仁限制单次请求时间跨度不能超过 10 年，若跨度超过 9 年则自动分段拉取
        if (end_date - start_date).days > 3200 and endpoint != "cn/industry/constituents/sw_2021":
            chunks: list[pl.DataFrame] = []
            curr_start = start_date
            while curr_start <= end_date:
                curr_end = min(curr_start + timedelta(days=3200), end_date)
                chunk_df = self.fetch_daily_bars_df(
                    symbol=symbol,
                    start_date=curr_start,
                    end_date=curr_end,
                    endpoint=endpoint,
                    **kwargs,
                )
                if not chunk_df.is_empty():
                    chunks.append(chunk_df)
                curr_start = curr_end + timedelta(days=1)
            if not chunks:
                return pl.DataFrame()
            return pl.concat(chunks).unique()

        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        raw_code = symbol.split(".")[0] if symbol else ""

        query_kwargs: dict[str, Any] = {}
        query_kwargs.update(meta.default_params)

        if meta.default_metrics:
            query_kwargs["metricsList"] = meta.default_metrics

        if "constituents" in endpoint:
            query_kwargs["date"] = start_str
            # 成份股列表查询无需指定单只 stockCodes，理杏仁将全量返回全行业成份股
            if "stockCodes" in query_kwargs:
                query_kwargs.pop("stockCodes", None)
            if "stockCode" in query_kwargs:
                query_kwargs.pop("stockCode", None)
        else:
            query_kwargs["startDate"] = start_str
            query_kwargs["endDate"] = end_str

            if raw_code and raw_code != endpoint and not raw_code.startswith("sw_2021"):
                if meta.code_param_name == "stockCode":
                    query_kwargs["stockCode"] = raw_code
                else:
                    query_kwargs["stockCodes"] = [raw_code]
            elif not query_kwargs.get("stockCodes") and not query_kwargs.get("stockCode"):
                if "index" in endpoint or endpoint == "cn/index/fundamental":
                    data_conf = load_data_config()
                    lx_indices = data_conf.watchlists.lixinger.indices
                    default_code = lx_indices[0] if lx_indices else "000985"
                    query_kwargs["stockCodes"] = [default_code]
                elif "industry" in endpoint or "sw_2021" in endpoint:
                    codes = [
                        "110000", "210000", "220000", "230000", "240000", "270000",
                        "280000", "330000", "340000", "350000", "360000", "370000",
                        "410000", "420000", "430000", "450000", "460000", "480000",
                        "490000", "510000", "610000", "620000", "630000", "640000",
                        "650000", "710000", "720000", "730000", "740000", "750000", "760000", "770000"
                    ]
                    # 申万行业估值接口限制单次只能查询 1 个行业代码，逐个查询并拼接
                    dfs: list[pl.DataFrame] = []
                    for code in codes:
                        sub_kwargs = dict(query_kwargs)
                        sub_kwargs["stockCodes"] = [code]
                        sub_df = self.client.query(meta.api_name, **sub_kwargs)
                        if not sub_df.empty:
                            dfs.append(pl.from_pandas(sub_df))
                    if not dfs:
                        return pl.DataFrame()
                    return pl.concat(dfs, how="diagonal_relaxed")

        # 调用方传入的自定义参数覆盖默认配置
        query_kwargs.update(kwargs)

        pandas_df = self.client.query(meta.api_name, **query_kwargs)

        if pandas_df.empty:
            return pl.DataFrame()

        return pl.from_pandas(pandas_df)

    def fetch_daily_bars(
        self, symbol: str, start_date: date, end_date: date
    ) -> list[DailyBar]:
        """抓取数据并转换为 DailyBar 模型列表。

        Args:
            symbol: 股票代码。
            start_date: 开始日期。
            end_date: 结束日期。

        Returns:
            list[DailyBar]: 转换后的模型列表。
        """
        df = self.fetch_daily_bars_df(symbol, start_date, end_date, endpoint="cn/company/candlestick")
        if df.is_empty():
            return []

        bars: list[DailyBar] = []
        for row in df.iter_rows(named=True):
            trade_date_val = row.get("date") or row.get("trade_date")
            if isinstance(trade_date_val, str):
                parsed_date = datetime.strptime(trade_date_val[:10], "%Y-%m-%d").date()
            elif isinstance(trade_date_val, date):
                parsed_date = trade_date_val
            else:
                parsed_date = date.today()

            code_val = row.get("stockCode", symbol)

            bars.append(
                DailyBar(
                    symbol=str(code_val),
                    trade_date=parsed_date,
                    open=float(row.get("open", row.get("cp", 0.0))),
                    high=float(row.get("high", row.get("cp", 0.0))),
                    low=float(row.get("low", row.get("cp", 0.0))),
                    close=float(row.get("close", row.get("cp", 0.0))),
                    volume=float(row.get("volume", 0.0)),
                    amount=float(row.get("amount", 0.0)),
                )
            )
        return bars

    def fetch_trade_cal(
        self, start_date: date, end_date: date
    ) -> list[date]:
        """获取指定日期范围内的有效交易日列表。

        使用理杏仁指数 K 线数据获取有效交易日。
        """
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        # 使用基准指数 K线查询实际开市日期
        try:
            data_cfg = load_data_config()
            pandas_df = self.client.query(
                "cn/index/candlestick",
                stockCode=data_cfg.default_benchmark_index_code,
                type="normal",
                startDate=start_str,
                endDate=end_str,
            )
        except Exception as e:
            logger.warning(
                f"理杏仁指数 K 线日历获取失败 ({e})，尝试降级使用 TuShare 交易日历或工作日列表..."
            )
            try:
                from stock.data.fetcher.tushare.facade import TuShareDataFetcher
                return TuShareDataFetcher().fetch_trade_cal(start_date, end_date)
            except Exception:
                fallback_dates: list[date] = []
                curr = start_date
                while curr <= end_date:
                    if curr.weekday() < 5:
                        fallback_dates.append(curr)
                    curr += timedelta(days=1)
                return fallback_dates

        if pandas_df.empty or "date" not in pandas_df.columns:
            # 降级退回自然日周一至周五
            weekday_dates: list[date] = []
            curr = start_date
            while curr <= end_date:
                if curr.weekday() < 5:
                    weekday_dates.append(curr)
                curr += timedelta(days=1)
            return weekday_dates

        parsed_dates: list[date] = []
        for d_val in pandas_df["date"].to_list():
            if isinstance(d_val, str):
                parsed_dates.append(datetime.strptime(d_val[:10], "%Y-%m-%d").date())
            elif isinstance(d_val, date):
                parsed_dates.append(d_val)

        return sorted(parsed_dates)
