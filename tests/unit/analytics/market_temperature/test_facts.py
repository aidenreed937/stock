"""市场温度计事实采集辅助函数测试。"""

from datetime import date

from stock.analytics.market_temperature.facts import _parse_date_value


def test_parse_date_value_supports_compact_month() -> None:
    assert _parse_date_value("202606") == date(2026, 6, 1)


def test_parse_date_value_supports_compact_day() -> None:
    assert _parse_date_value("20260814") == date(2026, 8, 14)
