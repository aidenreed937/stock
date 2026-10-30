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


def test_semi_parser_annual_article_with_sidebar_quarter_link() -> None:
    """年度公报页面含侧栏'相关新闻 Qx YYYY'链接标题时，不得误判为季度公报。

    回归锚点：2025 年度公报（$135 Billion）被误解析为 2026-Q2（侧栏相关新闻
    "…Increased 23% Year-Over-Year in Q2 2026" 被 q_match 命中）。
    """
    sample_pr = """
    SEMI Reports Global Semiconductor Equipment Billings Reached $135 Billion in 2025,
    Up 15% Year-on-Year
    MILPITAS, Calif. - April 7, 2026 - Worldwide sales of semiconductor manufacturing
    equipment increased 15% to $135.1 billion in 2025 from $117.1 billion in 2024,
    driven by continued investment in advanced logic, memory, and AI-related capacity
    expansion.
    More Press Releases
    SEMI Press Release Sep 3, 2026 Global Semiconductor Equipment Billings Increased
    23% Year-Over-Year in Q2 2026, SEMI Reports Learn More
    """
    res = parse_semi_article_text(sample_pr, source_url="https://www.semi.org/annual-2025")

    assert res is not None
    assert res["report_quarter"] == "2025-ANNUAL"
    assert res["source_record_type"] == "annual_source"
    assert res["annual_billings_raw"] == "$135 Billion"
    assert res["annual_billings_billion_usd"] == 135.0
    assert res["data_status"] == "annual_source"


def test_semi_parser_annual_growth_must_come_from_claim_sentence() -> None:
    """年度同比只能来自年度声明本句，不得被页脚/侧栏"相关新闻"标题污染。

    回归锚点：线上 RAW 里 9 个年度行与 8 个季度行的 `yoy_growth_raw` 都曾被写成
    侧栏的 "23%"（累计 16 行），属全文误抓。
    """
    sample_pr = """
    SEMI Reports Global Semiconductor Equipment Billings Reached $135 Billion in 2025,
    Up 15% Year-on-Year
    MILPITAS, Calif. - April 7, 2026 - Worldwide sales of semiconductor manufacturing
    equipment increased 15% to $135.1 billion in 2025 from $117.1 billion in 2024,
    driven by continued investment in advanced logic, memory, and AI-related capacity
    expansion.
    More Press Releases
    SEMI Press Release Sep 3, 2026 Global Semiconductor Equipment Billings Increased
    23% Year-Over-Year in Q2 2026, SEMI Reports Learn More
    """
    res = parse_semi_article_text(sample_pr, source_url="https://www.semi.org/annual-2025")

    assert res is not None
    assert res["source_record_type"] == "annual_source"
    assert res["yoy_growth_raw"] is None


def test_semi_parser_annual_growth_still_captured_in_claim_sentence() -> None:
    """收窄窗口不能丢信息：年度声明本句带 year-over-year 时必须正常提取。"""
    sample_pr = """
    MILPITAS, Calif. - April 7, 2026 - Worldwide sales of semiconductor manufacturing
    equipment increased 15 percent year-over-year to $135.1 billion in 2025.
    More Press Releases
    23% Year-Over-Year in Q2 2026
    """
    res = parse_semi_article_text(sample_pr, source_url="https://www.semi.org/annual-2025")

    assert res is not None
    assert res["source_record_type"] == "annual_source"
    assert res["yoy_growth_raw"] == "15%"


