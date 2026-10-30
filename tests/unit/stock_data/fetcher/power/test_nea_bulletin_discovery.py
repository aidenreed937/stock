"""国家能源局通报发现机制契约测试。

回归背景：通报离开官网首页后，仅扫首页的发现逻辑再也找不到它；且标题由半角连字符
（1-7月份）改为全角破折号（1—8月份）后，月份正则解析直接失效。本测试锁定这两处。
"""

from datetime import date

from stock_data.fetcher.industry.power.collectors import nea_crawler
from stock_data.fetcher.industry.power.collectors.nea_crawler import (
    NEA_BASE_URL,
    NEA_SEARCH_KEYWORDS,
    NEA_SEARCH_URL,
    NeaBulletinCrawler,
    _extract_month_key,
)

_HOMEPAGE_URL = NEA_BASE_URL
_ARTICLE_URL = "http://www.nea.gov.cn/20260924/1430d07985474c5b8110552785f1c74b/c.html"


class _SearchResponse:
    """站内搜索 JSON 响应替身。"""

    status_code = 200

    def __init__(self, rows):
        self._rows = rows

    def json(self):
        return {"code": 200, "content": {"result": self._rows}}


class _HtmlResponse:
    """最小 HTML 响应替身（文章正文的 raw snapshot 依赖 .content）。"""

    status_code = 200
    encoding = "utf-8"

    def __init__(self, text: str) -> None:
        self.text = text
        self.content = text.encode("utf-8")


def test_extract_release_date_ignores_report_period_range() -> None:
    """报告期区间（1-6月份）不能被误读成发布日期。"""
    body = "国家能源局发布2026年1-6月份全国电力统计数据发布时间：2026-07-22来源：国家能源局"
    assert nea_crawler._extract_release_date(body) == "2026-07-22"
    assert nea_crawler._extract_release_date("发布时间：2026年7月22日 正文") == "2026-07-22"
    assert nea_crawler._extract_release_date("无任何日期标注") is None


def test_extract_month_key_handles_fullwidth_dash_range() -> None:
    assert _extract_month_key("国家能源局发布2026年1—8月份全国电力统计数据") == "2026-08"
    assert _extract_month_key("国家能源局发布2026年1-7月份全国电力统计数据") == "2026-07"
    assert _extract_month_key("国家能源局发布2026年1～5月份全国电力统计数据") == "2026-05"


def test_extract_month_key_year_bulletin_falls_back_to_december() -> None:
    assert _extract_month_key("国家能源局发布2025年全国电力统计数据") == "2025-12"
    assert _extract_month_key("国家能源局发布2025年全国电力工业统计数据") == "2025-12"
    assert _extract_month_key("国家能源局发布2026年8月全国绿证数据") is None


def test_search_bulletins_queries_both_keywords_with_browser_headers(monkeypatch) -> None:
    calls = []
    rows_by_keyword = {
        "全国电力统计数据": [
            {
                "title": "国家能源局发布2026年1—8月份<font color=red>全国电力统计数据</font>",
                "originUrl": ["http://www.nea.gov.cn/20260924/deadbeef/c.html"],
            }
        ],
        "全国电力工业统计数据": [
            {
                "title": "国家能源局发布2025年1-11月份全国电力工业统计数据",
                "originUrl": ["http://www.nea.gov.cn/20251226/cafebabe/c.html"],
            }
        ],
    }

    def fake_get(url, *, params, headers, timeout):
        calls.append({"url": url, "params": params, "headers": headers})
        return _SearchResponse(rows_by_keyword[params["keyword"]])

    monkeypatch.setattr(nea_crawler.requests, "get", fake_get)
    candidates = nea_crawler._search_bulletins(start_date=None, end_date=None)

    assert [call["params"]["keyword"] for call in calls] == list(NEA_SEARCH_KEYWORDS)
    assert all(call["url"] == NEA_SEARCH_URL for call in calls)
    for call in calls:
        assert call["headers"]["X-Requested-With"] == "XMLHttpRequest"
        assert call["headers"]["Referer"] == f"{NEA_BASE_URL}/"
        assert call["headers"]["Origin"] == NEA_BASE_URL
    assert sorted(candidates) == sorted(
        [
            (
                "国家能源局发布2026年1—8月份全国电力统计数据",
                "http://www.nea.gov.cn/20260924/deadbeef/c.html",
            ),
            (
                "国家能源局发布2025年1-11月份全国电力工业统计数据",
                "http://www.nea.gov.cn/20251226/cafebabe/c.html",
            ),
        ]
    )


