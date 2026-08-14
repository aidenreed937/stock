from dataclasses import dataclass
import logging
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from stock.config.settings import settings
from stock.data.fetcher.fred.registry import FRED_API_REGISTRY
from stock.data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY
from stock.data.fetcher.tushare.registry import TUSHARE_API_REGISTRY
from stock.data.fetcher.yfinance.registry import YFINANCE_API_REGISTRY
from stock.data.task_registry import resolve_task

logger = logging.getLogger(__name__)

_DEFAULT_TZ = ZoneInfo("Asia/Shanghai")
DATA_SOURCE_TIMEZONES: dict[str, ZoneInfo] = {
    "tushare": ZoneInfo("Asia/Shanghai"),
    "lixinger": ZoneInfo("Asia/Shanghai"),
    "yfinance": ZoneInfo("Asia/Shanghai"),
    "fred": ZoneInfo("America/New_York"),
}


@dataclass(frozen=True)
class EndpointUpdateMeta:
    """端点数据更新规则与时间窗口元数据。"""

    task_name: str
    api_name: str
    frequency: str
    update_time: str
    update_delay_days: int
    timezone: ZoneInfo


class DataUpdateScheduler:
    """数据更新时间窗口调度拦截与就绪诊断工具。"""

    @classmethod
    def get_endpoint_update_meta(cls, data_source: str, endpoint: str) -> EndpointUpdateMeta:
        """获取指定端点的统一更新规则元数据（SSOT）。"""
        target_tz = DATA_SOURCE_TIMEZONES.get(data_source, _DEFAULT_TZ)
        task = resolve_task(data_source, endpoint)

        update_time_str = "18:00"
        update_delay_days = 0
        freq = task.frequency

        if data_source == "yfinance":
            meta_yf = YFINANCE_API_REGISTRY.get(task.api_name)
            if meta_yf:
                update_time_str = meta_yf.update_time
                update_delay_days = meta_yf.update_delay_days
                freq = getattr(meta_yf, "frequency", freq)
        elif data_source == "lixinger":
            meta_lx = LIXINGER_API_REGISTRY.get(task.api_name)
            if meta_lx:
                update_time_str = meta_lx.update_time
                update_delay_days = meta_lx.update_delay_days
                freq = getattr(meta_lx, "frequency", freq)
        elif data_source == "fred":
            meta_fred = FRED_API_REGISTRY.get(task.api_name)
            if meta_fred:
                freq = getattr(meta_fred, "frequency", freq)
        else:
            meta_ts = TUSHARE_API_REGISTRY.get(task.api_name)
            if meta_ts:
                update_time_str = meta_ts.update_time
                update_delay_days = meta_ts.update_delay_days
                freq = getattr(meta_ts, "frequency", freq)

        # 支持全局 Settings 配置项覆盖 update_time (HH:MM 格式)
        if task.task_name in settings.endpoint_update_time_overrides:
            update_time_str = settings.endpoint_update_time_overrides[task.task_name]
        elif task.api_name in settings.endpoint_update_time_overrides:
            update_time_str = settings.endpoint_update_time_overrides[task.api_name]

        return EndpointUpdateMeta(
            task_name=task.task_name,
            api_name=task.api_name,
            frequency=freq,
            update_time=update_time_str,
            update_delay_days=update_delay_days,
            timezone=target_tz,
        )

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
        expected_date = target_date + timedelta(days=meta.update_delay_days)
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
        from stock.data.task_registry import list_available_tasks

        t_date = target_date or date.today()
        endpoints = list_available_tasks(data_source)
        rows: list[dict[str, Any]] = []
        for ep in endpoints:
            meta = cls.get_endpoint_update_meta(data_source, ep)
            ready = cls.is_data_ready(ep, t_date, current_datetime, data_source=data_source)
            expected_date = t_date + timedelta(days=meta.update_delay_days)
            rows.append(
                {
                    "任务名称": meta.task_name,
                    "上游API": meta.api_name,
                    "频率": meta.frequency,
                    "更新窗口": f"{meta.update_time} (T+{meta.update_delay_days})",
                    "理论就绪时间": f"{expected_date} {meta.update_time}",
                    "状态": "已就绪" if ready else "未就绪 (窗口未到)",
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