_REGIONAL_TABLE_2018Q1 = """
<p>global semiconductor equipment billings reached US$17.0 billion in the first quarter of 2018.</p>
<p>Following are quarterly billings data by region in billions of U.S. dollars:</p>
<table><tbody>
<tr>
  <td><p>&nbsp;</p></td><td><p>1Q2018</p></td><td><p>4Q2017</p></td><td><p>1Q2017</p></td>
  <td><p>1Q18/4Q17 (Qtr-over-Qtr)</p></td><td><p>1Q18/1Q17 (Year-over-Year)</p></td>
</tr>
<tr><td><p><strong>Korea</strong></p></td><td><p>6.26</p></td><td><p>4.64</p></td><td><p>3.53</p></td><td><p>35%</p></td><td><p>78%</p></td></tr>
<tr><td><p><strong>China</strong></p></td><td><p>2.64</p></td><td><p>1.77</p></td><td><p>2.01</p></td><td><p>49%</p></td><td><p>31%</p></td></tr>
<tr><td><p><strong>Taiwan</strong></p></td><td><p>2.27</p></td><td><p>2.89</p></td><td><p>3.48</p></td><td><p>-22%</p></td><td><p>-35%</p></td></tr>
<tr><td><p><strong>Japan</strong></p></td><td><p>2.13</p></td><td><p>1.96</p></td><td><p>1.25</p></td><td><p>9%</p></td><td><p>70%</p></td></tr>
<tr><td><p><strong>North America</strong></p></td><td><p>1.14</p></td><td><p>1.58</p></td><td><p>1.27</p></td><td><p>-28%</p></td><td><p>-10%</p></td></tr>
<tr><td><p><strong>Total</strong></p></td><td><p>16.99</p></td><td><p>15.10</p></td><td><p>13.08</p></td><td><p>12%</p></td><td><p>30%</p></td></tr>
</tbody></table>
"""


def test_semi_parser_extracts_china_billings_from_regional_table() -> None:
    """区域表里的 China 当季出货额必须被解析出来。

    回归锚点：线上 Curated 的 `china_billings_billion_usd` 曾全 34 行为空——根因是
    解析器只认正文 `China … $X billion` 措辞，漏掉了表格里的裸数字，使
    `china_share_pct` 与对账报告的"中国占比"段一并失效。
    """
    res = parse_semi_article_text(_REGIONAL_TABLE_2018Q1, source_url="https://www.semi.org/q1-2018")

    assert res is not None
    assert res["report_quarter"] == "2018-Q1"
    assert res["china_billings_raw"] == "2.64"
    assert res["china_billings_billion_usd"] == 2.64

    regions = res["regional_billings"]
    assert regions is not None
    assert regions["China"]["billings_billion_usd"] == 2.64
    assert regions["China"]["yoy_raw"] == "31%"
    assert regions["North America"]["billings_raw"] == "1.14"
    assert regions["Korea"]["qoq_raw"] == "35%"
    # Total 不是区域，不得混入
    assert "Total" not in regions
    # 表头按源端原样保留（血统），不做规范化改写
    assert res["regional_billings_header_raw"] == (
        "1Q2018 | 4Q2017 | 1Q2017 | 1Q18/4Q17 (Qtr-over-Qtr) | 1Q18/1Q17 (Year-over-Year)"
    )


def test_semi_parser_regional_table_with_explicit_region_header() -> None:
    """表头首列是 "Region" 的写法（如 Q1 2020 公报）同样要能解析。"""
    sample = """
    <p>global semiconductor equipment billings reached US$15.57 billion in the first quarter of 2020.</p>
    <p>quarter-over-quarter and year-over-year change by region are as follows:</p>
    <table><tbody>
    <tr><td><p><strong>Region</strong></p></td><td><p><strong>Q12020</strong></p></td><td><p><strong>Q42019</strong></p></td>
        <td><p><strong>Q12019</strong></p></td><td><p><strong>1Q2020/4Q2019</strong></p></td><td><p><strong>1Q2020/1Q2019</strong></p></td></tr>
    <tr><td><p>Taiwan</p></td><td><p>4.02</p></td><td><p>6.20</p></td><td><p>3.81</p></td><td><p>-35%</p></td><td><p>6%</p></td></tr>
    <tr><td><p>China</p></td><td><p>3.50</p></td><td><p>4.29</p></td><td><p>2.36</p></td><td><p>-18%</p></td><td><p>48%</p></td></tr>
    <tr><td><p>Korea</p></td><td><p>3.36</p></td><td><p>2.30</p></td><td><p>2.89</p></td><td><p>46%</p></td><td><p>16%</p></td></tr>
    <tr><td><p>North America</p></td><td><p>1.93</p></td><td><p>2.28</p></td><td><p>1.67</p></td><td><p>-16%</p></td><td><p>15%</p></td></tr>
    <tr><td><p>Rest of the World</p></td><td><p>0.44</p></td><td><p>0.58</p></td><td><p>0.67</p></td><td><p>-24%</p></td><td><p>-34%</p></td></tr>
    </tbody></table>
    """
    res = parse_semi_article_text(sample, source_url="https://www.semi.org/q1-2020")

    assert res is not None
    assert res["report_quarter"] == "2020-Q1"
    assert res["china_billings_raw"] == "3.50"
    regions = res["regional_billings"]
    assert regions is not None
    assert regions["Rest of World"]["billings_billion_usd"] == 0.44