def test_search_bulletins_breaks_page_loop_when_page_empty(monkeypatch) -> None:
    pages = []

    def fake_get(url, *, params, headers, timeout):
        pages.append(int(params["pageNo"]))
        return _SearchResponse([])

    monkeypatch.setattr(nea_crawler.requests, "get", fake_get)
    assert nea_crawler._search_bulletins(start_date=None, end_date=None, max_pages=5) == []
    assert pages == [1, 1]


def test_search_bulletins_returns_empty_on_http_error(monkeypatch) -> None:
    class _Forbidden:
        status_code = 403

    monkeypatch.setattr(nea_crawler.requests, "get", lambda *a, **k: _Forbidden())
    assert nea_crawler._search_bulletins(start_date=None, end_date=None) == []


def test_fetch_latest_bulletins_recovers_bulletin_missing_from_homepage(
    tmp_path, monkeypatch
) -> None:
    """首页已无该通报时，仍能经站内搜索发现并入库（本 bug 的回归测试）。"""
    homepage_html = (
        "<html><body>"
        "<a href='/20260930/aaa/c.html'>国家能源局发布2026年8月全国可再生能源"
        "绿色电力证书核发及交易数据</a>"
        "</body></html>"
    )
    article_html = (
        "<html><body>2026年9月24日，国家能源局发布1—8月份全国电力统计数据。"
        "截至8月底，全国累计发电装机容量41.03亿千瓦，同比增长11.1%。其中，太阳能发电装机容量"
        "12.99亿千瓦，同比增长16.3%；风电装机容量6.93亿千瓦。</body></html>"
    )
    search_rows = [
        {
            "title": "国家能源局发布2026年1—8月份<font color=red>全国电力统计数据</font>",
            "originUrl": [_ARTICLE_URL],
        }
    ]

    def fake_get(url, headers=None, **kwargs):
        if url == _HOMEPAGE_URL:
            return _HtmlResponse(homepage_html)
        if url == NEA_SEARCH_URL:
            rows = (
                search_rows
                if kwargs.get("params", {}).get("keyword") == NEA_SEARCH_KEYWORDS[0]
                else []
            )
            return _SearchResponse(rows)
        assert url == _ARTICLE_URL
        return _HtmlResponse(article_html)

    monkeypatch.setattr(nea_crawler.requests, "get", fake_get)
    monkeypatch.setattr(nea_crawler.time, "sleep", lambda _seconds: None)

    crawler = NeaBulletinCrawler(raw_dir=tmp_path)
    cached = crawler.fetch_latest_bulletins()

    assert crawler.last_fetched_periods == ("2026-08",)
    assert cached["2026-08"]["cumulative_gw"] == 1299.0
    assert cached["2026-08"]["yoy_growth"] == 0.163
    assert (tmp_path / "power" / "nea" / "bulletins" / "2026-08.html.gz").exists()


def test_fetch_latest_bulletins_skips_cached_months(tmp_path, monkeypatch) -> None:
    """已有水位且非 force 时不应重复抓取文章（克制爬取）。"""
    cached = {
        "2026-08": {
            "report_month": "2026-08",
            "title": "国家能源局发布2026年1—8月份全国电力统计数据",
            "url": _ARTICLE_URL,
            "cumulative_gw": 1299.0,
            "yoy_growth": 0.163,
            "release_date": date(2026, 9, 24).isoformat(),
        }
    }
    crawler = NeaBulletinCrawler(raw_dir=tmp_path)
    monkeypatch.setattr(crawler, "_load_cache", lambda: dict(cached))
    monkeypatch.setattr(
        crawler,
        "_search_bulletins",
        lambda **kwargs: [("国家能源局发布2026年1—8月份全国电力统计数据", _ARTICLE_URL)],
    )

    def fake_get(url, headers=None, **kwargs):
        if url == _HOMEPAGE_URL:
            return _HtmlResponse("<html><body>首页无统计通报链接</body></html>")
        raise AssertionError("已有水位时不应再抓取文章")

    monkeypatch.setattr(nea_crawler.requests, "get", fake_get)

    result = crawler.fetch_latest_bulletins()

    assert crawler.last_fetched_periods == ()
    assert result["2026-08"]["cumulative_gw"] == 1299.0
