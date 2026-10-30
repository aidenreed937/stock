"""晶圆代工 (TSMC / SMIC) 官方产能利用率采集爬虫与清洗器单元测试。"""

from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.semiconductor.collectors.foundry_crawler import (
    FoundryUtilizationCrawler,
)
from stock_data.fetcher.industry.semiconductor.collectors.foundry_utilization import (
    FoundryUtilizationCollector,
)
from stock_data.fetcher.industry.semiconductor.parsers import (
    extract_smic_financial_report_links,
    extract_tsmc_quarterly_report_links,
    parse_smic_operating_text,
    parse_tsmc_quarterly_report_text,
)
from stock_data.fetcher.industry.semiconductor.schemas import FOUNDRY_RAW_SCHEMA
from stock_data.fetcher.industry.semiconductor.transforms import (
    build_foundry_utilization_frame,
    determine_foundry_utilization_regime,
)


def test_smic_operating_text_parse():
    # 模拟中芯国际 2024Q3 业绩公报文本
    sample_text = """
    中芯国际集成电路制造有限公司公布截至二零二四年九月三十日止三亇月的未经审核业绩。
    二零二四年第三季，產能利用率為85.2%，相比二零二四年第二季為85.2%。
    月產能由二零二四年第二季的837.0千片8吋約當晶圓增加至二零二四年第三季的884.25千片。
    晶圓出貨量為2,122.3千片8吋約當晶圓。
    2024-11-07
    """
    parsed = parse_smic_operating_text(sample_text)
    assert parsed is not None
    assert parsed["report_quarter"] == "2024Q3"
    assert parsed["trade_date"] == date(2024, 9, 30)
    assert parsed["smic_utilization_pct"] == 85.2
    assert parsed["smic_monthly_capacity_8inch_kw"] == 884.25
    assert parsed["smic_wafer_shipment_kw"] == 2122.3
    assert parsed["smic_utilization_raw"] == "85.2%"
    assert parsed["smic_monthly_capacity_raw"] == "884.25千片"
    assert parsed["smic_wafer_shipment_raw"] == "2,122.3千片"
    assert parsed["release_date"] == date(2024, 11, 7)


def test_smic_official_table_formats_are_normalised_to_thousand_wafers():
    parsed = parse_smic_operating_text(
        "中芯国际截至 2026 年 6 月 30 日止三个月未经审核业绩公布。"
        "2026 年第二季度产能利用率(2) 93.7%。"
        "月产能由 2026 年第一季度的 1,078,250 片增加至 2026 年第二季度的 1,096,500 片。"
        "销售晶圆(1) 2,869,495。2026 年 8 月 13 日。"
    )

    assert parsed is not None
    assert parsed["report_quarter"] == "2026Q2"
    assert parsed["smic_utilization_pct"] == 93.7
    assert parsed["smic_monthly_capacity_raw"] == "1,096,500 片"
    assert parsed["smic_monthly_capacity_8inch_kw"] == 1096.5
    assert parsed["smic_wafer_shipment_raw"] == "2,869,495"
    assert parsed["smic_wafer_shipment_kw"] == 2869.495
    assert parsed["release_date"] == date(2026, 8, 13)


def test_smic_english_earnings_release_is_supported():
    parsed = parse_smic_operating_text(
        "SMIC REPORTS UNAUDITED RESULTS FOR THE THREE MONTHS ENDED JUNE 30, 2026. "
        "Monthly capacity increased to 1,096,500 standard logic 8-inch equivalent wafers in 2Q26. "
        "Wafer shipments(1) 2,869,495. Utilization rate(2) 93.7%. "
        "The release was published on August 13, 2026."
    )

    assert parsed is not None
    assert parsed["report_quarter"] == "2026Q2"
    assert parsed["smic_monthly_capacity_8inch_kw"] == 1096.5
    assert parsed["smic_wafer_shipment_kw"] == 2869.495
    assert parsed["smic_utilization_pct"] == 93.7
    assert parsed["release_date"] == date(2026, 8, 13)


