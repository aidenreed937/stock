from datetime import date, datetime
from unittest.mock import patch

from stock.config.settings import settings
from stock.data.update_scheduler import DataUpdateScheduler


def test_tushare_daily_update_timing() -> None:
    target_date = date(2026, 8, 12)

    # 1. T 日 14:00 (盘中) -> 尚未更新
    dt_midday = datetime(2026, 8, 12, 14, 0)
    assert not DataUpdateScheduler.is_data_ready("daily", target_date, dt_midday, data_source="tushare")

    # 2. T 日 17:30 (盘后) -> 已就绪
    dt_evening = datetime(2026, 8, 12, 17, 30)
    assert DataUpdateScheduler.is_data_ready("daily", target_date, dt_evening, data_source="tushare")


def test_tushare_margin_detail_timing() -> None:
    target_date = date(2026, 8, 12)

    # 1. T 日 20:00 (T日晚间，要求 T+1 09:00) -> 尚未就绪
    dt_same_night = datetime(2026, 8, 12, 20, 0)
    assert not DataUpdateScheduler.is_data_ready("margin_detail", target_date, dt_same_night, data_source="tushare")

    # 2. T+1 日 09:30 -> 已就绪
    dt_next_morning = datetime(2026, 8, 13, 9, 30)
    assert DataUpdateScheduler.is_data_ready("margin_detail", target_date, dt_next_morning, data_source="tushare")


def test_yfinance_history_timing() -> None:
    target_date = date(2026, 8, 12)

    # 1. T 日 22:00 (美股刚开盘/盘中) -> 尚未就绪 (要求次日 06:00)
    dt_us_trading = datetime(2026, 8, 12, 22, 0)
    assert not DataUpdateScheduler.is_data_ready("history", target_date, dt_us_trading, data_source="yfinance")

    # 2. T+1 日 07:00 (次日清晨) -> 已就绪
    dt_us_closed = datetime(2026, 8, 13, 7, 0)
    assert DataUpdateScheduler.is_data_ready("history", target_date, dt_us_closed, data_source="yfinance")


def test_mock_data_source_timing() -> None:
    target_date = date(2026, 8, 12)
    dt_midday = datetime(2026, 8, 12, 14, 0)

    # mock 数据源不受时间限制
    assert DataUpdateScheduler.is_data_ready("daily", target_date, dt_midday, data_source="mock")


def test_settings_override_timing() -> None:
    target_date = date(2026, 8, 12)
    dt_1715 = datetime(2026, 8, 12, 17, 15)

    # 默认 daily 17:00 -> 17:15 已就绪
    assert DataUpdateScheduler.is_data_ready("daily", target_date, dt_1715, data_source="tushare")

    # 外部配置覆盖为 17:30 更新
    with patch.object(settings, "endpoint_update_time_overrides", {"daily": "17:30"}):
        # 17:15 早于 17:30 -> 未就绪
        assert not DataUpdateScheduler.is_data_ready("daily", target_date, dt_1715, data_source="tushare")
