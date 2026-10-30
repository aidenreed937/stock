"""半导体产业数据源发布日期提取测试。"""

from datetime import date

from stock_data.fetcher.industry.semiconductor.parsers import (
    parse_seaj_historical_xls_url,
    parse_seaj_press_release_target,
    parse_seaj_release_calendar_text,
    parse_semi_article_text,
    parse_sia_china_and_date,
    parse_smic_operating_text,
    parse_tsmc_monthly_revenue_html,
)
from stock_data.fetcher.industry.semiconductor.parsers.inventory import (
    SecFiling,
    build_inventory_release_date_map,
)


def test_sia_release_date_supports_metadata_and_legacy_visible_date() -> None:
    metadata_html = (
        '<meta property="article:published_time" content="2026-08-07T12:00:00+00:00">'
        "Global semiconductor sales during the month of June 2026."
    )
    parsed = parse_sia_china_and_date(metadata_html, "https://example.test/sia")
    assert parsed is not None
    assert parsed["report_month"] == "2026-06"
    assert parsed["release_date"] == date(2026, 8, 7)

    legacy_html = (
        "SAN JOSE, Calif. – June 4, 2007. Worldwide semiconductor sales during the month "
        "of April 2007."
    )
    parsed = parse_sia_china_and_date(legacy_html, "https://example.test/sia")
    assert parsed is not None
    assert parsed["release_date"] == date(2007, 6, 4)


def test_semi_release_date_reads_json_ld_metadata() -> None:
    text = (
        '<script type="application/ld+json">{"datePublished":"2024-12-02T08:00:00Z"}</script>'
        " Global semiconductor equipment billings reached US$30.38 billion "
        "in the third quarter of 2024."
    )
    parsed = parse_semi_article_text(text)
    assert parsed is not None
    assert parsed["release_date"] == date(2024, 12, 2)


def test_tsmc_yearly_html_parses_monthly_revenue_and_skips_empty() -> None:
    html = (
        "<html><body><h3>2025 Monthly Revenue</h3>"
        '<article id="tab-2024"><table class="basicTable"><tr><th>Month</th>'
        "<th>Net Revenue</th><th>YoY</th></tr>"
        "<tr><td><div>Jan.</div></td><td>10,000</td><td>10%</td></tr>"
        "<tr><td><div>Total</div></td><td>10,000</td><td>10%</td></tr></table></article>"
        '<article id="tab-2025"><table class="basicTable"><tr><th>Month</th>'
        "<th>Net Revenue</th><th>YoY</th></tr>"
        "<tr><td><div>Jan.</div></td><td>20,000</td><td>20%</td></tr>"
        "<tr><td><div>Feb.</div></td><td>30,000</td><td>15%</td></tr>"
        "<tr><td><div>Sept.</div></td><td></td><td></td></tr>"
        "</table></article></body></html>"
    )
    parsed = parse_tsmc_monthly_revenue_html(html)
    assert parsed == [
        {
            "report_month": "2025-01",
            "tsmc_revenue_ntd_million": 20000.0,
            "tsmc_revenue_yoy": 0.2,
            "month_raw": "Jan.",
            "net_revenue_raw": "20,000",
            "yoy_change_raw": "20%",
        },
        {
            "report_month": "2025-02",
            "tsmc_revenue_ntd_million": 30000.0,
            "tsmc_revenue_yoy": 0.15,
            "month_raw": "Feb.",
            "net_revenue_raw": "30,000",
            "yoy_change_raw": "15%",
        },
    ]


def test_seaj_release_calendar_and_listing_date_are_source_dates() -> None:
    calendar_text = "2026年7月度 半導体製造装置 2026/8/21"
    assert parse_seaj_release_calendar_text(calendar_text) == {"2026-07": date(2026, 8, 21)}

    html = (
        "<table><tr><td>販売高速報値(3ヶ月平均) "
        "半導体製造装置（日本製）2026年7月度</td>"
        '<td><a href="70971354181554.pdf">pdf</a></td>'
        "<td>2026年8月21日</td></tr></table>"
    )
    target = parse_seaj_press_release_target(html, "https://www.seaj.or.jp/statistics/")
    assert target.release_date == date(2026, 8, 21)
    assert target.pdf_url == "https://www.seaj.or.jp/statistics/70971354181554.pdf"

    history_html = (
        "<table><tr><td>販売高速報値(3ヶ月平均) 半導体</td>"
        '<td><a href="9097484030727.xls">xls</a></td></tr></table>'
    )
    assert parse_seaj_historical_xls_url(history_html) == (
        "https://www.seaj.or.jp/statistics/9097484030727.xls"
    )


def test_smic_release_date_comes_from_announcement_text() -> None:
    parsed = parse_smic_operating_text(
        "中芯国际公布截至二零二四年九月三十日止三个月的未经审核业绩。"
        "产能利用率为85.2%。公告日期 2024 年 11 月 7 日"
    )
    assert parsed is not None
    assert parsed["release_date"] == date(2024, 11, 7)


def test_old_foreign_issuer_6k_is_matched_in_post_quarter_window() -> None:
    row = {"symbol": "STM", "report_quarter": "2016Q1", "trade_date": date(2016, 3, 31)}
    filings = [
        SecFiling("6-K", date(2016, 4, 4), date(2016, 4, 4), "agm.htm", 5_000_000),
        SecFiling("6-K", date(2016, 4, 27), date(2016, 4, 27), "results.htm", 450_000),
    ]
    assert build_inventory_release_date_map([row], {"STM": filings}) == {
        ("STM", "2016Q1"): date(2016, 4, 27)
    }
