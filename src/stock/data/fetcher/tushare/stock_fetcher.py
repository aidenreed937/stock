"""TuShare 股票行情与基本面数据 Fetcher 实现。"""

from datetime import date
from typing import Any

import polars as pl

from stock.data.fetcher.base import BaseDataFetcher
from stock.data.fetcher.tushare.client import TuShareClient
from stock.data.fetcher.tushare.registry import EndpointMeta, TUSHARE_API_REGISTRY
from stock.models.market import DailyBar


TUSHARE_INDEX_DAILYBASIC_SUPPORTED_CODES = {
    "000001.SH", "399001.SZ", "000300.SH", "000905.SH", "399006.SZ"
}


class TuShareStockFetcher(BaseDataFetcher):
    """TuShare 股票领域专用数据抓取组件。"""

    def __init__(self, client: TuShareClient | None = None) -> None:
        """初始化 TuShareStockFetcher。

        Args:
            client: TuShareClient 实例，若为 None 则自动创建。
        """
        self.client = client or TuShareClient()

    def fetch_daily_bars_df(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        endpoint: str = "daily",
        **extra_kwargs: Any,
    ) -> pl.DataFrame:
        """抓取指定股票或全市场在给定日期范围内的行情/基本面原始数据。

        Args:
            symbol: 股票代码（若为空字符串，则表示抓取全市场指定交易日的数据）。
            start_date: 开始日期。
            end_date: 结束日期。
            endpoint: API 接口名称（默认 daily）。
            extra_kwargs: 额外的 API 查询参数 (如 exchange_id)。

        Returns:
            pl.DataFrame: 包含 TuShare 原始响应字段的 Polars DataFrame。
        """
        meta = TUSHARE_API_REGISTRY.get(
            endpoint, EndpointMeta(api_name=endpoint, description=endpoint)
        )
        if endpoint == "index_dailybasic" and symbol and symbol not in TUSHARE_INDEX_DAILYBASIC_SUPPORTED_CODES:
            from stock.utils.logger import logger
            logger.info(
                f"TuShare index_dailybasic 接口不支持指数 [{symbol}]，自动跳过请求以节省流量和额度"
            )
            return pl.DataFrame()

        # 最外层防御性拦截：针对 margin 接口自动按交易所拆分与最早上线首日过滤
        if endpoint == "margin" and "exchange_id" not in extra_kwargs:
            from stock.config.loader import load_data_config
            from stock.utils.logger import logger

            data_cfg = load_data_config()
            ex_dates = getattr(getattr(data_cfg, "exchange_start_dates", None), "margin", {})

            dfs: list[pl.DataFrame] = []
            for ex in ["SSE", "SZSE", "BSE"]:
                min_start_str = (
                    getattr(ex_dates, ex, None)
                    if hasattr(ex_dates, ex)
                    else (ex_dates.get(ex) if isinstance(ex_dates, dict) else None)
                )
                if min_start_str:
                    min_start_d = date.fromisoformat(min_start_str)
                    if end_date < min_start_d:
                        logger.info(
                            f"接口 [margin] 自动拦截跳过交易所 [{ex}]: 请求终止日 [{end_date}] 早于官方上线首日 [{min_start_d}]"
                        )
                        continue
                    sub_start_d = max(start_date, min_start_d)
                else:
                    sub_start_d = start_date

                sub_df = self.fetch_daily_bars_df(
                    symbol=symbol,
                    start_date=sub_start_d,
                    end_date=end_date,
                    endpoint=endpoint,
                    exchange_id=ex,
                )
                if not sub_df.is_empty():
                    dfs.append(sub_df)

            if not dfs:
                return pl.DataFrame()
            merged = pl.concat(dfs, how="diagonal_relaxed")
            return merged

        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        query_kwargs: dict[str, Any] = dict(extra_kwargs)
        is_real_symbol = symbol and (symbol != endpoint)

        if meta.frequency == "event":
            if is_real_symbol:
                if endpoint in ("index_weight", "index_classify", "index_member"):
                    query_kwargs["index_code"] = symbol
                else:
                    query_kwargs["ts_code"] = symbol
            if endpoint == "stock_basic" and not is_real_symbol:
                query_kwargs["list_status"] = "L"
        else:
            if is_real_symbol:
                if endpoint in ("index_weight", "index_classify", "index_member"):
                    query_kwargs["index_code"] = symbol
                else:
                    query_kwargs["ts_code"] = symbol
                query_kwargs["start_date"] = start_str
                query_kwargs["end_date"] = end_str
            else:
                if start_date == end_date:
                    query_kwargs["trade_date"] = start_str
                elif (end_date - start_date).days >= (meta.request_window_days or 300):
                    from datetime import timedelta

                    window_days = meta.request_window_days or 300
                    cur_d = start_date
                    frames: list[pl.DataFrame] = []
                    while cur_d <= end_date:
                        next_d = min(cur_d + timedelta(days=window_days - 1), end_date)
                        sub_df = self.fetch_daily_bars_df(
                            symbol=symbol,
                            start_date=cur_d,
                            end_date=next_d,
                            endpoint=endpoint,
                            **extra_kwargs,
                        )
                        if not sub_df.is_empty():
                            frames.append(sub_df)
                        cur_d = next_d + timedelta(days=1)
                    if not frames:
                        return pl.DataFrame()
                    merged = pl.concat(frames, how="diagonal_relaxed")
                    primary_keys = [c for c in meta.primary_keys if c in merged.columns]
                    if primary_keys:
                        merged = merged.unique(subset=primary_keys, keep="last")
                    if "trade_date" in merged.columns:
                        merged = merged.sort("trade_date")
                    return merged
                else:
                    query_kwargs["start_date"] = start_str
                    query_kwargs["end_date"] = end_str

        pandas_df = self.client.query(meta.api_name, **query_kwargs)

        if pandas_df.empty:
            return pl.DataFrame()

        pl_df = pl.from_pandas(pandas_df)
        if "symbol" not in pl_df.columns and symbol:
            pl_df = pl_df.with_columns(pl.lit(symbol).alias("symbol"))
        # 事件型接口可能返回重复页或重复关系，按注册表自然键去重，保留有效期字段。
        primary_keys = [key for key in meta.primary_keys if key in pl_df.columns]
        if primary_keys:
            pl_df = pl_df.unique(subset=primary_keys, keep="last")
        return pl_df

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

        from stock.data.normalizer.unit_normalizer import UnitNormalizer
        norm_df = UnitNormalizer("tushare", "daily").normalize_units(df)

        bars: list[DailyBar] = []
        for row in norm_df.iter_rows(named=True):
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

            vol_val = row.get("volume", row.get("vol", 0.0))
            amt_val = row.get("amount", 0.0)

            bars.append(
                DailyBar(
                    symbol=row.get("ts_code", symbol),
                    trade_date=parsed_date,
                    open=float(row.get("open", 0.0)),
                    high=float(row.get("high", 0.0)),
                    low=float(row.get("low", 0.0)),
                    close=float(row.get("close", 0.0)),
                    volume=float(vol_val or 0.0),
                    amount=float(amt_val or 0.0),
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
