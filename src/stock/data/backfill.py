"""全市场历史数据回填调度器 (HistoricalBackfiller)。

支持按自定义历史日期范围（如过去 5 年、10 年）进行交易日历自动对齐、断点续传与两层 ETL 数据回填。
"""

import argparse
from datetime import date, datetime, timedelta
from typing import Any

from stock.data.fetcher.base import BaseDataFetcher
from stock.data.fetcher.tushare.facade import TuShareDataFetcher
from stock.data.pipeline import MarketDataPipeline
from stock.exceptions import DataFetchError
from stock.utils.logger import logger


class HistoricalBackfiller:
    """生产级历史数据回填调度引擎。"""

    def __init__(
        self,
        pipeline: MarketDataPipeline | None = None,
        fetcher: BaseDataFetcher | None = None,
        data_source: str = "tushare",
        endpoint: str = "daily",
    ) -> None:
        """初始化历史数据回填器。

        Args:
            pipeline: MarketDataPipeline 实例，若为 None 则自动根据 fetcher 创建。
            fetcher: 数据抓取器，若为 None 则默认使用 TuShareDataFetcher。
            data_source: 数据源标识名称（默认 tushare）。
            endpoint: API 接口名称（默认 daily）。
        """
        self.fetcher = fetcher or TuShareDataFetcher()
        self.pipeline = pipeline or MarketDataPipeline(
            fetcher=self.fetcher, data_source=data_source, endpoint=endpoint
        )
        self.data_source = data_source
        self.endpoint = endpoint
        self._calendar_cache: dict[tuple[date, date], list[date]] = {}

    def _get_open_trading_dates(
        self, start_date: date, end_date: date, use_cache: bool = True
    ) -> list[date]:
        """获取开市有效交易日列表，支持内存与离线 Raw 缓存。

        Raises:
            DataFetchError: 当抓取器未实现交易日历接口或获取日历失败时抛出。
        """
        cache_key = (start_date, end_date)
        if use_cache and cache_key in self._calendar_cache:
            logger.info(
                f"命中内存交易日历缓存 [{start_date} ~ {end_date}]: 共 {len(self._calendar_cache[cache_key])} 个有效开市交易日"
            )
            return self._calendar_cache[cache_key]

        fetch_trade_cal_fn = getattr(self.fetcher, "fetch_trade_cal", None)
        if not callable(fetch_trade_cal_fn):
            raise DataFetchError(
                f"数据源抓取器 [{type(self.fetcher).__name__}] 未实现 fetch_trade_cal 交易日历接口，无法进行历史回填！"
            )

        try:
            res = fetch_trade_cal_fn(start_date, end_date)
            if isinstance(res, list):
                cal_dates: list[date] = [d for d in res if isinstance(d, date)]
                if cal_dates:
                    logger.info(
                        f"交易日历从数据源获取成功 [{start_date} ~ {end_date}]: 共 {len(cal_dates)} 个有效开市交易日（已写入内存缓存）"
                    )
                    self._calendar_cache[cache_key] = cal_dates
                    return cal_dates
        except Exception as e:
            logger.error(f"获取数据源交易日历失败: {e}")
            raise DataFetchError(f"获取交易日历失败: {e}") from e

        raise DataFetchError(
            f"交易日历接口返回空数据 [{start_date} ~ {end_date}]，无法进行历史回填！"
        )

    def backfill_range(
        self,
        start_date: date,
        end_date: date,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """按交易日范围进行历史数据批量回填。

        Args:
            start_date: 回填开始日期。
            end_date: 回填结束日期。
            force_refresh: 是否强制向 API 拉取最新数据并覆盖 RAW 离线归档（默认 False）。

        Returns:
            dict[str, Any]: 包含回填统计信息的字典。
        """
        total_days = (end_date - start_date).days + 1
        open_dates = self._get_open_trading_dates(
            start_date, end_date, use_cache=not force_refresh
        )

        logger.info(
            f"开始历史数据回填 [{self.data_source}/{self.endpoint}] "
            f"(时间段: {start_date} ~ {end_date}, 自然日: {total_days}, 交易日: {len(open_dates)})"
        )

        synced_count = 0
        skipped_count = 0
        failed_count = 0

        for idx, trade_date in enumerate(open_dates, 1):
            # 1. 检查 RAW 时间分区缓存（断点续传）
            has_raw = self.pipeline.raw_store.has_raw(
                self.data_source, self.endpoint, trade_date
            )
            if has_raw and not force_refresh:
                skipped_count += 1
                logger.debug(
                    f"[{idx}/{len(open_dates)}] 命中离线 RAW 归档 [{trade_date}]，断点续传自动跳过"
                )
                continue

            # 2. 执行两层 ETL 管道进行补全与归档
            try:
                df = self.pipeline.sync_daily_bars(
                    symbol="",
                    start_date=trade_date,
                    end_date=trade_date,
                    use_raw_cache=not force_refresh,
                    force_refresh=force_refresh,
                )
                if not df.is_empty():
                    synced_count += 1
                else:
                    failed_count += 1
                logger.info(
                    f"[{idx}/{len(open_dates)}] 交易日 [{trade_date}] 回填成功 ({len(df)} 条记录)"
                )
            except Exception as e:
                failed_count += 1
                logger.error(f"[{idx}/{len(open_dates)}] 交易日 [{trade_date}] 回填异常: {e}")

        summary = {
            "total_days": total_days,
            "open_days": len(open_dates),
            "synced_days": synced_count,
            "skipped_days": skipped_count,
            "failed_days": failed_count,
        }

        logger.info(
            f"历史数据回填完成总结: 交易日={summary['open_days']}, "
            f"同步成功={summary['synced_days']}, 断点跳过={summary['skipped_days']}, 失败={summary['failed_days']}"
        )
        return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="全市场历史数据回填工具")
    parser.add_argument("--start", type=str, required=True, help="开始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True, help="结束日期 (YYYY-MM-DD)")
    parser.add_argument(
        "--data-source",
        type=str,
        default="tushare",
        help="数据源标识名称 (默认: tushare)",
    )
    parser.add_argument(
        "--endpoint", type=str, default="daily", help="API 接口名称 (默认: daily)"
    )
    parser.add_argument(
        "--force-refresh", action="store_true", help="强制从 API 重新拉取并覆盖本地缓存"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    start_d = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_d = datetime.strptime(args.end, "%Y-%m-%d").date()

    backfiller = HistoricalBackfiller(
        data_source=args.data_source, endpoint=args.endpoint
    )
    backfiller.backfill_range(start_d, end_d, force_refresh=args.force_refresh)