def test_semi_parser_ignores_regional_table_of_another_quarter() -> None:
    """表头季度与本公报报告期不一致时不得采信（防‘相关新闻’他期表格误抓）。"""
    sample = _REGIONAL_TABLE_2018Q1.replace("1Q2018", "2Q2018")

    res = parse_semi_article_text(sample, source_url="https://www.semi.org/q1-2018")

    assert res is not None
    assert res["report_quarter"] == "2018-Q1"
    assert res["regional_billings"] is None
    assert res["china_billings_raw"] is None


def test_semi_parser_returns_no_regional_table_when_only_image_present() -> None:
    """区域表改为内嵌图片发布时（2021 年起多数期次）不得凭空产出 China 值。"""
    sample = """
    <p>global semiconductor equipment billings reached US$30.38 billion in the third quarter of 2024.</p>
    <p>Following are quarterly billings data in billions of U.S. dollars by region:</p>
    <img alt="Semiconductor Equipment Billings by region" src="/sites/semi.org/image_256.png.webp">
    """
    res = parse_semi_article_text(sample, source_url="https://www.semi.org/q3-2024")

    assert res is not None
    assert res["report_quarter"] == "2024-Q3"
    assert res["regional_billings"] is None
    assert res["china_billings_raw"] is None
    assert res["china_billings_billion_usd"] is None


def test_semi_parser_real_q2_2026_article() -> None:
    """真实 2026-Q2 公报（US$40.53 billion）正确解析为季度记录。"""
    sample_pr = """
    SEMI Reports Global Semiconductor Equipment Billings Increased 23% Year-Over-Year
    in Q2 2026, SEMI Reports
    MILPITAS, Calif. - September 3, 2026 - SEMI, the industry association advancing
    the global semiconductor and electronics design and manufacturing supply chain,
    today announced in its Worldwide Semiconductor Equipment Market Statistics
    (WWSEMS) report that global semiconductor equipment billings increased 23%
    year-over-year to US$40.53 billion in the second quarter of 2026. Second quarter
    2026 billings registered an 11% quarter-over-quarter growth.
    """
    res = parse_semi_article_text(sample_pr, source_url="https://www.semi.org/q2-2026")

    assert res is not None
    assert res["report_quarter"] == "2026-Q2"
    assert res["trade_date"] == date(2026, 6, 30)
    assert res["global_billings_billion_usd"] == 40.53
    assert res["global_billings_raw"] == "US$40.53 billion"
    assert res["yoy_growth_raw"] == "23%"
    assert res["qoq_growth_raw"] == "11%"
    assert res["release_date"] == date(2026, 9, 3)


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
    assert res["china_billings_raw"] is None
    assert res["china_billings_billion_usd"] is None
    assert res["data_status"] == "annual_source"


def test_semi_parser_extracts_annual_china_billings_from_prose() -> None:
    sample_pr = """
    MILPITAS, Calif. - April 7, 2026 - Worldwide sales of semiconductor manufacturing
    equipment increased 15% to $135 billion in 2025. In 2025, spending in China
    remained near record levels at $49.3 billion, down just 0.5% from the prior year.
    """

    res = parse_semi_article_text(sample_pr, source_url="https://www.semi.org/annual-2025")

    assert res is not None
    assert res["report_quarter"] == "2025-ANNUAL"
    assert res["china_billings_raw"] == "$49.3 billion"
    assert res["china_billings_billion_usd"] == 49.3


