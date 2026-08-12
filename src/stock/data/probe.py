"""多数据源 (TuShare, yfinance, FRED, 理杏仁) 接口连通性与数据契约探测工具。"""

import argparse
import time
from datetime import date, timedelta
from typing import Any

import polars as pl

from stock.data.fetcher.fred import create_fred_fetcher
from stock.data.fetcher.lixinger import LixingerDataFetcher
from stock.data.fetcher.tushare.facade import TuShareDataFetcher
from stock.data.fetcher.yfinance import YFinanceDataFetcher
from stock.data.fetcher.yfinance.client import YFinanceClient
from stock.utils.logger import logger, setup_logger


class GlobalDataProbe:
    """全数据源接口健康度、连通性、响应时延与 Schema 契约综合探测器。"""

    def __init__(
        self,
        tushare_fetcher: TuShareDataFetcher | None = None,
        yfinance_fetcher: YFinanceDataFetcher | None = None,
        fred_fetcher: Any | None = None,
        lixinger_fetcher: LixingerDataFetcher | None = None,
        fetcher: Any | None = None,  # 兼容旧单入参
    ) -> None:
        """初始化各大数据源 Fetcher 实例。"""
        self.tushare_fetcher = fetcher or tushare_fetcher or TuShareDataFetcher()
        self.yfinance_fetcher = yfinance_fetcher or YFinanceDataFetcher(client=YFinanceClient())
        self.fred_fetcher = fred_fetcher or create_fred_fetcher()
        self.lixinger_fetcher = lixinger_fetcher or LixingerDataFetcher()

    def probe_tushare(self) -> list[dict[str, Any]]:
        """探测 TuShare 代表接口。"""
        results = []
        target_date = date.today() - timedelta(days=3)

        # 1. A 股日线
        start_t = time.monotonic()
        try:
            df = self.tushare_fetcher.fetch_daily_bars_df("600000.SH", target_date, target_date)
            lat = (time.monotonic() - start_t) * 1000
            results.append({
                "source": "tushare",
                "endpoint": "daily (A股日线)",
                "freq": "daily",
                "status": "SUCCESS" if not df.is_empty() else "EMPTY",
                "rows": len(df),
                "cols": len(df.columns),
                "latency_ms": round(lat, 2),
            })
        except Exception as e:
            lat = (time.monotonic() - start_t) * 1000
            results.append({"source": "tushare", "endpoint": "daily", "freq": "daily", "status": "FAILED", "error": str(e), "latency_ms": round(lat, 2)})

        # 2. 每日估值指标
        start_t = time.monotonic()
        try:
            df = self.tushare_fetcher.fetch_daily_bars_df("600000.SH", target_date, target_date, endpoint="daily_basic")
            lat = (time.monotonic() - start_t) * 1000
            results.append({
                "source": "tushare",
                "endpoint": "daily_basic (每日估值)",
                "freq": "daily",
                "status": "SUCCESS" if not df.is_empty() else "EMPTY",
                "rows": len(df),
                "cols": len(df.columns),
                "latency_ms": round(lat, 2),
            })
        except Exception as e:
            lat = (time.monotonic() - start_t) * 1000
            results.append({"source": "tushare", "endpoint": "daily_basic", "freq": "daily", "status": "FAILED", "error": str(e), "latency_ms": round(lat, 2)})

        return results

    def probe_yfinance(self) -> list[dict[str, Any]]:
        """探测 yfinance 代表接口。"""
        results = []
        target_date = date.today() - timedelta(days=5)
        today = date.today()

        # 1. 美股日线行情 (AAPL)
        start_t = time.monotonic()
        try:
            df = self.yfinance_fetcher.fetch_daily_bars_df("AAPL", target_date, today)
            lat = (time.monotonic() - start_t) * 1000
            results.append({
                "source": "yfinance",
                "endpoint": "history (美股个股K线)",
                "freq": "daily",
                "status": "SUCCESS" if not df.is_empty() else "EMPTY",
                "rows": len(df),
                "cols": len(df.columns),
                "latency_ms": round(lat, 2),
            })
        except Exception as e:
            lat = (time.monotonic() - start_t) * 1000
            results.append({"source": "yfinance", "endpoint": "history (AAPL)", "freq": "daily", "status": "FAILED", "error": str(e), "latency_ms": round(lat, 2)})

        # 2. 大盘指数 K 线 (^GSPC 标普500)
        start_t = time.monotonic()
        try:
            df = self.yfinance_fetcher.fetch_daily_bars_df("^GSPC", target_date, today)
            lat = (time.monotonic() - start_t) * 1000
            results.append({
                "source": "yfinance",
                "endpoint": "history (美股大盘指数)",
                "freq": "daily",
                "status": "SUCCESS" if not df.is_empty() else "EMPTY",
                "rows": len(df),
                "cols": len(df.columns),
                "latency_ms": round(lat, 2),
            })
        except Exception as e:
            lat = (time.monotonic() - start_t) * 1000
            results.append({"source": "yfinance", "endpoint": "history (^GSPC)", "freq": "daily", "status": "FAILED", "error": str(e), "latency_ms": round(lat, 2)})

        # 3. ETF 大盘指数估值 (SPY / QQQ)
        start_t = time.monotonic()
        try:
            df = self.yfinance_fetcher.fetch_index_valuations_df(etf_map={"SPY": "^GSPC", "QQQ": "^IXIC"})
            lat = (time.monotonic() - start_t) * 1000
            results.append({
                "source": "yfinance",
                "endpoint": "index_valuation (核心ETF估值)",
                "freq": "daily",
                "status": "SUCCESS" if not df.is_empty() else "EMPTY",
                "rows": len(df),
                "cols": len(df.columns),
                "latency_ms": round(lat, 2),
            })
        except Exception as e:
            lat = (time.monotonic() - start_t) * 1000
            results.append({"source": "yfinance", "endpoint": "index_valuation", "freq": "daily", "status": "FAILED", "error": str(e), "latency_ms": round(lat, 2)})

        # 4. 全球宏观资产 (美债10Y / 黄金 / VIX)
        start_t = time.monotonic()
        try:
            df = self.yfinance_fetcher.fetch_macro_indicators_df(target_date, today, symbols=["^TNX", "GC=F", "^VIX"])
            lat = (time.monotonic() - start_t) * 1000
            results.append({
                "source": "yfinance",
                "endpoint": "macro_indicators (全球宏观)",
                "freq": "daily",
                "status": "SUCCESS" if not df.is_empty() else "EMPTY",
                "rows": len(df),
                "cols": len(df.columns),
                "latency_ms": round(lat, 2),
            })
        except Exception as e:
            lat = (time.monotonic() - start_t) * 1000
            results.append({"source": "yfinance", "endpoint": "macro_indicators", "freq": "daily", "status": "FAILED", "error": str(e), "latency_ms": round(lat, 2)})

        return results

    def probe_fred(self) -> list[dict[str, Any]]:
        """探测 FRED 代表接口。"""
        results = []
        start_d = date(2026, 1, 1)
        today = date.today()

        # 1. 月频 CPI (CPIAUCSL)
        start_t = time.monotonic()
        try:
            df = self.fred_fetcher.fetch_series_df("CPIAUCSL", start_d, today)
            lat = (time.monotonic() - start_t) * 1000
            results.append({
                "source": "fred",
                "endpoint": "CPIAUCSL (美国CPI)",
                "freq": "monthly",
                "status": "SUCCESS" if not df.is_empty() else "EMPTY",
                "rows": len(df),
                "cols": len(df.columns),
                "latency_ms": round(lat, 2),
            })
        except Exception as e:
            lat = (time.monotonic() - start_t) * 1000
            results.append({"source": "fred", "endpoint": "CPIAUCSL", "freq": "monthly", "status": "FAILED", "error": str(e), "latency_ms": round(lat, 2)})

        # 2. 月频美联储有效利率 (FEDFUNDS)
        start_t = time.monotonic()
        try:
            df = self.fred_fetcher.fetch_series_df("FEDFUNDS", start_d, today)
            lat = (time.monotonic() - start_t) * 1000
            results.append({
                "source": "fred",
                "endpoint": "FEDFUNDS (美联储利率)",
                "freq": "monthly",
                "status": "SUCCESS" if not df.is_empty() else "EMPTY",
                "rows": len(df),
                "cols": len(df.columns),
                "latency_ms": round(lat, 2),
            })
        except Exception as e:
            lat = (time.monotonic() - start_t) * 1000
            results.append({"source": "fred", "endpoint": "FEDFUNDS", "freq": "monthly", "status": "FAILED", "error": str(e), "latency_ms": round(lat, 2)})

        # 3. 日频国债 10Y-2Y 利差 (T10Y2Y)
        start_t = time.monotonic()
        try:
            df = self.fred_fetcher.fetch_series_df("T10Y2Y", start_d, today)
            lat = (time.monotonic() - start_t) * 1000
            results.append({
                "source": "fred",
                "endpoint": "T10Y2Y (10Y-2Y利差)",
                "freq": "daily",
                "status": "SUCCESS" if not df.is_empty() else "EMPTY",
                "rows": len(df),
                "cols": len(df.columns),
                "latency_ms": round(lat, 2),
            })
        except Exception as e:
            lat = (time.monotonic() - start_t) * 1000
            results.append({"source": "fred", "endpoint": "T10Y2Y", "freq": "daily", "status": "FAILED", "error": str(e), "latency_ms": round(lat, 2)})

        return results

    def probe_lixinger(self) -> list[dict[str, Any]]:
        """探测理杏仁代表接口。"""
        results = []
        start_t = time.monotonic()
        try:
            # 只有当理杏仁配置有效 Token 时探测成功
            df = self.lixinger_fetcher.fetch_daily_bars_df("600519", date(2026, 8, 1), date(2026, 8, 10))
            lat = (time.monotonic() - start_t) * 1000
            results.append({
                "source": "lixinger",
                "endpoint": "cn/company/candlestick",
                "freq": "daily",
                "status": "SUCCESS" if not df.is_empty() else "EMPTY/NO_TOKEN",
                "rows": len(df),
                "cols": len(df.columns),
                "latency_ms": round(lat, 2),
            })
        except Exception as e:
            lat = (time.monotonic() - start_t) * 1000
            results.append({"source": "lixinger", "endpoint": "candlestick", "freq": "daily", "status": "NO_TOKEN", "error": str(e), "latency_ms": round(lat, 2)})
        return results

    def probe_all(self) -> list[dict[str, Any]]:
        """全数据源代表接口综合探测排查。"""
        res = []
        logger.info("开始探测 TuShare 代表接口...")
        res.extend(self.probe_tushare())

        logger.info("开始探测 yfinance 代表接口...")
        res.extend(self.probe_yfinance())

        logger.info("开始探测 FRED 代表接口...")
        res.extend(self.probe_fred())

        logger.info("开始探测 理杏仁 代表接口...")
        res.extend(self.probe_lixinger())

        return res


