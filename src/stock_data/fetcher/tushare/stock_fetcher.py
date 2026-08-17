"""TuShare 股票行情与基本面数据 Fetcher 实现。"""

from datetime import date, timedelta
from typing import Any

import polars as pl

from stock_core.models.market import DailyBar
from stock_core.utils.logger import logger
from stock_data.constants import EXCHANGE_START_DATES
from stock_data.fetcher.base import BaseDataFetcher
from stock_data.fetcher.tushare.client import TuShareClient
from stock_data.fetcher.tushare.query_builder import (
    build_tushare_query,
    is_index_dailybasic_supported,
    post_process_tushare_frame,
    should_split_margin_exchanges,
)
from stock_data.fetcher.tushare.registry import TUSHARE_API_REGISTRY, EndpointMeta


class TuShareStockFetcher(BaseDataFetcher):
    """TuShare 股票领域专用数据抓取组件。"""

    def __init__(self, client: TuShareClient | None = None) -> None:
        """初始化 TuShareStockFetcher。"""
        self.client = client or TuShareClient()

    def _fetch_split_exchanges(
        self, symbol: str, start_date: date, end_date: date, endpoint: str
    ) -> pl.DataFrame:
        """按交易所拆分并行请求并合并数据。"""
        ex_dates = EXCHANGE_START_DATES.get("margin", {})
        dfs = [
            self.fetch_daily_bars_df(
                symbol=symbol,
                start_date=max(start_date, date.fromisoformat(ex_dates[ex]))
                if ex in ex_dates
                else start_date,
                end_date=end_date,
                endpoint=endpoint,
                exchange_id=ex,
            )
            for ex in ["SSE", "SZSE", "BSE"]
            if not (ex in ex_dates and end_date < date.fromisoformat(ex_dates[ex]))
        ]
        valid_dfs = [df for df in dfs if not df.is_empty()]
        return pl.concat(valid_dfs, how="diagonal_relaxed") if valid_dfs else pl.DataFrame()

    def _fetch_windowed(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        endpoint: str,
        meta: EndpointMeta,
        extra_kwargs: dict[str, Any],
    ) -> pl.DataFrame:
        """按窗口分片循环拉取长周期数据并合并。"""
        window_days = meta.request_window_days or 300
        cur_d = start_date
        frames: list[pl.DataFrame] = []
        while cur_d <= end_date:
            next_d = min(cur_d + timedelta(days=window_days - 1), end_date)
            sub_df = self.fetch_daily_bars_df(
                symbol=symbol, start_date=cur_d, end_date=next_d, endpoint=endpoint, **extra_kwargs
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

    def _fetch_all_industry_classifies(self, meta: EndpointMeta, symbol: str) -> pl.DataFrame:
        """同时拉取 SW2021 与 SW2014 标准的行业分类元数据并合并。"""
        frames: list[pl.DataFrame] = []
        for src_ver in ["SW2021", "SW2014"]:
            pdf = self.client.query("index_classify", src=src_ver)
            if not pdf.empty:
                df = post_process_tushare_frame(pdf, meta, symbol)
                if not df.is_empty():
                    frames.append(df)
        return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()

    def fetch_daily_bars_df(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        endpoint: str = "daily",
        **extra_kwargs: Any,
    ) -> pl.DataFrame:
        """抓取指定股票或全市场在给定日期范围内的行情/基本面原始数据。"""
        meta = TUSHARE_API_REGISTRY.get(
            endpoint, EndpointMeta(api_name=endpoint, description=endpoint)
        )
        if not is_index_dailybasic_supported(endpoint, symbol):
            logger.info(f"TuShare index_dailybasic 不支持指数 [{symbol}]，自动跳过")
            return pl.DataFrame()

        if should_split_margin_exchanges(endpoint, extra_kwargs):
            return self._fetch_split_exchanges(symbol, start_date, end_date, endpoint)

        if endpoint == "index_classify" and "src" not in extra_kwargs:
            return self._fetch_all_industry_classifies(meta, symbol)

        is_real_symbol = bool(symbol and (symbol != endpoint))
        if (
            not is_real_symbol
            and meta.frequency not in ("event", "static")
            and endpoint != "trade_cal"
            and start_date != end_date
        ):
            if (end_date - start_date).days >= (meta.request_window_days or 300):
                return self._fetch_windowed(
                    symbol, start_date, end_date, endpoint, meta, extra_kwargs
                )

        api_to_call, query_kwargs = build_tushare_query(
            meta, symbol, start_date, end_date, extra_kwargs
        )
        pandas_df = self.client.query(api_to_call, **query_kwargs)
        return post_process_tushare_frame(pandas_df, meta, symbol)

    def fetch_daily_bars(self, symbol: str, start_date: date, end_date: date) -> list[DailyBar]:
        """抓取日 K 线数据并转换为 DailyBar 模型列表。"""
        df = self.fetch_daily_bars_df(symbol, start_date, end_date)
        if df.is_empty():
            return []

        from stock_data.normalizer.unit_normalizer import UnitNormalizer

        norm_df = UnitNormalizer("tushare", "daily").normalize_units(df)
        bars: list[DailyBar] = []
        for row in norm_df.iter_rows(named=True):
            d_val = row.get("trade_date")
            p_date = (
                date(int(d_val[:4]), int(d_val[4:6]), int(d_val[6:8]))
                if isinstance(d_val, str) and len(d_val) == 8
                else (d_val if isinstance(d_val, date) else date.today())
            )
            bars.append(
                DailyBar(
                    symbol=row.get("ts_code", symbol),
                    trade_date=p_date,
                    open=float(row.get("open", 0.0)),
                    high=float(row.get("high", 0.0)),
                    low=float(row.get("low", 0.0)),
                    close=float(row.get("close", 0.0)),
                    volume=float(row.get("volume", row.get("vol", 0.0)) or 0.0),
                    amount=float(row.get("amount", 0.0) or 0.0),
                )
            )
        return bars

    def fetch_trade_cal(self, start_date: date, end_date: date) -> list[date]:
        """获取指定日期范围内的 A 股有效开市交易日列表（优先本地黄金表，未命中查询 API）。"""
        try:
            from stock_data.catalog import DataCatalog

            cat = DataCatalog(data_source="tushare")
            df = cat.load_dataset("trade_cal")
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
                            d if isinstance(d, date) else date.fromisoformat(str(d))
                            for d in raw_dates
                            if d is not None
                        }
                    )
                    if dates and dates[0] <= start_date and dates[-1] >= end_date:
                        return [d for d in dates if start_date <= d <= end_date]
        except Exception:
            pass

        pandas_df = self.client.query(
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
                date(int(d[:4]), int(d[4:6]), int(d[6:8]))
                for d in pandas_df["cal_date"].to_list()
                if isinstance(d, str) and len(d) == 8
            ]
        )
