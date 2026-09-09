"""海关统计在线查询数据发布时间（release_date）确定性规则测试。

依据海关总署年度《中国海关统计数据公布时间表》：
1-2 月合并 3 月 20 日发布；12 月次年 1 月 20 日；其余月次月 20 日。
"""

from datetime import date

from stock_data.fetcher.industry.customs.release_calendar import release_date_for


def test_jan_and_feb_merge_to_march():
    assert release_date_for("2026-01") == date(2026, 3, 20)
    assert release_date_for("2026-02") == date(2026, 3, 20)


def test_december_rolls_to_next_year():
    assert release_date_for("2025-12") == date(2026, 1, 20)


def test_regular_month_next_month_20th():
    assert release_date_for("2026-03") == date(2026, 4, 20)
    assert release_date_for("2026-07") == date(2026, 8, 20)
    assert release_date_for("2026-11") == date(2026, 12, 20)


def test_historical_year_uses_same_rule():
    assert release_date_for("2019-01") == date(2019, 3, 20)
    assert release_date_for("2019-12") == date(2020, 1, 20)
