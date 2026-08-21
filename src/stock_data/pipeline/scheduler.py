import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from stock_data.core.settings import data_settings
from stock_data.core.task_registry import _provider_registry, resolve_task
from stock_data.pipeline.cleaner.date_utils import parse_mixed_date

logger = logging.getLogger(__name__)

_DEFAULT_TZ = ZoneInfo("Asia/Shanghai")
DATA_SOURCE_TIMEZONES: dict[str, ZoneInfo] = {
    "tushare": ZoneInfo("Asia/Shanghai"),
    "lixinger": ZoneInfo("Asia/Shanghai"),
    "yfinance": ZoneInfo("Asia/Shanghai"),
    "fred": ZoneInfo("America/New_York"),
    "alphavantage": ZoneInfo("Asia/Shanghai"),
}


@dataclass(frozen=True)
class EndpointUpdateMeta:
    """端点数据更新规则与时间窗口元数据。"""

    task_name: str
    api_name: str
    frequency: str
    update_time: str
    update_delay_days: int
    delay_in_trading_days: bool
    timezone: ZoneInfo


def _resolve_update_values(task: Any, meta: Any) -> tuple[str, int, bool, str]:
    """合并任务契约与 Provider 元数据中的更新窗口。"""
    update_time = task.update_time
    delay_days = task.update_delay_days
    delay_in_trading_days = task.delay_in_trading_days
    frequency = task.frequency
    if meta:
        frequency = getattr(meta, "frequency", frequency)
        if not task.update_time:
            update_time = getattr(meta, "update_time", update_time)
        if task.update_delay_days == 0:
            delay_days = getattr(meta, "update_delay_days", delay_days)
        if not task.delay_in_trading_days:
            delay_in_trading_days = getattr(meta, "delay_in_trading_days", False)
    return update_time, delay_days, delay_in_trading_days, frequency