def test_semi_parser_extracts_annual_china_billings_from_legacy_table() -> None:
    sample_pr = """
    2018 Global Semiconductor Equipment Sales Jump to Record $64.5 Billion.
    The annual billings data by region are as follows:
    <table><tr><th>Region</th><th>2018</th><th>2017</th><th>% Change</th></tr>
    <tr><td>China</td><td>13.11</td><td>8.23</td><td>59%</td></tr>
    <tr><td>Total</td><td>64.53</td><td>56.62</td><td>14%</td></tr></table>
    """

    res = parse_semi_article_text(sample_pr, source_url="https://www.semi.org/annual-2018")

    assert res is not None
    assert res["report_quarter"] == "2018-ANNUAL"
    assert res["china_billings_raw"] == "13.11"
    assert res["china_billings_billion_usd"] == 13.11


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


def test_semi_crawler_replay_applies_regional_image_ledger(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "semiconductor" / "semi"
    snapshot_dir.mkdir(parents=True)
    html = """
    <html>
      <head><link rel="canonical" href="https://www.semi.org/cached-pr"></head>
      <body>
        MILPITAS, Calif. - September 2, 2025 - Global semiconductor equipment billings
        reached US$33.07 billion in the second quarter of 2025.
      </body>
    </html>
    """
    (snapshot_dir / "cached.html").write_text(html, encoding="utf-8")
    image_bytes = b"regional-image"
    image_path = snapshot_dir / "regional_billings_2025-Q2.webp"
    image_path.write_bytes(image_bytes)
    (snapshot_dir / "regional_billings_image_ledger.csv").write_text(
        "report_quarter,image_source_url,image_snapshot_path,image_sha256,"
        "extraction_method,verified_at,global_billings_billion_usd,"
        "regional_sum_billion_usd,reconciliation_diff_billion_usd,"
        "china_billings_billion_usd\n"
        "2025-Q2,https://www.semi.org/image,"
        "semiconductor/semi/regional_billings_2025-Q2.webp,"
        f"{raw_content_sha256(image_bytes)},manual_visual_verification,2026-09-10,"
        "33.07,33.07,0.00,11.36\n",
        encoding="utf-8",
    )

    items = SemiEquipmentCrawler(raw_dir=tmp_path).replay_cached_snapshots()

    assert len(items) == 1
    assert items[0]["china_billings_billion_usd"] == 11.36
    assert items[0]["china_billings_raw"] == "11.36"


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
            "china_billings_raw": "$49.60 billion",
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
    # yoy/qoq 由出货额序列 pct_change 自算，不再采信源端 "19%"/"13%" 字符串
    assert latest["yoy_growth"][0] == 0.1961
    assert latest["qoq_growth"][0] == 0.1302
    derived_q4 = df.filter(pl.col("report_quarter") == "2024-Q4")
    assert derived_q4["global_billings_billion_usd"][0] == 32.74
    assert derived_q4["china_billings_billion_usd"][0] == 19.0
    assert derived_q4["china_share_pct"][0] == 58.03
    assert derived_q4["data_status"][0] == "derived_from_annual"
    assert derived_q4["source_url"][0] == "https://www.semi.org/en/news-media/press-releases"


def test_semi_curated_keeps_q4_china_null_when_a_first_three_quarter_is_missing() -> None:
    raw = pl.DataFrame(
        {
            "report_quarter": ["2024-Q1", "2024-Q2", "2024-Q3", "2024-ANNUAL"],
            "trade_date": [
                date(2024, 3, 31),
                date(2024, 6, 30),
                date(2024, 9, 30),
                date(2024, 12, 31),
            ],
            "source_record_type": [
                "quarterly_actual",
                "quarterly_actual",
                "quarterly_actual",
                "annual_source",
            ],
            "report_year": ["2024", "2024", "2024", "2024"],
            "global_billings_billion_usd": [10.0, 11.0, 12.0, None],
            "china_billings_billion_usd": [3.0, None, 4.0, 20.0],
            "annual_billings_billion_usd": [None, None, None, 50.0],
            "release_date": [
                date(2024, 6, 3),
                date(2024, 9, 2),
                date(2024, 12, 2),
                date(2025, 4, 9),
            ],
        }
    )

    curated = build_semi_equipment_curated_frame(raw)

    derived_q4 = curated.filter(pl.col("report_quarter") == "2024-Q4")
    assert derived_q4["global_billings_billion_usd"][0] == 17.0
    assert derived_q4["china_billings_billion_usd"][0] is None
    assert derived_q4["china_share_pct"][0] is None


def test_semi_parser_extracts_annual_total_from_table() -> None:
    sample_pr = """
    Worldwide sales of semiconductor equipment reached $41.2 billion in 2016, SEMI reports.
    <table>
      <tr><th>Region</th><th>2016</th><th>2015</th></tr>
      <tr><td>China</td><td>6.46</td><td>4.90</td></tr>
      <tr><td>Total</td><td>41.24</td><td>36.53</td></tr>
    </table>
    """
    res = parse_semi_article_text(sample_pr, source_url="https://www.semi.org/annual-2016")
    assert res is not None
    assert res["report_quarter"] == "2016-ANNUAL"
    assert res["annual_billings_billion_usd"] == 41.24
    assert res["china_billings_billion_usd"] == 6.46


def test_semi_curated_backfill_2016_2017_closure() -> None:
    raw = pl.DataFrame(
        {
            "report_quarter": [
                "2016-Q1",
                "2016-Q2",
                "2016-Q3",
                "2016-ANNUAL",
                "2017-Q1",
                "2017-Q2",
                "2017-Q3",
                "2017-ANNUAL",
            ],
            "trade_date": [
                date(2016, 3, 31),
                date(2016, 6, 30),
                date(2016, 9, 30),
                date(2016, 12, 31),
                date(2017, 3, 31),
                date(2017, 6, 30),
                date(2017, 9, 30),
                date(2017, 12, 31),
            ],
            "source_record_type": [
                "quarterly_actual",
                "quarterly_actual",
                "quarterly_actual",
                "annual_source",
                "quarterly_actual",
                "quarterly_actual",
                "quarterly_actual",
                "annual_source",
            ],
            "report_year": ["2016", "2016", "2016", "2016", "2017", "2017", "2017", "2017"],
            "global_billings_billion_usd": [8.28, 10.46, 10.98, None, 13.08, 14.11, 14.33, None],
            "china_billings_billion_usd": [1.60, 2.27, 1.43, 6.46, 2.01, 2.51, 1.93, 8.23],
            "annual_billings_billion_usd": [None, None, None, 41.24, None, None, None, 56.62],
            "release_date": [
                date(2016, 6, 7),
                date(2016, 9, 8),
                date(2016, 12, 1),
                date(2017, 3, 13),
                date(2017, 6, 1),
                date(2017, 9, 11),
                date(2017, 12, 4),
                date(2018, 4, 5),
            ],
        }
    )
    curated = build_semi_equipment_curated_frame(raw)
    assert curated.height == 8

    q4_2016 = curated.filter(pl.col("report_quarter") == "2016-Q4")
    assert q4_2016["global_billings_billion_usd"][0] == 11.52
    assert q4_2016["china_billings_billion_usd"][0] == 1.16
    assert q4_2016["china_share_pct"][0] == 10.07
    assert q4_2016["data_status"][0] == "derived_from_annual"

    q4_2017 = curated.filter(pl.col("report_quarter") == "2017-Q4")
    assert q4_2017["global_billings_billion_usd"][0] == 15.10
    assert q4_2017["china_billings_billion_usd"][0] == 1.78
    assert q4_2017["china_share_pct"][0] == 11.79
    assert q4_2017["data_status"][0] == "derived_from_annual"

    q1_2017 = curated.filter(pl.col("report_quarter") == "2017-Q1")
    assert q1_2017["yoy_growth"][0] == 0.5797
