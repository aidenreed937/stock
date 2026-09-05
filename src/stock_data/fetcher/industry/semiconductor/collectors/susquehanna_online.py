"""Susquehanna 公开报道在线发现、抓取与 RAW 归档实现。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from curl_cffi import requests

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
    save_raw_snapshot,
)
from stock_data.fetcher.industry.semiconductor.collectors.susquehanna_helpers import (
    _host,
    _is_allowed_host,
    _is_google_news_article,
    _month_floor,
    _resolve_feed_link,
)
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
    response_content_bytes,
)
from stock_data.fetcher.industry.semiconductor.models import ChipLeadTimeRecord
from stock_data.fetcher.industry.semiconductor.parsers.lead_time_raw import (
    determine_lead_time_status,
)
from stock_data.fetcher.industry.semiconductor.parsers.susquehanna import (
    archive_susquehanna_raw_snapshot,
    html_to_visible_text,
    parse_susquehanna_lead_time_article,
    parse_susquehanna_published_date,
    parse_susquehanna_rss_feed,
)

logger = logging.getLogger(__name__)

DEFAULT_SUSQUEHANNA_RSS_URL = (
    "https://news.google.com/rss/search?"
    "q=%22Susquehanna%22+%22weeks%22+%22lead%22&hl=en-US&gl=US&ceid=US:en"
)
DEFAULT_SUSQUEHANNA_DOMAINS = frozenset(
    {
        "astutegroup.com",
        "bloomberg.com",
        "electronicsweekly.com",
        "finance.yahoo.com",
        "marketwatch.com",
        "msn.com",
        "seekingalpha.com",
        "techspot.com",
        "theregister.com",
        "ttnews.com",
    }
)
GOOGLE_NEWS_BATCH_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
MSN_DETAIL_URL = "https://assets.msn.com/content/view/v2/Detail/{locale}/{article_id}"
DEFAULT_LOOKBACK_MONTHS = 18
DEFAULT_MAX_FEED_ITEMS = 30
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_ARTICLE_CHARS = 200_000
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
}


def collect_susquehanna_online(
    *,
    raw_root: Path,
    rss_urls: tuple[str, ...],
    source_domains: frozenset[str],
    target_months: set[str] | None,
    existing_months: set[str],
    force: bool,
    thresholds: dict[str, float],
    timeout: int,
    lookback_months: int,
    max_feed_items: int,
    max_article_chars: int,
    infer_report_month: bool,
    allow_rss_excerpt: bool,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """发现、解析并归档请求窗口内的 Susquehanna 报道。"""
    if not rss_urls:
        return (), ("未配置 Susquehanna 公开报道 RSS 地址",)

    candidates: dict[str, tuple[dict[str, object], bytes, str]] = {}
    errors: list[str] = []
    seen_urls: set[str] = set()
    for feed_url in rss_urls:
        response = _get(feed_url, timeout)
        if response is None:
            errors.append(f"RSS 请求失败: {feed_url}")
            continue
        feed_bytes = response_content_bytes(response)
        feed_items = parse_susquehanna_rss_feed(feed_bytes)
        feed_hash = raw_content_sha256(feed_bytes)
        save_raw_snapshot(
            source_name="lead_time",
            snapshot_filename=f"susquehanna_feed_{feed_hash[:12]}.xml",
            content=feed_bytes,
            base_dir=raw_root,
        )
        for item in feed_items[:max_feed_items]:
            if not _is_candidate_item(item):
                continue
            link = _resolve_feed_link(item["link"])
            if link in seen_urls:
                continue
            seen_urls.add(link)
            published = parse_susquehanna_published_date(item.get("pub_date"))
            if target_months is None and published is not None:
                if published < _month_floor(date.today(), lookback_months):
                    continue
            hint = parse_susquehanna_lead_time_article(
                item.get("title", ""),
                html_to_visible_text(item.get("description", "")),
                link,
                published,
                infer_report_month=False,
            )
            if hint is not None:
                hinted_month = str(hint["report_month"])
                if target_months is not None and hinted_month not in target_months:
                    continue
                if hinted_month in existing_months and not force:
                    continue

            article = _get(link, timeout)
            if article is None:
                continue
            source_url = str(getattr(article, "url", "") or link)
            host = _host(source_url)
            if source_domains and not _is_allowed_host(host, source_domains):
                continue
            article_bytes = response_content_bytes(article)
            article_text = html_to_visible_text(article_bytes, max_article_chars)
            source_kind = "article_html"
            if host == "msn.com":
                msn_detail = _fetch_msn_detail(link, timeout, max_article_chars)
                if msn_detail is not None:
                    source_url, article_bytes, article_text = msn_detail
                    source_kind = "msn_detail_json"
            if source_domains and not _is_allowed_host(_host(source_url), source_domains):
                continue
            parsed = parse_susquehanna_lead_time_article(
                item.get("title", ""),
                article_text,
                source_url,
                published,
                infer_report_month=infer_report_month,
            )
            source_content = article_bytes
            if parsed is None and allow_rss_excerpt:
                parsed = parse_susquehanna_lead_time_article(
                    item.get("title", ""),
                    html_to_visible_text(item.get("description", "")),
                    source_url,
                    published,
                    infer_report_month=False,
                )
                source_kind = "rss_excerpt"
                source_content = item.get("description", "").encode("utf-8")
            if parsed is None:
                continue
            report_month = str(parsed["report_month"])
            if target_months is not None and report_month not in target_months:
                continue
            if report_month in existing_months and not force:
                continue
            candidates.setdefault(report_month, (parsed, source_content, source_kind))

    fetched: list[str] = []
    for report_month, (parsed, source_content, source_kind) in sorted(candidates.items()):
        record = _build_record(parsed, thresholds)
        source_path, _metadata_path = archive_susquehanna_raw_snapshot(
            raw_root,
            record,
            source_content,
            source_kind=source_kind,
            report_month_inferred=bool(parsed.get("report_month_inferred", False)),
        )
        record = replace(
            record,
            raw_content_sha256=raw_content_sha256(source_content),
            raw_snapshot_path=raw_snapshot_path_value(source_path, raw_root),
        )
        fetched.append(report_month)
        logger.info(
            "在线采集 Susquehanna 交期: %s %.2f 周 (%s)",
            report_month,
            record.avg_lead_time_weeks,
            record.source,
        )
    return tuple(fetched), tuple(errors)


def _build_record(parsed: dict[str, object], thresholds: dict[str, float]) -> ChipLeadTimeRecord:
    report_month = str(parsed["report_month"])
    year, month = parse_month_string(report_month)
    release_date = parsed["release_date"]
    if not isinstance(release_date, date):
        raise ValueError(f"Susquehanna 报道发布日期无效: {release_date!r}")
    avg_value = parsed["avg_lead_time_weeks"]
    if not isinstance(avg_value, int | float | str):
        raise ValueError(f"Susquehanna 交期周数无效: {avg_value!r}")
    avg_weeks = float(avg_value)
    return ChipLeadTimeRecord(
        report_month=report_month,
        trade_date=get_month_end_date(year, month),
        avg_lead_time_weeks=avg_weeks,
        lead_time_status=determine_lead_time_status(avg_weeks, thresholds),
        unit="weeks",
        source=str(parsed["source"]),
        source_url=str(parsed["source_url"]),
        release_date=release_date,
        data_status=str(parsed.get("data_status", "actual")),
        collected_at=now_utc_iso(),
        lead_time_raw=str(parsed["lead_time_raw"]),
    )


def _get(url: str, timeout: int) -> Any | None:
    for attempt in range(2):
        try:
            response = requests.get(
                url,
                headers=DEFAULT_HEADERS,
                timeout=timeout,
                allow_redirects=True,
                impersonate="chrome120",
            )
            if response.status_code == 200:
                if _is_google_news_article(url):
                    resolved_url = _decode_google_news_url(
                        url, response_content_bytes(response), timeout
                    )
                    if resolved_url is None:
                        return None
                    return _get(resolved_url, timeout)
                return response
            if response.status_code not in {403, 429}:
                break
        except Exception as exc:  # noqa: BLE001
            logger.warning("请求 Susquehanna 公开来源失败 [%s]: %s", url, exc)
            break
        if attempt == 0:
            logger.debug("Susquehanna 公开来源暂时拒绝请求，准备重试: %s", url)
    logger.warning("Susquehanna 公开来源请求未成功 [%s]", url)
    return None


def _fetch_msn_detail(
    article_url: str, timeout: int, max_article_chars: int
) -> tuple[str, bytes, str] | None:
    match = re.search(
        r"/(?P<locale>[a-z]{2}-[a-z]{2})/.*?/ar-(?P<article_id>[A-Za-z0-9]+)",
        article_url,
    )
    if match is None:
        return None
    detail_url = MSN_DETAIL_URL.format(
        locale=match.group("locale"), article_id=match.group("article_id")
    )
    response = _get(detail_url, timeout)
    if response is None:
        return None
    content = response_content_bytes(response)
    try:
        payload = json.loads(content.decode("utf-8"))
    except (TypeError, ValueError):
        return None
    body = payload.get("body") if isinstance(payload, dict) else None
    if not isinstance(body, str) or not body.strip():
        return None
    source_url = payload.get("sourceHref") if isinstance(payload, dict) else None
    return (
        str(source_url or article_url),
        content,
        html_to_visible_text(body, max_article_chars),
    )


def _decode_google_news_url(url: str, landing_page: bytes, timeout: int) -> str | None:
    """用 Google News 公共 batchexecute 接口解析现代文章包装链接。"""
    page = landing_page.decode("utf-8", errors="ignore")
    signature = re.search(r'data-n-a-sg="([^"]+)"', page)
    timestamp = re.search(r'data-n-a-ts="(\d+)"', page)
    if signature is None or timestamp is None:
        return None
    article_id = urlsplit(url).path.rsplit("/", 1)[-1]
    request_shell = [
        [
            "X",
            "X",
            ["X", "X"],
            None,
            None,
            1,
            1,
            "US:en",
            None,
            1,
            None,
            None,
            None,
            None,
            None,
            0,
            1,
        ],
        "X",
        "X",
        1,
        [1, 1, 1],
        1,
        1,
        None,
        0,
        0,
        None,
        0,
    ]
    rpc_inner = json.dumps(
        ["garturlreq", request_shell, article_id, int(timestamp.group(1)), signature.group(1)],
        separators=(",", ":"),
    )
    request_body = json.dumps([[["Fbv4je", rpc_inner, None, "generic"]]], separators=(",", ":"))
    try:
        response = requests.post(
            GOOGLE_NEWS_BATCH_URL,
            headers={
                **DEFAULT_HEADERS,
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            },
            data={"f.req": request_body},
            timeout=timeout,
            impersonate="chrome120",
        )
        body = response.text.split("\n", 1)[1] if "\n" in response.text else response.text
        for envelope in json.loads(body):
            if not isinstance(envelope, list) or len(envelope) < 3:
                continue
            if envelope[0] != "wrb.fr" or envelope[1] != "Fbv4je":
                continue
            payload = json.loads(envelope[2])
            if isinstance(payload, list) and len(payload) >= 2 and payload[0] == "garturlres":
                target = payload[1]
                return target if isinstance(target, str) else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("解析 Google News 文章地址失败 [%s]: %s", url, exc)
    return None


def _is_candidate_item(item: dict[str, str]) -> bool:
    text = f"{item.get('title', '')} {item.get('description', '')}".lower()
    return ("susquehanna" in text or "semisignals" in text) and (
        "lead time" in text or "lead-time" in text or "wait time" in text
    )
