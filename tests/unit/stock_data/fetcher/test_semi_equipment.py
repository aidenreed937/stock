"""SEMI 全球设备销售公报在线采集爬虫与清洗器单元测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.semiconductor.collectors.semi import (
    SemiEquipmentCollector,
)
from stock_data.fetcher.industry.semiconductor.collectors.semi_crawler import (
    SemiEquipmentCrawler,
)
from stock_data.fetcher.industry.semiconductor.lineage import raw_content_sha256
from stock_data.fetcher.industry.semiconductor.parsers import (
    parse_semi_article_text,
)
from stock_data.fetcher.industry.semiconductor.transforms.semi import (
    build_semi_equipment_curated_frame,
)


def test_semi_crawler_parse_article_text():
    # 模拟 2024Q3 SEMI 新闻稿样本
    sample_pr = """
    MILPITAS, Calif. – December 2, 2024 – Global semiconductor equipment billings increased 19%
    year-over-year to US$30.38 billion in the third quarter of 2024, while quarter-over-quarter
    billings registered 13% growth during the same period, SEMI announced today.
    China continues to lead in spending with billings of $12.45 billion.
    """
    res = parse_semi_article_text(sample_pr, source_url="https://www.semi.org/test")
    assert res is not None
    assert res["report_quarter"] == "2024-Q3"
    assert res["trade_date"] == date(2024, 9, 30)
    assert res["global_billings_billion_usd"] == 30.38
    assert res["china_billings_billion_usd"] == 12.45
    assert res["global_billings_raw"] == "US$30.38 billion"
    assert res["china_billings_raw"] == "$12.45 billion"
    assert res["yoy_growth_raw"] == "19%"
    assert res["qoq_growth_raw"] == "13%"
    assert res["release_date"] == date(2024, 12, 2)


def test_semi_article_without_release_date_keeps_null() -> None:
    sample_pr = """
    Global semiconductor equipment billings reached US$30.38 billion in the third quarter of 2024.
    China billings were $12.45 billion.
    """
    res = parse_semi_article_text(sample_pr, source_url="https://www.semi.org/test")
    assert res is not None
    assert res["trade_date"] == date(2024, 9, 30)
    assert res["release_date"] is None


def test_semi_parser_supports_legacy_percent_copy() -> None:
    sample_pr = """
    MILPITAS, Calif. - June 2, 2020 - Worldwide semiconductor manufacturing equipment
    billings contracted 13 percent to US$15.57 billion quarter-over-quarter in
    First-Quarter 2020 but increased 13 percent year-over-year, SEMI announced today.
    """
    res = parse_semi_article_text(sample_pr, source_url="https://www.semi.org/q1-2020")

    assert res is not None
    assert res["report_quarter"] == "2020-Q1"
    assert res["global_billings_raw"] == "US$15.57 billion"
    assert res["yoy_growth_raw"] == "13%"
    assert res["qoq_growth_raw"] == "-13%"


def test_semi_parser_supports_annual_source_article() -> None:
    sample_pr = """
    MILPITAS, Calif. - April 9, 2025 - Global semiconductor equipment billings
    surged to $117.1 billion in 2024, SEMI announced today.
    """
    res = parse_semi_article_text(sample_pr, source_url="https://www.semi.org/annual-2024")

    assert res is not None
    assert res["report_quarter"] == "2024-ANNUAL"
    assert res["trade_date"] == date(2024, 12, 31)
    assert res["source_record_type"] == "annual_source"
    assert res["annual_billings_raw"] == "$117.1 billion"
    assert res["annual_billings_billion_usd"] == 117.1
    assert res["data_status"] == "annual_source"


def test_semi_crawler_default_uses_online_response_even_with_cached_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    snapshot_dir = tmp_path / "semiconductor" / "semi"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "cached.html").write_text(
        """
        MILPITAS, Calif. - June 1, 2020 - Global semiconductor equipment billings
        reached US$1.00 billion in the first quarter of 2020.
        """,
        encoding="utf-8",
    )

    class Response:
        def __init__(
            self,
            text: str,
            status_code: int = 200,
            headers: dict[str, str] | None = None,
        ) -> None:
            self.text = text
            self.content = text.encode("utf-8")
            self.status_code = status_code
            self.headers = headers or {}

    calls: list[tuple[str, dict[str, object]]] = []

    def fake_get(url: str, **kwargs: object) -> Response:
        calls.append((url, kwargs))
        if "products-services/market-data/equipment" in url:
            return Response('<a href="/live-pr">Global Semiconductor Equipment Billings</a>')
        return Response(
            """
            MILPITAS, Calif. - September 2, 2025 - Global semiconductor equipment
            billings reached US$33.07 billion in the second quarter of 2025.
            China continues to lead in spending with billings of $12.00 billion.
            """,
            headers={"Last-Modified": "Tue, 02 Sep 2025 00:00:00 GMT"},
        )

    monkeypatch.setattr(
        "stock_data.fetcher.industry.semiconductor.collectors.semi_crawler.requests.get",
        fake_get,
    )

    crawler = SemiEquipmentCrawler(raw_dir=tmp_path, timeout=7, impersonate="chrome124")
    items = crawler.fetch_latest()

    assert [item["report_quarter"] for item in items] == ["2025-Q2"]
    assert items[0]["source_url"] == "https://www.semi.org/live-pr"
    assert calls[0][1]["timeout"] == 7
    assert calls[0][1]["impersonate"] == "chrome124"
    assert (snapshot_dir / "www-semi-org-live-pr.html.gz").exists()


def test_semi_crawler_uses_equipment_market_page_as_primary_source(
    tmp_path: Path, monkeypatch
) -> None:
    class Response:
        def __init__(self, text: str, status_code: int = 200) -> None:
            self.text = text
            self.content = text.encode("utf-8")
            self.status_code = status_code
            self.headers: dict[str, str] = {}

    calls: list[str] = []

    def fake_get(url: str, **_kwargs: object) -> Response:
        calls.append(url)
        if "products-services/market-data/equipment" in url:
            return Response(
                '<a href="/q1-2026">SEMI Reports Global Semiconductor Equipment Billings '
                "Increased 14% Year-Over-Year in Q1 2026</a>"
            )
        return Response(
            """
            MILPITAS, Calif. - June 4, 2026 - Global semiconductor equipment
            billings increased 14% year-over-year to US$36.55 billion in the first quarter of 2026.
            First quarter 2026 billings registered a 1% quarter-over-quarter growth.
            """
        )

    monkeypatch.setattr(
        "stock_data.fetcher.industry.semiconductor.collectors.semi_crawler.requests.get",
        fake_get,
    )

    items = SemiEquipmentCrawler(raw_dir=tmp_path).fetch_latest()

    assert [item["report_quarter"] for item in items] == ["2026-Q1"]
    assert calls[0] == "https://www.semi.org/en/products-services/market-data/equipment"
    assert "press-releases" not in calls


def test_semi_crawler_fetch_range_uses_official_equipment_article_archive(
    tmp_path: Path, monkeypatch
) -> None:
    class Response:
        def __init__(self, text: str, status_code: int = 200) -> None:
            self.text = text
            self.content = text.encode("utf-8")
            self.status_code = status_code
            self.headers: dict[str, str] = {}

    archive_url = "https://www.semi.org/en/products-services/market-data/equipment-article-archive"
    pages = {
        "https://www.semi.org/en/products-services/market-data/equipment": "<html></html>",
        archive_url: """
            <a href="/q1-2023">Q1 2023 Global Semiconductor Equipment Billings Grow
            9% Year-Over-Year, SEMI Reports</a>
            <a href="/q3-2022">Global Semiconductor Equipment Billings Increase 9% in
            Q3 2022, SEMI Reports</a>
            <a href="/annual-2022">Global Semiconductor Equipment Billings Reach Industry
            Record $107.6 Billion in 2022, SEMI Reports</a>
        """,
    }
    articles = {
        "https://www.semi.org/q1-2023": """
            MILPITAS, Calif. - June 6, 2023 - Global semiconductor equipment
            billings increased 9% year-over-year to US$26.8 billion in the first quarter of 2023.
            Quarter-over-quarter billings slipped 3%.
        """,
        "https://www.semi.org/q3-2022": """
            MILPITAS, Calif. - November 30, 2022 - Global semiconductor equipment
            billings rose 9% from the second to the third quarter of 2022 and
            7% year-over-year to US$28.75 billion.
        """,
        "https://www.semi.org/annual-2022": """
            MILPITAS, Calif. - April 12, 2023 - Global semiconductor equipment
            billings reach industry record $107.6 billion in 2022, SEMI reports.
        """,
    }
    calls: list[str] = []

    def fake_get(url: str, **_kwargs: object) -> Response:
        calls.append(url)
        if url in pages:
            return Response(pages[url])
        if url in articles:
            return Response(articles[url])
        return Response("", status_code=404)

    monkeypatch.setattr(
        "stock_data.fetcher.industry.semiconductor.collectors.semi_crawler.requests.get",
        fake_get,
    )

    items = SemiEquipmentCrawler(raw_dir=tmp_path).fetch_range(
        start_date=date(2022, 1, 1),
        end_date=date(2023, 12, 31),
    )

    assert [item["report_quarter"] for item in items] == [
        "2022-Q3",
        "2022-ANNUAL",
        "2023-Q1",
    ]
    assert archive_url in calls
    assert f"{archive_url}?page=1" not in calls
    assert (tmp_path / "semiconductor" / "semi" / "www-semi-org-q1-2023.html.gz").exists()


def test_semi_crawler_fetch_range_uses_official_legacy_article_seeds(
    tmp_path: Path, monkeypatch
) -> None:
    class Response:
        def __init__(self, text: str, status_code: int = 200) -> None:
            self.text = text
            self.content = text.encode("utf-8")
            self.status_code = status_code
            self.headers: dict[str, str] = {}

    q1_url = "https://www.semi.org/en/news-resources/press/Q1-2020-wwsems"
    q2_url = "https://www.semi.org/en/news-resources/press/Q2-2020-wwsems"
    pages = {
        "https://www.semi.org/en/products-services/market-data/equipment": "<html></html>",
        "https://www.semi.org/en/products-services/market-data/equipment-article-archive": (
            "<html></html>"
        ),
        "https://www.semi.org/en/news-media/press-releases": "<html></html>",
        "https://www.prnewswire.com/news-releases/semi-reports-news-list/": "<html></html>",
    }
    articles = {
        q1_url: """
            MILPITAS, Calif. - June 2, 2020 - Worldwide semiconductor manufacturing equipment
            billings contracted 13 percent to US$15.57 billion quarter-over-quarter in Q1 2020
            but increased 13 percent year-over-year.
        """,
        q2_url: """
            MILPITAS, Calif. - September 8, 2020 - Second quarter 2020 global billings for
            semiconductor manufacturing equipment jumped 26% year-over-year and 8%, to
            US$16.8 billion, from the first quarter of the year.
        """,
    }
    calls: list[str] = []

    def fake_get(url: str, **_kwargs: object) -> Response:
        calls.append(url)
        if url in pages:
            return Response(pages[url])
        if url in articles:
            return Response(articles[url])
        return Response("", status_code=404)

    monkeypatch.setattr(
        "stock_data.fetcher.industry.semiconductor.collectors.semi_crawler.requests.get",
        fake_get,
    )

    items = SemiEquipmentCrawler(raw_dir=tmp_path).fetch_range(
        start_date=date(2020, 1, 1),
        end_date=date(2020, 6, 30),
    )

    assert [item["report_quarter"] for item in items] == ["2020-Q1", "2020-Q2"]
    assert q1_url in calls
    assert q2_url in calls
    assert items[0]["qoq_growth_raw"] == "-13%"
    assert items[1]["qoq_growth_raw"] == "8%"


def test_semi_crawler_fetch_range_paginates_and_filters_by_trade_date(
    tmp_path: Path, monkeypatch
) -> None:
    class Response:
        def __init__(self, text: str, status_code: int = 200) -> None:
            self.text = text
            self.content = text.encode("utf-8")
            self.status_code = status_code
            self.headers: dict[str, str] = {}

    pages = {
        "https://www.semi.org/en/news-media/press-releases": """
            <a href="/q2-2025">Global Semiconductor Equipment Billings Q2 2025</a>
            <a href="/q1-2025">Global Semiconductor Equipment Billings Q1 2025</a>
        """,
        "https://www.semi.org/en/news-media/press-releases?page=1": """
            <a href="/q4-2024">Global Semiconductor Equipment Billings Q4 2024</a>
        """,
        "https://www.semi.org/en/news-media/press-releases?page=2": """
            <a href="/q3-2024">Global Semiconductor Equipment Billings Q3 2024</a>
        """,
    }
    articles = {
        "https://www.semi.org/q2-2025": """
            MILPITAS, Calif. - September 2, 2025 - Global semiconductor equipment
            billings reached US$33.07 billion in the second quarter of 2025.
        """,
        "https://www.semi.org/q1-2025": """
            MILPITAS, Calif. - June 3, 2025 - Global semiconductor equipment
            billings reached US$29.00 billion in the first quarter of 2025.
        """,
        "https://www.semi.org/q4-2024": """
            MILPITAS, Calif. - March 3, 2025 - Global semiconductor equipment
            billings reached US$30.00 billion in the fourth quarter of 2024.
        """,
        "https://www.semi.org/q3-2024": """
            MILPITAS, Calif. - December 2, 2024 - Global semiconductor equipment
            billings reached US$28.00 billion in the third quarter of 2024.
        """,
    }
    calls: list[str] = []

    def fake_get(url: str, **_kwargs: object) -> Response:
        calls.append(url)
        if url in pages:
            return Response(pages[url])
        if url in articles:
            return Response(articles[url])
        return Response("", status_code=404)

    monkeypatch.setattr(
        "stock_data.fetcher.industry.semiconductor.collectors.semi_crawler.requests.get",
        fake_get,
    )

    items = SemiEquipmentCrawler(raw_dir=tmp_path).fetch_range(
        start_date=date(2024, 10, 1),
        end_date=date(2025, 6, 30),
        max_pages=5,
    )

    assert [item["report_quarter"] for item in items] == ["2024-Q4", "2025-Q1", "2025-Q2"]
    assert "https://www.semi.org/en/news-media/press-releases?page=2" in calls
    assert "https://www.semi.org/en/news-media/press-releases?page=3" not in calls
    assert (tmp_path / "semiconductor" / "semi" / "www-semi-org-q2-2025.html.gz").exists()


def test_semi_collector_uses_online_range_when_context_dates_are_provided(
    tmp_path: Path, monkeypatch
) -> None:
    collector = SemiEquipmentCollector(raw_dir=tmp_path)
    called: dict[str, object] = {}

    def fake_fetch_range(
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        force: bool = False,
    ) -> list[dict[str, object]]:
        called["start_date"] = start_date
        called["end_date"] = end_date
        called["force"] = force
        return [
            {
                "report_quarter": "2025-Q2",
                "trade_date": date(2025, 6, 30),
                "global_billings_raw": "US$33.07 billion",
                "china_billings_raw": None,
                "yoy_growth_raw": None,
                "qoq_growth_raw": None,
                "release_date": date(2025, 9, 2),
                "raw_content_sha256": "sha-2025q2",
                "raw_snapshot_path": "semiconductor/semi/q2.html.gz",
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
    assert raw_df["report_quarter"].to_list() == ["2025-Q2"]


def test_semi_crawler_replay_cached_snapshots_uses_snapshot_lineage(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "semiconductor" / "semi"
    snapshot_dir.mkdir(parents=True)
    html = """
    <html>
      <head><link rel="canonical" href="https://www.semi.org/cached-pr"></head>
      <body>
        MILPITAS, Calif. - September 2, 2025 - Global semiconductor equipment billings
        reached US$33.07 billion in the second quarter of 2025.
        China continues to lead in spending with billings of $12.00 billion.
      </body>
    </html>
    """
    snapshot = snapshot_dir / "cached.html"
    snapshot.write_text(html, encoding="utf-8")

    items = SemiEquipmentCrawler(raw_dir=tmp_path).replay_cached_snapshots()

    assert len(items) == 1
    assert items[0]["report_quarter"] == "2025-Q2"
    assert items[0]["source_url"] == "https://www.semi.org/cached-pr"
    assert items[0]["raw_content_sha256"] == raw_content_sha256(html.encode("utf-8"))
    assert items[0]["raw_snapshot_path"] == "semiconductor/semi/cached.html"


def test_semi_collector_collect_and_calc(tmp_path: Path, monkeypatch):
    collector = SemiEquipmentCollector(raw_dir=tmp_path)

    items = [
        {
            "report_quarter": "2023-Q3",
            "trade_date": date(2023, 9, 30),
            "global_billings_raw": "US$25.40 billion",
            "china_billings_raw": "$8.20 billion",
            "yoy_growth_raw": None,
            "qoq_growth_raw": None,
            "release_date": date(2023, 12, 4),
            "raw_content_sha256": "sha-2023q3",
            "raw_snapshot_path": "semiconductor/semi/2023q3.html.gz",
        },
        {
            "report_quarter": "2023-Q4",
            "trade_date": date(2023, 12, 31),
            "global_billings_raw": "US$26.50 billion",
            "china_billings_raw": "$8.70 billion",
            "yoy_growth_raw": None,
            "qoq_growth_raw": None,
            "release_date": date(2024, 3, 4),
            "raw_content_sha256": "sha-2023q4",
            "raw_snapshot_path": "semiconductor/semi/2023q4.html.gz",
        },
        {
            "report_quarter": "2024-Q1",
            "trade_date": date(2024, 3, 31),
            "global_billings_raw": "US$27.10 billion",
            "china_billings_raw": "$9.00 billion",
            "yoy_growth_raw": None,
            "qoq_growth_raw": None,
            "release_date": date(2024, 6, 3),
            "raw_content_sha256": "sha-2024q1",
            "raw_snapshot_path": "semiconductor/semi/2024q1.html.gz",
        },
        {
            "report_quarter": "2024-Q2",
            "trade_date": date(2024, 6, 30),
            "global_billings_raw": "US$26.88 billion",
            "china_billings_raw": "$9.15 billion",
            "yoy_growth_raw": None,
            "qoq_growth_raw": None,
            "release_date": date(2024, 9, 2),
            "raw_content_sha256": "sha-2024q2",
            "raw_snapshot_path": "semiconductor/semi/2024q2.html.gz",
        },
        {
            "report_quarter": "2024-Q3",
            "trade_date": date(2024, 9, 30),
            "global_billings_raw": "US$30.38 billion",
            "china_billings_raw": "$12.45 billion",
            "yoy_growth_raw": "19%",
            "qoq_growth_raw": "13%",
            "release_date": date(2024, 12, 2),
            "raw_content_sha256": "sha-2024q3",
            "raw_snapshot_path": "semiconductor/semi/2024q3.html.gz",
        },
        {
            "report_quarter": "2024-ANNUAL",
            "trade_date": date(2024, 12, 31),
            "source_record_type": "annual_source",
            "report_year": "2024",
            "global_billings_raw": None,
            "china_billings_raw": None,
            "annual_billings_raw": "$117.1 billion",
            "yoy_growth_raw": "10%",
            "qoq_growth_raw": None,
            "release_date": date(2025, 4, 9),
            "data_status": "annual_source",
            "raw_content_sha256": "sha-2024annual",
            "raw_snapshot_path": "semiconductor/semi/2024annual.html.gz",
        },
    ]

    monkeypatch.setattr(collector.crawler, "fetch_latest", lambda force=False: items)

    raw_df = collector.collect_raw(force=True)
    latest_raw = raw_df.filter(pl.col("report_quarter") == "2024-Q3")
    assert latest_raw["global_billings_raw"][0] == "US$30.38 billion"
    assert "global_billings_billion_usd" not in raw_df.columns
    assert latest_raw["raw_content_sha256"][0] == "sha-2024q3"
    assert latest_raw["raw_snapshot_path"][0] == "semiconductor/semi/2024q3.html.gz"
    annual_raw = raw_df.filter(pl.col("report_quarter") == "2024-ANNUAL")
    assert annual_raw["source_record_type"][0] == "annual_source"
    assert annual_raw["annual_billings_raw"][0] == "$117.1 billion"

    df = build_semi_equipment_curated_frame(raw_df)
    assert not df.is_empty()
    assert "global_billings_billion_usd" in df.columns
    assert "china_share_pct" in df.columns
    assert "release_date" in df.columns
    assert "raw_content_sha256" not in df.columns
    assert "raw_snapshot_path" not in df.columns

    latest = df.filter(pl.col("report_quarter") == "2024-Q3")
    assert latest["china_share_pct"][0] == 40.98
    assert latest["yoy_growth"][0] == 0.19
    assert latest["qoq_growth"][0] == 0.13
    derived_q4 = df.filter(pl.col("report_quarter") == "2024-Q4")
    assert derived_q4["global_billings_billion_usd"][0] == 32.74
    assert derived_q4["data_status"][0] == "derived_from_annual"
    assert derived_q4["source_url"][0] == "https://www.semi.org/en/news-media/press-releases"
