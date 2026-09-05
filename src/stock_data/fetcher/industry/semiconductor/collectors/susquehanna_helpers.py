"""Susquehanna 公开报道采集的月份与链接辅助函数。"""

from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, unquote, urlsplit


def _target_months(start_date: date | None, end_date: date | None) -> set[str] | None:
    if start_date is None and end_date is None:
        return None
    start = start_date or end_date
    end = end_date or start_date
    if start is None or end is None:
        return None
    start = start.replace(day=1)
    end = end.replace(day=1)
    months: set[str] = set()
    cursor = start
    while cursor <= end:
        months.add(f"{cursor.year:04d}-{cursor.month:02d}")
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    return months


def _month_floor(value: date, months_ago: int) -> date:
    index = value.year * 12 + value.month - 1 - max(months_ago, 0)
    return date(index // 12, index % 12 + 1, 1)


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _is_allowed_host(host: str, domains: frozenset[str]) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _resolve_feed_link(link: str) -> str:
    """展开 Bing/Google 新闻包装链接，得到可抓取的媒体文章地址。"""
    query = parse_qs(urlsplit(link).query)
    for key in ("url", "u"):
        values = query.get(key, ())
        if values:
            candidate = unquote(values[0])
            if candidate.startswith(("http://", "https://")):
                return candidate
    return link


def _is_google_news_article(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.netloc.lower() == "news.google.com" and "/rss/articles/" in parsed.path