def test_smic_pdf_table_values_prefer_report_period_over_comparatives():
    parsed = parse_smic_operating_text(
        "SMIC REPORTS UNAUDITED RESULTS FOR THE THREE MONTHS ENDED DECEMBER 31,  2022. "
        "Monthly capacity increased to 714 thousand 8-inch equivalent wafers. "
        "Shipment and Utilization 4Q22 3Q22 QoQ 4Q21 YoY "
        "Wafer shipments(1) 1,574,068 1,797,671 -12.4% 1,723,360 -8.7% "
        "Utilization rate(2) 79.5% 92.1% 99.4%. "
        "Shanghai, China – February 9, 2023."
    )

    assert parsed is not None
    assert parsed["report_quarter"] == "2022Q4"
    assert parsed["smic_utilization_pct"] == 79.5
    assert parsed["smic_monthly_capacity_8inch_kw"] == 714.0
    assert parsed["smic_wafer_shipment_kw"] == 1574.068


def test_smic_utilization_preserves_three_digit_percentages():
    parsed = parse_smic_operating_text(
        "SMIC REPORTS UNAUDITED RESULTS FOR THE THREE MONTHS ENDED JUNE 30, 2021. "
        "Monthly capacity increased to 561,500 8-inch equivalent wafers. "
        "Shipment and Utilization 2Q21 1Q21 QoQ 2Q20 YoY "
        "Wafer shipments 1,745,194 1,558,893 12.0% 1,435,591 21.6% "
        "Utilization rate(2) 100.4% 98.7% 98.6%. "
        "The release was published on August 5, 2021."
    )

    assert parsed is not None
    assert parsed["report_quarter"] == "2021Q2"
    assert parsed["smic_utilization_pct"] == 100.4
    assert parsed["smic_wafer_shipment_kw"] == 1745.194


def test_smic_financial_summary_discovers_official_earnings_release_links():
    html = (
        '<a href="https://smic.cdn.shwebspace.com/q2.pdf">Earnings Release</a>'
        '<a href="/calendar.pdf">Announcement of Webcast Conference Call</a>'
    )

    assert extract_smic_financial_report_links(html) == ["https://smic.cdn.shwebspace.com/q2.pdf"]


def test_tsmc_quarterly_report_keeps_shipments_and_marks_missing_utilization_unavailable():
    parsed = parse_tsmc_quarterly_report_text(
        "2Q26 Quarterly Management Report July 16, 2026. "
        "Wafer Shipment (kpcs 12 inch-equiv.) 4,336 4,174 3,718. "
        "Gross margin was 67.7%, primarily due to a higher capacity utilization rate."
    )

    assert parsed is not None
    assert parsed["report_quarter"] == "2026Q2"
    assert parsed["tsmc_wafer_shipments_12in_kpcs_raw"] == "4,336 kpcs 12 inch-equiv."
    assert parsed["tsmc_utilization_raw"] is None
    assert parsed["tsmc_utilization_status"] == "unavailable"
    assert parsed["release_date"] == date(2026, 7, 16)


def test_tsmc_quarterly_report_link_discovery_only_selects_management_reports():
    html = (
        '<a href="/earnings.pdf">Earnings Release</a>'
        '<a href="/management.pdf">2Q26 Management Report</a>'
    )

    assert extract_tsmc_quarterly_report_links(
        html,
        base_url="https://investor.tsmc.com/english/quarterly-results/2026/q2",
    ) == ["https://investor.tsmc.com/management.pdf"]


def test_foundry_utilization_regimes():
    assert determine_foundry_utilization_regime(96.0) == "tight_overheated"
    assert determine_foundry_utilization_regime(88.0) == "healthy"
    assert determine_foundry_utilization_regime(78.0) == "oversupply"
    assert determine_foundry_utilization_regime(65.0) == "slump"


