from datetime import date, datetime
from unittest.mock import MagicMock, patch

import polars as pl

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

    with patch.object(
        DataUpdateScheduler, "_get_trading_days", return_value=(date(2026, 8, 13),)
    ):
        # 1. T 日 20:00 (T日晚间，要求下一个交易日 09:00) -> 尚未就绪
        dt_same_night = datetime(2026, 8, 12, 20, 0)
        assert not DataUpdateScheduler.is_data_ready(
            "margin_detail", target_date, dt_same_night, data_source="tushare"
        )

        # 2. 下一个交易日 09:30 -> 已就绪
        dt_next_morning = datetime(2026, 8, 13, 9, 30)
        assert DataUpdateScheduler.is_data_ready(
            "margin_detail", target_date, dt_next_morning, data_source="tushare"
        )


def test_tushare_margin_weekend_waits_for_next_trading_day() -> None:
    target_date = date(2026, 8, 14)  # Friday
    with patch.object(
        DataUpdateScheduler, "_get_trading_days", return_value=(date(2026, 8, 17),)
    ):
        dt_saturday = datetime(2026, 8, 15, 9, 30)
        dt_monday = datetime(2026, 8, 17, 9, 30)

        assert DataUpdateScheduler.get_expected_ready_date("margin", target_date) == date(
            2026, 8, 17
        )
        assert not DataUpdateScheduler.is_data_ready(
            "margin", target_date, dt_saturday, data_source="tushare"
        )
        assert DataUpdateScheduler.is_data_ready(
            "margin", target_date, dt_monday, data_source="tushare"
        )


def test_tushare_margin_fails_closed_without_trading_calendar() -> None:
    with patch.object(DataUpdateScheduler, "_get_trading_days", return_value=()):
        assert DataUpdateScheduler.get_expected_ready_date(
            "margin", date(2026, 8, 14), data_source="tushare"
        ) is None
        assert not DataUpdateScheduler.is_data_ready(
            "margin",
            date(2026, 8, 14),
            datetime(2026, 8, 17, 10, 0),
            data_source="tushare",
        )


def test_stale_local_trade_calendar_falls_back_to_source() -> None:
    local_catalog = MagicMock()
    local_catalog.load_dataset.return_value = pl.DataFrame(
        {"cal_date": ["20260813"], "is_open": [1]}
    )
    source_fetcher = MagicMock()
    source_fetcher.fetch_trade_cal.return_value = [date(2026, 8, 14)]

    DataUpdateScheduler._get_trading_days.cache_clear()
    try:
        with (
            patch("stock.data.catalog.DataCatalog", return_value=local_catalog),
            patch(
                "stock.data.fetcher.tushare.facade.TuShareDataFetcher",
                return_value=source_fetcher,
            ),
        ):
            trading_days = DataUpdateScheduler._get_trading_days(
                date(2026, 8, 13), date(2026, 8, 14), "tushare"
            )
    finally:
        DataUpdateScheduler._get_trading_days.cache_clear()

    assert trading_days == (date(2026, 8, 14),)
    source_fetcher.fetch_trade_cal.assert_called_once_with(
        date(2026, 8, 13), date(2026, 8, 14)
    )


def test_yfinance_history_timing() -> None:
    target_date = date(2026, 8, 12)

    # 1. T 日 22:00 (美股刚开盘/盘中) -> 尚未就绪 (要求次日 06:00)
    dt_us_trading = datetime(2026, 8, 12, 22, 0)
    assert not DataUpdateScheduler.is_data_ready("history", target_date, dt_us_trading, data_source="yfinance")

    # 2. T+1 日 07:00 (次日清晨) -> 已就绪
    dt_us_closed = datetime(2026, 8, 13, 7, 0)
    assert DataUpdateScheduler.is_data_ready("history", target_date, dt_us_closed, data_source="yfinance")


def test_settings_override_timing() -> None:
    target_date = date(2026, 8, 12)
    dt_1715 = datetime(2026, 8, 12, 17, 15)

    # 默认 daily 17:00 -> 17:15 已就绪
    assert DataUpdateScheduler.is_data_ready("daily", target_date, dt_1715, data_source="tushare")

    # 外部配置覆盖为 17:30 更新
    with patch.object(settings, "endpoint_update_time_overrides", {"daily": "17:30"}):
        # 17:15 早于 17:30 -> 未就绪
        assert not DataUpdateScheduler.is_data_ready("daily", target_date, dt_1715, data_source="tushare")


def test_timezone_aware_timing() -> None:
    from zoneinfo import ZoneInfo

    target_date = date(2026, 8, 12)

    # 传入带 UTC 时区的 datetime (对应北京时间 2026-08-12 18:30) -> 已就绪 (tushare 18:00)
    dt_utc_ready = datetime(2026, 8, 12, 10, 30, tzinfo=ZoneInfo("UTC"))
    assert DataUpdateScheduler.is_data_ready("daily", target_date, dt_utc_ready, data_source="tushare")

    # 传入带 UTC 时区的 datetime (对应北京时间 2026-08-12 16:30) -> 未就绪
    dt_utc_not_ready = datetime(2026, 8, 12, 8, 30, tzinfo=ZoneInfo("UTC"))
    assert not DataUpdateScheduler.is_data_ready("daily", target_date, dt_utc_not_ready, data_source="tushare")


def test_get_endpoint_update_meta() -> None:
    meta = DataUpdateScheduler.get_endpoint_update_meta("tushare", "daily")
    assert meta.task_name == "stock_daily_bar"
    assert meta.api_name == "daily"
    assert meta.update_time == "17:00"
    assert meta.update_delay_days == 0
    assert not meta.delay_in_trading_days
    assert meta.frequency == "daily"


def test_margin_endpoint_uses_trading_day_delay() -> None:
    meta = DataUpdateScheduler.get_endpoint_update_meta("tushare", "margin")
    assert meta.update_delay_days == 1
    assert meta.delay_in_trading_days


def test_check_readiness_and_cli(capsys) -> None:
    from stock.data.update_scheduler import main

    # 测试 check_readiness 返回 DataFrame
    df = DataUpdateScheduler.check_readiness(target_date=date(2026, 8, 12), data_source="tushare")
    assert not df.is_empty()
    assert "任务名称" in df.columns
    assert "状态" in df.columns

    # 测试 CLI main 输出
    with patch("sys.argv", ["update_scheduler.py", "-s", "tushare", "-d", "2026-08-12"]):
        main()
        captured = capsys.readouterr()
        assert "数据源更新窗口就绪诊断报告" in captured.out
