"""TuShare 数据接口探测与健康检查工具。"""

import argparse
import time
from datetime import date, timedelta
from typing import Any

from stock.data.fetcher.tushare.facade import TuShareDataFetcher
from stock.utils.logger import logger, setup_logger


class TuShareProbe:
    """TuShare 数据源接口连通性、响应时延与 Schema 契约探测器。"""

    def __init__(self, fetcher: TuShareDataFetcher | None = None) -> None:
        """初始化探测器。

        Args:
            fetcher: TuShareDataFetcher 实例，若为 None 则自动创建。
        """
        self.fetcher = fetcher or TuShareDataFetcher()

    def probe_endpoint(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        """对单接口执行健康探测。

        Args:
            endpoint: 接口名称。
            **kwargs: 传给接口的检索参数。

        Returns:
            dict: 探测结果元数据。
        """
        start_time = time.monotonic()
        try:
            target_date = date.today() - timedelta(days=1)
            if endpoint == "trade_cal":
                dates = self.fetcher.fetch_trade_cal(
                    target_date - timedelta(days=10), target_date
                )
                elapsed_ms = (time.monotonic() - start_time) * 1000
                return {
                    "endpoint": endpoint,
                    "status": "SUCCESS",
                    "rows": len(dates),
                    "columns": ["cal_date"],
                    "latency_ms": round(elapsed_ms, 2),
                }

            df = self.fetcher.fetch_daily_bars_df(
                symbol=kwargs.get("symbol", ""),
                start_date=kwargs.get("start_date", target_date),
                end_date=kwargs.get("end_date", target_date),
                endpoint=endpoint,
            )
            elapsed_ms = (time.monotonic() - start_time) * 1000
            return {
                "endpoint": endpoint,
                "status": "SUCCESS" if not df.is_empty() else "EMPTY",
                "rows": len(df),
                "columns": df.columns,
                "latency_ms": round(elapsed_ms, 2),
            }
        except Exception as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            return {
                "endpoint": endpoint,
                "status": "FAILED",
                "error": str(e),
                "latency_ms": round(elapsed_ms, 2),
            }

    def probe_all(self) -> list[dict[str, Any]]:
        """执行常用接口全量健康排查。"""
        endpoints = ["trade_cal", "stock_basic", "daily", "daily_basic", "adj_factor"]
        results = []
        target_date = date.today() - timedelta(days=1)
        for ep in endpoints:
            logger.info(f"正在探测 TuShare 接口 [{ep}]...")
            res = self.probe_endpoint(ep, start_date=target_date, end_date=target_date)
            results.append(res)
        return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TuShare 接口连通性与健康探测工具")
    parser.add_argument(
        "--endpoint", type=str, default="", help="指定探测的 API 接口名称 (为空时全量排查)"
    )
    return parser.parse_args()


def main() -> None:
    """CLI 入口点。"""
    setup_logger()
    args = _parse_args()
    probe = TuShareProbe()

    print("=" * 70)
    print("           TuShare 数据源连通性与 Schema 探测报告           ")
    print("=" * 70)

    if args.endpoint:
        results = [probe.probe_endpoint(args.endpoint)]
    else:
        results = probe.probe_all()

    for r in results:
        status = r["status"]
        ep = r["endpoint"]
        lat = r["latency_ms"]
        if status == "SUCCESS":
            rows = r["rows"]
            cols = r.get("columns", [])
            cols_preview = ", ".join(cols[:4]) + ("..." if len(cols) > 4 else "")
            print(
                f"[OK]   {ep:<15} | 记录数: {rows:>5} 条 | 耗时: {lat:>7.2f}ms | 字段: {cols_preview}"
            )
        elif status == "EMPTY":
            print(f"[WARN] {ep:<15} | 记录数:     0 条 | 耗时: {lat:>7.2f}ms | (可能因非交易日)")
        else:
            err = r.get("error", "Unknown error")
            print(f"[ERR]  {ep:<15} | 探测失败       | 耗时: {lat:>7.2f}ms | 原因: {err}")

    print("=" * 70)


if __name__ == "__main__":
    main()