def test_foundry_utilization_collect_and_save(tmp_path: Path, monkeypatch) -> None:
    collector = FoundryUtilizationCollector(raw_dir=tmp_path, timeout=7, impersonate="chrome124")

    assert collector.timeout == 7
    assert collector.impersonate == "chrome124"
    assert collector.crawler.timeout == 7
    assert collector.crawler.impersonate == "chrome124"

    def fake_fetch_latest_smic(force: bool = False) -> list[dict[str, object]]:
        assert force is True
        return [
            {
                "report_quarter": "2024Q3",
                "trade_date": date(2024, 9, 30),
                "tsmc_utilization_raw": "90.0%",
                "smic_utilization_raw": "85.2%",
                "smic_monthly_capacity_raw": "884.25千片",
                "smic_wafer_shipment_raw": "2,122.3千片",
                "release_date": date(2024, 11, 7),
                "raw_content_sha256": "smic-sha",
                "raw_snapshot_path": "semiconductors/foundry/smic-q3.html.gz",
            }
        ]

    monkeypatch.setattr(collector.crawler, "fetch_latest_smic", fake_fetch_latest_smic)

    raw_df = collector.collect_raw(force=True)
    assert raw_df["smic_utilization_raw"][0] == "85.2%"
    assert "smic_utilization_pct" not in raw_df.columns
    assert raw_df["raw_content_sha256"][0] == "smic-sha"
    assert raw_df["raw_snapshot_path"][0] == "semiconductors/foundry/smic-q3.html.gz"

    df = build_foundry_utilization_frame(raw_df)
    assert not df.is_empty()
    assert "foundry_weighted_utilization_pct" in df.columns
    assert "utilization_regime" in df.columns
    assert "trade_date" in df.columns
    assert "tsmc_utilization_pct" in df.columns
    assert "smic_utilization_pct" in df.columns
    assert "raw_content_sha256" not in df.columns
    assert "raw_snapshot_path" not in df.columns
    assert df["foundry_proxy_utilization_pct"].to_list() == [87.6]
    assert df["proxy_method"].to_list() == ["equal_company_mean"]
    assert df["proxy_status"].to_list() == ["proxy"]


def test_foundry_collector_uses_online_range_when_context_dates_are_provided(
    tmp_path: Path, monkeypatch
) -> None:
    collector = FoundryUtilizationCollector(raw_dir=tmp_path)
    called: dict[str, object] = {}

    def fake_fetch_range(
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        force: bool = False,
    ) -> list[dict[str, object]]:
        called.update(start_date=start_date, end_date=end_date, force=force)
        return [
            {
                "report_quarter": "2025Q2",
                "trade_date": date(2025, 6, 30),
                "tsmc_utilization_raw": "90.0%",
                "smic_utilization_raw": "85.2%",
                "smic_monthly_capacity_raw": "884.25千片",
                "smic_wafer_shipment_raw": "2,122.3千片",
                "release_date": date(2025, 8, 7),
                "raw_content_sha256": "sha-2025q2",
                "raw_snapshot_path": "semiconductors/foundry/smic-q2.html.gz",
            }
        ]

    monkeypatch.setattr(collector.crawler, "fetch_range", fake_fetch_range)

    raw_df = collector.collect_raw(
        force=True,
        start_date=date(2025, 4, 1),
        end_date=date(2025, 6, 30),
    )

    assert called == {
        "start_date": date(2025, 4, 1),
        "end_date": date(2025, 6, 30),
        "force": True,
    }
    assert raw_df.columns == list(FOUNDRY_RAW_SCHEMA)
    assert raw_df["smic_utilization_raw"].to_list() == ["85.2%"]
    assert "smic_utilization_pct" not in raw_df.columns


