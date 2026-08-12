import logging
from datetime import date, timedelta
from typing import Any

import polars as pl

from stock.data.fetcher.base import BaseDataFetcher
from stock.data.fetcher.yfinance.client import YFinanceClient
from stock.data.fetcher.yfinance.registry import YFINANCE_API_REGISTRY
from stock.models.market import DailyBar, IndexValuation

logger = logging.getLogger(__name__)


class YFinanceDataFetcher(BaseDataFetcher):
    """Yahoo Finance 规范化行情抓取实现。"""

    def __init__(self, client: YFinanceClient) -> None:
        """初始化 YFinanceDataFetcher。

        Args:
            client: YFinanceClient 实例。
        """
        self.client = client

    def fetch_trade_cal(self, start_date: date, end_date: date) -> list[date]:
        """获取交易日历（过滤周末）。"""
        cur = start_date
        open_dates: list[date] = []
        while cur <= end_date:
            if cur.weekday() < 5:
                open_dates.append(cur)
            cur += timedelta(days=1)
        return open_dates

    def fetch_daily_bars(
        self, symbol: str, start_date: date, end_date: date
    ) -> list[DailyBar]:
        """抓取指定标的代码的 K 线数据，转化为标准 DailyBar 模型。"""
        # yfinance 结束日期是 exclusive，加1天以包含该日期
        end_date_ex = end_date + timedelta(days=1)

        logger.info(f"YFinance 抓取 {symbol} 行情 (区间: {start_date} ~ {end_date})")

        try:
            df = self.client.query_history(
                symbol=symbol,
                start_date_str=start_date.isoformat(),
                end_date_str=end_date_ex.isoformat(),
            )

            if df.empty:
                logger.warning(f"YFinance 返回空数据: {symbol}")
                return []

            bars: list[DailyBar] = []
            for dt, row_series in df.iterrows():
                row: Any = row_series
                trade_date = dt.date() if hasattr(dt, "date") else dt
                volume = float(row["Volume"])
                close_price = float(row["Close"])
                amount = round(volume * close_price, 2)

                bars.append(
                    DailyBar(
                        symbol=symbol,
                        trade_date=trade_date,
                        open=round(float(row["Open"]), 4),
                        high=round(float(row["High"]), 4),
                        low=round(float(row["Low"]), 4),
                        close=round(close_price, 4),
                        volume=volume,
                        amount=amount,
                    )
                )
            logger.info(f"YFinance 成功抓取 {symbol} 共 {len(bars)} 条记录")
            return bars

        except Exception as e:
            logger.error(f"YFinance 抓取 {symbol} 失败: {e}", exc_info=True)
            return []

    def fetch_daily_bars_df(
        self, symbol: str, start_date: date, end_date: date, endpoint: str = "history"
    ) -> pl.DataFrame:
        """抓取指定标的行情数据，返回 Polars DataFrame。"""
        meta = YFINANCE_API_REGISTRY.get(endpoint)
        if not meta:
            logger.warning(f"未在注册表中找到 YFinance endpoint: {endpoint}")

        bars = self.fetch_daily_bars(symbol, start_date, end_date)
        if not bars:
            return pl.DataFrame()

        data_dicts = [bar.model_dump() for bar in bars]
        return pl.DataFrame(data_dicts)

    def fetch_index_valuations(
        self, etf_map: dict[str, str] | None = None, target_date: date | None = None
    ) -> list[IndexValuation]:
        """使用核心追踪 ETF (SPY/QQQ/DIA 等) 提取美股指数级实时估值指标。"""
        import yfinance as yf

        mapping = etf_map or {
            "SPY": "^GSPC",
            "QQQ": "^IXIC",
            "DIA": "^DJI",
            "SOXX": "^SOX",
            "IWM": "^RUT",
        }
        val_date = target_date or date.today()
        results: list[IndexValuation] = []

        session = self.client._get_session()
        for etf_symbol, target_index in mapping.items():
            try:
                ticker = yf.Ticker(etf_symbol, session=session)
                info = ticker.info or {}
                raw_yield = info.get("yield")
                div_yield = round(float(raw_yield) * 100, 4) if raw_yield is not None else None

                val = IndexValuation(
                    symbol=etf_symbol,
                    target_index=target_index,
                    trade_date=val_date,
                    trailing_pe=info.get("trailingPE"),
                    forward_pe=info.get("forwardPE"),
                    price_to_book=info.get("priceToBook"),
                    price_to_sales=info.get("priceToSalesTrailing12Months"),
                    dividend_yield=div_yield,
                    market_cap=info.get("totalAssets") or info.get("marketCap"),
                )
                results.append(val)
                logger.info(
                    f"YFinance 成功提取 ETF 指数估值 [{etf_symbol} -> {target_index}]: "
                    f"PE-TTM={val.trailing_pe}, Forward-PE={val.forward_pe}, PB={val.price_to_book}"
                )
            except Exception as e:
                logger.error(f"提取 ETF 指数估值失败 [{etf_symbol}]: {e}")

        return results

    def fetch_index_valuations_df(
        self, etf_map: dict[str, str] | None = None, target_date: date | None = None
    ) -> pl.DataFrame:
        """抓取 ETF 指数估值数据并返回 Polars DataFrame。"""
        vals = self.fetch_index_valuations(etf_map=etf_map, target_date=target_date)
        if not vals:
            return pl.DataFrame()
        return pl.DataFrame([v.model_dump() for v in vals])

    def fetch_financials_df(
        self, symbol: str, statement_type: str = "financials", freq: str = "quarterly"
    ) -> pl.DataFrame:
        """抓取上市公司财务报表 (利润表/资产负债表/现金流量表)。"""
        import yfinance as yf

        session = self.client._get_session()
        try:
            ticker = yf.Ticker(symbol, session=session)
            attr_name = f"{freq}_{statement_type}" if freq == "quarterly" else statement_type
            df_raw = getattr(ticker, attr_name, None)
            if df_raw is None or df_raw.empty:
                return pl.DataFrame()

            # yfinance 返回的报表列是日期，索引是科目
            reset_df = df_raw.T.reset_index()
            reset_df = reset_df.rename(columns={"index": "asOfDate", "Date": "asOfDate"})
            reset_df["symbol"] = symbol
            return pl.from_pandas(reset_df)
        except Exception as e:
            logger.error(f"YFinance 抓取财务报表失败 [{symbol}/{statement_type}]: {e}")
            return pl.DataFrame()

    def fetch_actions_df(self, symbol: str, action_type: str = "dividends") -> pl.DataFrame:
        """抓取公司历史分红派息或拆股记录。"""
        import yfinance as yf

        session = self.client._get_session()
        try:
            ticker = yf.Ticker(symbol, session=session)
            series_raw = getattr(ticker, action_type, None)
            if series_raw is None or series_raw.empty:
                return pl.DataFrame()

            df_raw = series_raw.reset_index()
            df_raw.columns = ["Date", action_type]
            df_raw["symbol"] = symbol
            return pl.from_pandas(df_raw)
        except Exception as e:
            logger.error(f"YFinance 抓取分红/拆股失败 [{symbol}/{action_type}]: {e}")
            return pl.DataFrame()

    def fetch_analyst_target_df(self, symbol: str) -> pl.DataFrame:
        """抓取分析师目标价 (最高、最低、均值、中位数)。"""
        import yfinance as yf

        session = self.client._get_session()
        try:
            ticker = yf.Ticker(symbol, session=session)
            targets = ticker.analyst_price_target
            if not targets or not isinstance(targets, dict):
                return pl.DataFrame()

            record = {
                "symbol": symbol,
                "trade_date": date.today(),
                "target_high": targets.get("high"),
                "target_low": targets.get("low"),
                "target_mean": targets.get("mean"),
                "target_median": targets.get("median"),
                "current_price": targets.get("current"),
            }
            return pl.DataFrame([record])
        except Exception as e:
            logger.error(f"YFinance 抓取分析师目标价失败 [{symbol}]: {e}")
            return pl.DataFrame()

    def fetch_fast_info_df(self, symbol: str) -> pl.DataFrame:
        """抓取极速盘前盘后行情快照。"""
        import yfinance as yf

        session = self.client._get_session()
        try:
            ticker = yf.Ticker(symbol, session=session)
            fi = ticker.fast_info
            record = {
                "symbol": symbol,
                "trade_date": date.today(),
                "last_price": getattr(fi, "last_price", None),
                "previous_close": getattr(fi, "previous_close", None),
                "open_price": getattr(fi, "open", None),
                "day_high": getattr(fi, "day_high", None),
                "day_low": getattr(fi, "day_low", None),
                "year_high": getattr(fi, "year_high", None),
                "year_low": getattr(fi, "year_low", None),
                "market_cap": getattr(fi, "market_cap", None),
            }
            return pl.DataFrame([record])
        except Exception as e:
            logger.error(f"YFinance 抓取极速快照失败 [{symbol}]: {e}")
            return pl.DataFrame()