class DataUpdateScheduler:
    """数据更新时间窗口调度拦截与就绪诊断工具。"""

    @classmethod
    def get_endpoint_update_meta(cls, data_source: str, endpoint: str) -> EndpointUpdateMeta:
        """获取指定端点的统一更新规则元数据（SSOT）。"""
        target_tz = DATA_SOURCE_TIMEZONES.get(data_source, _DEFAULT_TZ)
        task = resolve_task(data_source, endpoint)

        meta = (_provider_registry(data_source) or _provider_registry("tushare")).get(task.api_name)
        update_time_str, update_delay_days, delay_in_trading_days, freq = _resolve_update_values(
            task, meta
        )

        # 支持全局 Settings 配置项覆盖 update_time (HH:MM 格式)
        if task.task_name in data_settings.endpoint_update_time_overrides:
            update_time_str = data_settings.endpoint_update_time_overrides[task.task_name]
        elif task.api_name in data_settings.endpoint_update_time_overrides:
            update_time_str = data_settings.endpoint_update_time_overrides[task.api_name]

        return EndpointUpdateMeta(
            task_name=task.task_name,
            api_name=task.api_name,
            frequency=freq,
            update_time=update_time_str,
            update_delay_days=update_delay_days,
            delay_in_trading_days=delay_in_trading_days,
            timezone=target_tz,
        )

    @classmethod
    def get_expected_ready_date(
        cls,
        endpoint: str,
        target_date: date,
        data_source: str = "tushare",
    ) -> date | None:
        """返回端点的理论就绪日期；交易日历不可用时返回 None。"""
        meta = cls.get_endpoint_update_meta(data_source, endpoint)
        return cls._resolve_expected_ready_date(target_date, meta, data_source)

    @classmethod
    def get_latest_trading_date(
        cls,
        target_date: date,
        data_source: str = "tushare",
        *,
        strictly_before: bool = False,
    ) -> date | None:
        """返回目标日前（或含目标日）的最近有效交易日。"""
        end_date = target_date - timedelta(days=1) if strictly_before else target_date
        start_date = end_date - timedelta(days=31)
        trading_days = cls.get_trading_days(start_date, end_date, data_source)
        candidates = [value for value in trading_days if value <= end_date]
        return max(candidates) if candidates else None

    @classmethod
    def get_trading_days(
        cls, start_date: date, end_date: date, data_source: str = "tushare"
    ) -> tuple[date, ...]:
        """获取指定范围内的权威开市交易日，不按周一至周五猜测。"""
        calendar_source = "tushare" if data_source == "lixinger" else data_source
        return cls._get_trading_days(start_date, end_date, calendar_source)

    @classmethod
    def _resolve_expected_ready_date(
        cls,
        target_date: date,
        meta: EndpointUpdateMeta,
        data_source: str,
    ) -> date | None:
        if meta.update_delay_days <= 0:
            return target_date
        if not meta.delay_in_trading_days:
            return target_date + timedelta(days=meta.update_delay_days)
        return cls._advance_trading_days(
            target_date, meta.update_delay_days, data_source=data_source
        )

    @classmethod
    def _advance_trading_days(
        cls, target_date: date, delay_days: int, *, data_source: str
    ) -> date | None:
        """按权威交易日历推进日期；无法取得日历时保持未就绪。"""
        cursor = target_date
        remaining = delay_days
        while remaining > 0:
            search_start = cursor + timedelta(days=1)
            search_end = cursor + timedelta(days=max(14, remaining * 7))
            trading_days = cls._get_trading_days(search_start, search_end, data_source)
            for trading_day in trading_days:
                if trading_day <= cursor:
                    continue
                cursor = trading_day
                remaining -= 1
                if remaining == 0:
                    return cursor
            logger.warning(
                "[%s] 无法取得交易日历，端点 T+%d 数据保持未就绪: %s",
                data_source,
                delay_days,
                target_date,
            )
            return None
        return cursor

    @staticmethod
    @lru_cache(maxsize=128)
    def _get_trading_days(start_date: date, end_date: date, data_source: str) -> tuple[date, ...]:
        """读取本地交易日历，缺失时尝试上游；不做工作日猜测。"""
        if data_source == "yfinance":
            import exchange_calendars as xcals

            sessions = xcals.get_calendar("XNYS").sessions_in_range(
                start_date.isoformat(), end_date.isoformat()
            )
            return tuple(session.date() for session in sessions)
        if data_source == "alphavantage":
            from stock_data.fetcher.alphavantage.global_fetcher import AlphaVantageDataFetcher

            return tuple(AlphaVantageDataFetcher().fetch_trade_cal(start_date, end_date))
        if data_source != "tushare":
            return ()

        try:
            from stock_data.catalog import DataCatalog

            frame = DataCatalog(data_source="tushare").load_dataset("trade_cal")
            date_column = "cal_date" if "cal_date" in frame.columns else "trade_date"
            if not frame.is_empty() and date_column in frame.columns:
                frame = frame.with_columns(parse_mixed_date(date_column).alias("_calendar_date"))
                calendar_dates: list[date] = [
                    value
                    for value in frame.get_column("_calendar_date").drop_nulls().to_list()
                    if isinstance(value, date)
                ]
                if not calendar_dates:
                    raise ValueError("本地交易日历没有可解析日期")
                local_min = min(calendar_dates)
                local_max = max(calendar_dates)
                if local_min <= start_date and local_max >= end_date:
                    if "is_open" in frame.columns:
                        frame = frame.filter(pl.col("is_open").cast(pl.Int8, strict=False) == 1)
                    local_dates = {
                        value
                        for value in frame.get_column("_calendar_date").drop_nulls().to_list()
                        if isinstance(value, date) and start_date <= value <= end_date
                    }
                    return tuple(sorted(local_dates))
        except Exception as exc:
            logger.debug("读取本地 TuShare 交易日历失败: %s", exc)

        try:
            from stock_data.fetcher.tushare.facade import TuShareDataFetcher

            fetched = TuShareDataFetcher().fetch_trade_cal(start_date, end_date)
            return tuple(sorted({value for value in fetched if start_date <= value <= end_date}))
        except Exception as exc:
            logger.warning("读取 TuShare 交易日历失败 [%s ~ %s]: %s", start_date, end_date, exc)
            return ()

    @classmethod
    def is_data_ready(
        cls,
        endpoint: str,
        target_date: date,
        current_datetime: datetime | None = None,
        data_source: str = "tushare",
    ) -> bool:
        """判断目标接口针对指定交易日的数据是否已过预计更新窗口。

        Args:
            endpoint: API 接口标识（如 daily, daily_basic, margin_detail, history 等）。
            target_date: 拟同步的交易日期。
            current_datetime: 当前系统时间，默认值为当前时间。
            data_source: 数据源标识（tushare / yfinance / lixinger / fred）。

        Returns:
            bool: 若已到达更新时间点返回 True，未到达则返回 False。
        """
        meta = cls.get_endpoint_update_meta(data_source, endpoint)
        target_tz = meta.timezone

        if current_datetime is None:
            current_datetime = datetime.now(target_tz)
        elif current_datetime.tzinfo is None:
            current_datetime = current_datetime.replace(tzinfo=target_tz)
        else:
            current_datetime = current_datetime.astimezone(target_tz)

        # 解析 HH:MM 时间
        try:
            hour_str, minute_str = meta.update_time.split(":")
            target_time = time(int(hour_str), int(minute_str))
        except ValueError:
            logger.warning(
                f"接口 [{endpoint}] 配置的时间解析失败: '{meta.update_time}'，回退默认 18:00"
            )
            target_time = time(18, 0)

        # 计算理论可获取的最早时间点 (带有时区信息)
        expected_date = cls._resolve_expected_ready_date(target_date, meta, data_source)
        if expected_date is None:
            logger.warning(
                "[%s/%s] 交易日 [%s] 的交易日历不可用，安全跳过请求",
                data_source,
                endpoint,
                target_date,
            )
            return False
        expected_ready_dt = datetime.combine(expected_date, target_time, tzinfo=target_tz)

        if current_datetime < expected_ready_dt:
            logger.warning(
                f"[{data_source}/{endpoint}] 交易日 [{target_date}] 数据未就绪！"
                f"预计更新时间: {expected_ready_dt.strftime('%Y-%m-%d %H:%M %Z')}, "
                f"当前时间: {current_datetime.strftime('%Y-%m-%d %H:%M %Z')}，安全跳过该请求。"
            )
            return False

        return True

    @classmethod
    def check_readiness(
        cls,
        target_date: date | None = None,
        data_source: str = "tushare",
        current_datetime: datetime | None = None,
    ) -> pl.DataFrame:
        """批量检查指定数据源全部端点在目标日期的就绪状态。"""
        from stock_data.core.task_registry import list_available_tasks

        t_date = target_date or date.today()
        endpoints = list_available_tasks(data_source)
        rows: list[dict[str, Any]] = []
        for ep in endpoints:
            meta = cls.get_endpoint_update_meta(data_source, ep)
            ready = cls.is_data_ready(ep, t_date, current_datetime, data_source=data_source)
            expected_date = cls._resolve_expected_ready_date(t_date, meta, data_source)
            delay_unit = "交易日" if meta.delay_in_trading_days else "日历日"
            if expected_date is None:
                readiness = "未就绪 (交易日历不可用)"
                expected_label = "未知"
            else:
                readiness = "已就绪" if ready else "未就绪 (窗口未到)"
                expected_label = f"{expected_date} {meta.update_time}"
            rows.append(
                {
                    "任务名称": meta.task_name,
                    "上游API": meta.api_name,
                    "频率": meta.frequency,
                    "更新窗口": f"{meta.update_time} (T+{meta.update_delay_days}{delay_unit})",
                    "理论就绪时间": expected_label,
                    "状态": readiness,
                }
            )
        if not rows:
            return pl.DataFrame()
        return pl.DataFrame(rows)


def main() -> None:
    """Update Scheduler 诊断 CLI 入口。"""
    import argparse

    parser = argparse.ArgumentParser(description="数据更新时间窗口就绪检查与调度保护诊断 CLI")
    parser.add_argument(
        "-s",
        "--source",
        dest="source",
        type=str,
        default="tushare",
        help="数据源标识 (默认 tushare)",
    )
    parser.add_argument(
        "-d",
        "--date",
        dest="date",
        type=str,
        default=None,
        help="待检查目标交易日 (YYYY-MM-DD，默认当日)",
    )
    args = parser.parse_args()
    target_dt = date.fromisoformat(args.date) if args.date else date.today()

    df = DataUpdateScheduler.check_readiness(target_date=target_dt, data_source=args.source)
    print("=" * 95)
    print(f"       【数据源更新窗口就绪诊断报告: {args.source.upper()} (目标日: {target_dt})】")
    print("=" * 95)
    if not df.is_empty():
        with pl.Config(tbl_rows=100, tbl_width_chars=120, tbl_hide_dataframe_shape=True):
            print(df)
    else:
        print(f"数据源 [{args.source}] 未注册任何公开任务。")
    print("=" * 95)


if __name__ == "__main__":
    main()