def test_foundry_crawler_range_filters_online_results_and_uses_request_options(
    tmp_path: Path, monkeypatch
) -> None:
    class Response:
        def __init__(self, text: str, status_code: int = 200) -> None:
            self.text = text
            self.content = text.encode("utf-8")
            self.status_code = status_code

    pages = {
        "https://www.smics.com/site/news": (
            '<a href="/q1">2025年第一季度业绩公布</a><a href="/q2">2025年第二季度业绩公布</a>'
        ),
    }
    articles = {
        "https://www.smics.com/q1": """
            中芯国际公布截至二零二五年三月三十一日止三个月的未经审核业绩。
            二零二五年第一季，產能利用率為80.0%。 2025-05-08
        """,
        "https://www.smics.com/q2": """
            中芯国际公布截至二零二五年六月三十日止三个月的未经审核业绩。
            二零二五年第二季，產能利用率為85.0%。 2025-08-07
        """,
    }
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_get(url: str, **kwargs: object) -> Response:
        calls.append((url, kwargs))
        if url in pages:
            return Response(pages[url])
        return Response(articles.get(url, ""), status_code=200 if url in articles else 404)

    monkeypatch.setattr(
        "stock_data.fetcher.industry.semiconductor.collectors.foundry_crawler.requests.get",
        fake_get,
    )

    crawler = FoundryUtilizationCrawler(raw_dir=tmp_path, timeout=7, impersonate="chrome124")
    items = crawler.fetch_range(
        start_date=date(2025, 4, 1),
        end_date=date(2025, 6, 30),
    )

    assert [item["report_quarter"] for item in items] == ["2025Q2"]
    assert calls[0][0] == "https://www.smics.com/site/news"
    assert calls[0][1]["timeout"] == 7
    assert calls[0][1]["impersonate"] == "chrome124"


def test_foundry_crawler_merges_tsmc_and_smic_by_report_quarter(
    tmp_path: Path, monkeypatch
) -> None:
    class Response:
        def __init__(self, text: str, status_code: int = 200) -> None:
            self.text = text
            self.content = text.encode("utf-8")
            self.status_code = status_code

    tsmc_page = (
        '<a href="/tsmc-report.pdf">2Q26 Management Report</a>'
        '<a href="/earnings.pdf">Earnings Release</a>'
    )
    smic_article = (
        "中芯国际截至 2026 年 6 月 30 日止三个月未经审核业绩公布。"
        "2026 年第二季度产能利用率(2) 93.7%。"
        "月产能由 2026 年第一季度的 1,078,250 片增加至 2026 年第二季度的 1,096,500 片。"
        "销售晶圆(1) 2,869,495。2026 年 8 月 13 日。"
    )
    tsmc_report = (
        "2Q26 Quarterly Management Report July 16, 2026. "
        "Wafer Shipment (kpcs 12 inch-equiv.) 4,336 4,174 3,718."
    )

    def fake_get(url: str, **_kwargs: object) -> Response:
        if url == "https://www.smics.com/site/news":
            return Response('<a href="/smic-q2">2026年第二季度业绩公布</a>')
        if url == "https://www.smics.com/smic-q2":
            return Response(smic_article)
        if url == "https://investor.tsmc.com/english/quarterly-results/2026/q2":
            return Response(tsmc_page)
        if url == "https://investor.tsmc.com/tsmc-report.pdf":
            return Response(tsmc_report)
        return Response("", status_code=404)

    monkeypatch.setattr(
        "stock_data.fetcher.industry.semiconductor.collectors.foundry_crawler.requests.get",
        fake_get,
    )

    crawler = FoundryUtilizationCrawler(raw_dir=tmp_path)
    items = crawler.fetch_range(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 6, 30),
    )

    assert len(items) == 1
    item = items[0]
    assert item["report_quarter"] == "2026Q2"
    assert item["smic_utilization_raw"] == "93.7%"
    assert item["tsmc_wafer_shipments_12in_kpcs_raw"] == "4,336 kpcs 12 inch-equiv."
    assert item["tsmc_utilization_raw"] is None
    assert item["source"] == "TSMC_IR/SMIC_IR"
    assert item["tsmc_source_url"] == "https://investor.tsmc.com/tsmc-report.pdf"
    assert item["smic_source_url"] == "https://www.smics.com/smic-q2"
    assert item["tsmc_release_date"] == date(2026, 7, 16)
    assert item["smic_release_date"] == date(2026, 8, 13)
    assert item["raw_content_sha256"] == ""
    assert item["tsmc_raw_content_sha256"]
    assert item["smic_raw_content_sha256"]
