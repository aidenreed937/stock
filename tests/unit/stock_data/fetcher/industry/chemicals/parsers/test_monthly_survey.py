"""化工月频调研解析器单元测试（SMM / 隆众·Mysteel 原文样例）。"""

from __future__ import annotations

from datetime import date

from stock_data.fetcher.industry.chemicals.parsers.monthly_survey import (
    parse_monthly_survey_record,
)

_KW = {
    "symbol": "TiO2",
    "product_name": "钛白粉",
    "source_url": "https://example.test/monthly",
}


def test_parse_longzhong_monthly_production_and_utilization() -> None:
    text = (
        "6月，我国钛白粉样本装置产量为39.66万吨，较上月环比-1.15%，同比+10.60%。"
        "本月产能利用率为74.39%，较上月减少3.56个百分点"
    )
    r = parse_monthly_survey_record(
        text, report_month="2026-06", source="Longzhong", release_date=date(2026, 6, 29), **_KW
    )
    assert r is not None
    assert r["production_w_tons"] == 39.66
    assert r["operating_rate_pct"] == 74.39
    assert r["factory_inventory_w_tons"] is None


def test_parse_mysteel_monthly_utilization() -> None:
    text = (
        "7月，我国钛白粉样本装置产量为38.54万吨，较上月环比+0.86%，同比+4.44%。"
        "本月产能利用率为72.29%，较上月减少1.77个百分点"
    )
    r = parse_monthly_survey_record(
        text, report_month="2026-07", source="Mysteel", release_date=date(2026, 8, 7), **_KW
    )
    assert r is not None
    assert r["production_w_tons"] == 38.54
    assert r["operating_rate_pct"] == 72.29


def test_parse_smm_monthly_inventory_abs_mom_yoy() -> None:
    text = (
        "2026年7月中国钛白粉产量为33.87万吨，环比减少1.59%，同比增长1.50%。"
        "库存方面,7月份钛白粉厂商库存达30.68万吨，环比增长23.26%，同比减少22.01%。"
    )
    r = parse_monthly_survey_record(
        text, report_month="2026-07", source="SMM", release_date=date(2026, 7, 31), **_KW
    )
    assert r is not None
    assert r["production_w_tons"] == 33.87
    assert r["factory_inventory_w_tons"] == 30.68
    # 必须取库存环比/同比，而不是前面的产量环比
    assert r["inventory_mom_pct"] == 23.26
    assert r["inventory_yoy_pct"] == -22.01


def test_parse_smm_may_operating_rate_and_inventory_mom() -> None:
    text = (
        "2026年5月，中国钛白粉产量为35.38万吨，环比增长6.31%，行业开工率达80%；"
        "厂商库存为26.3万吨，环比增加14.1%。"
    )
    r = parse_monthly_survey_record(
        text, report_month="2026-05", source="SMM", release_date=date(2026, 5, 29), **_KW
    )
    assert r is not None
    assert r["operating_rate_pct"] == 80.0
    assert r["factory_inventory_w_tons"] == 26.3
    assert r["inventory_mom_pct"] == 14.1
    assert r["inventory_yoy_pct"] is None


def test_parse_smm_august_without_absolute_inventory() -> None:
    text = (
        "2026年8月，SMM国内钛白粉产量环比小幅回升0.3%，但厂商库存同步累积，环比增长0.34%。"
        "当月产量33.97万吨，环比回升0.3%"
    )
    r = parse_monthly_survey_record(
        text, report_month="2026-08", source="SMM", release_date=date(2026, 9, 2), **_KW
    )
    assert r is not None
    assert r["production_w_tons"] == 33.97
    assert r["factory_inventory_w_tons"] is None
    assert r["inventory_mom_pct"] == 0.34


def test_parse_returns_none_for_irrelevant_text() -> None:
    r = parse_monthly_survey_record(
        "今天的钛白粉市场维持弱势运行，整体成交清淡。",
        report_month="2026-08",
        source="SMM",
        release_date=None,
        **_KW,
    )
    assert r is None
