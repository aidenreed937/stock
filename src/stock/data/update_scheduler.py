"""接口更新时刻拦截器模块 (DataUpdateScheduler)。

校验各数据源接口在指定日期下的数据是否已达到数据提供商的盘后/次日结算时间点，防止早于更新时间发起无效网络请求。
"""

import logging
from datetime import date, datetime, time, timedelta

from stock.config.settings import settings
from stock.data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY
from stock.data.fetcher.tushare.registry import TUSHARE_API_REGISTRY
from stock.data.fetcher.yfinance.registry import YFINANCE_API_REGISTRY
from stock.data.task_registry import resolve_task

logger = logging.getLogger(__name__)


class DataUpdateScheduler:
    """数据更新时间窗口调度拦截器。"""

    @staticmethod
    def is_data_ready(
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
            data_source: 数据源标识（tushare / yfinance / lixinger / mock）。

        Returns:
            bool: 若已到达更新时间点返回 True，未到达则返回 False。
        """
        # mock 数据源无时间约束，时刻可被读取
        if data_source == "mock":
            return True

        if current_datetime is None:
            current_datetime = datetime.now()

        task = resolve_task(data_source, endpoint)

        # 获取默认更新规则元数据
        update_time_str = "18:00"
        update_delay_days = 0

        if data_source == "yfinance":
            meta_yf = YFINANCE_API_REGISTRY.get(task.api_name)
            if meta_yf:
                update_time_str = meta_yf.update_time
                update_delay_days = meta_yf.update_delay_days
        elif data_source == "lixinger":
            meta_lx = LIXINGER_API_REGISTRY.get(task.api_name)
            if meta_lx:
                update_time_str = meta_lx.update_time
                update_delay_days = meta_lx.update_delay_days
        else:
            meta_ts = TUSHARE_API_REGISTRY.get(task.api_name)
            if meta_ts:
                update_time_str = meta_ts.update_time
                update_delay_days = meta_ts.update_delay_days

        # 支持全局 Settings 配置项覆盖 update_time (HH:MM 格式)
        if task.task_name in settings.endpoint_update_time_overrides:
            update_time_str = settings.endpoint_update_time_overrides[task.task_name]
        elif task.api_name in settings.endpoint_update_time_overrides:
            update_time_str = settings.endpoint_update_time_overrides[task.api_name]

        # 解析 HH:MM 时间
        try:
            hour_str, minute_str = update_time_str.split(":")
            target_time = time(int(hour_str), int(minute_str))
        except ValueError:
            logger.warning(
                f"接口 [{endpoint}] 配置的时间解析失败: '{update_time_str}'，回退默认 18:00"
            )
            target_time = time(18, 0)

        # 计算理论可获取的最早时间点
        expected_date = target_date + timedelta(days=update_delay_days)
        expected_ready_dt = datetime.combine(expected_date, target_time)

        if current_datetime < expected_ready_dt:
            logger.warning(
                f"[{data_source}/{endpoint}] 交易日 [{target_date}] 数据未就绪！"
                f"预计更新时间: {expected_ready_dt.strftime('%Y-%m-%d %H:%M')}, "
                f"当前时间: {current_datetime.strftime('%Y-%m-%d %H:%M')}，安全跳过该请求。"
            )
            return False

        return True