def main() -> None:
    """CLI 入口点。"""
    setup_logger()
    probe = GlobalDataProbe()

    print("=" * 95)
    print("                全数据源 (TuShare, yfinance, FRED, 理杏仁) 健康度与连通性验证报告                ")
    print("=" * 95)

    results = probe.probe_all()

    for r in results:
        src = r["source"]
        ep = r["endpoint"]
        freq = r["freq"]
        status = r["status"]
        lat = r["latency_ms"]

        if status == "SUCCESS":
            rows = r["rows"]
            cols = r.get("cols", 0)
            print(f"[OK]   [{src:<8}] {ep:<30} | 频次: {freq:<9} | 记录: {rows:>4} 条 | 字段: {cols:>2} 列 | 耗时: {lat:>7.2f}ms")
        elif status == "EMPTY":
            print(f"[WARN] [{src:<8}] {ep:<30} | 频次: {freq:<9} | 记录:    0 条 | (可能是非交易日或更新未完成) | 耗时: {lat:>7.2f}ms")
        else:
            err = r.get("error", "未知错误/未配置Token")
            print(f"[INFO] [{src:<8}] {ep:<30} | 频次: {freq:<9} | 状态: {status:<8} | 提示: {err[:35]}")

    print("=" * 95)


if __name__ == "__main__":
    main()


# 兼容别名
TuShareProbe = GlobalDataProbe
