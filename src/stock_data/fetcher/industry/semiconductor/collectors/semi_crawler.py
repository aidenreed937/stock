"""SEMI 全球半导体设备市场统计 (WWSEMS) 季度公报在线爬虫。

数据源: SEMI (https://www.semi.org/en/news-media/press-releases) 与 PR Newswire
季度初 (3月、6月、9月、12月) 官方发布上季度全球及中国大陆半导体设备出货公报。
"""

from __future__ import annotations

import logging
import re
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from curl_cffi import requests

from stock_data.fetcher.industry.common import save_raw_snapshot
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_content_bytes,
    raw_snapshot_path_value,
    response_content_bytes,
)
from stock_data.fetcher.industry.semiconductor.parsers.semi import (
    extract_semi_press_release_links,
    parse_semi_article_text,
)
from stock_data.fetcher.industry.semiconductor.paths import SemiconductorRawPaths

logger = logging.getLogger(__name__)

SEMI_PR_URL = "https://www.semi.org/en/news-media/press-releases"
SEMI_EQUIPMENT_MARKET_URL = "https://www.semi.org/en/products-services/market-data/equipment"
SEMI_EQUIPMENT_ARTICLE_ARCHIVE_URL = (
    "https://www.semi.org/en/products-services/market-data/equipment-article-archive"
)
PRNEWSWIRE_SEMI_URL = "https://www.prnewswire.com/news-releases/semi-reports-news-list/"
DEFAULT_HISTORY_MAX_PAGES = 12
SEMI_SOURCES = (
    (SEMI_EQUIPMENT_MARKET_URL, "https://www.semi.org"),
    (SEMI_EQUIPMENT_ARTICLE_ARCHIVE_URL, "https://www.semi.org"),
    (SEMI_PR_URL, "https://www.semi.org"),
    (PRNEWSWIRE_SEMI_URL, "https://www.prnewswire.com"),
)
SEMI_LEGACY_ARTICLE_URLS = (
    "https://www.semi.org/en/news-resources/press/Q2-2019-wwsems",
    "https://www.semi.org/en/news-resources/press/Q1-2020-wwsems",
    "https://www.semi.org/en/news-resources/press/Q2-2020-wwsems",
    "https://www.semi.org/en/2018-global-semiconductor-equipment-sales-jump-record-645-billion",
    "https://www.semi.org/en/news-resources/press/2019-global-semiconductor-equipment",
    "https://www.semi.org/en/news-media-press/semi-press-releases/annual-global-semiconductor-equipment-sales",
    "https://www.semi.org/en/news-media-press-releases/semi-press-releases/2021-global-semiconductor-equipment-sales-surge-44%25-to-industry-record-%24102.6-billion-semi-reports",
    "https://www.semi.org/en/news-media-press-releases/semi-press-releases/global-semiconductor-equipment-billings-reach-industry-record-%24107.6-billion-in-2022-semi-reports",
    "https://www.semi.org/en/news-media-press-releases/semi-press-releases/global-semiconductor-equipment-billings-slip-to-%24106.3-billion-in-2023-semi-reports",
    "https://www.semi.org/en/semi-press-release/global-semiconductor-equipment-billings-surged-to-117-billion-dollars-in-2024-semi-reports",
    "https://www.semi.org/en/SEMI-Reports-Global-Semiconductor-Equipment-Billings-Reached-135-Billion-in-2025",
)
SEMI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class SemiEquipmentCrawler:
    """SEMI 官方 WWSEMS 季度设备出货公报在线采集爬虫。"""

    def __init__(
        self,
        raw_dir: Path | str,
        timeout: int = 15,
        impersonate: str = "chrome120",
    ) -> None:
        self.paths = SemiconductorRawPaths(raw_dir)
        self.snapshot_dir = self.paths.semi_dir
        self.timeout = timeout
        self.impersonate = impersonate

    def fetch_latest(self, force: bool = False) -> list[dict[str, Any]]:
        """在线抓取 SEMI 官方新闻主页或 PR Newswire 镜像并解析最新 WWSEMS 公报。

        `force` 保持统一采集入口签名；默认路径始终解析本次线上响应，本地 HTML
        快照仅通过 `replay_cached_snapshots()` 显式用于离线对账重放。
        """
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        if force:
            logger.debug("SEMI WWSEMS 强制刷新: 跳过调度层缓存并重新访问线上源")

        return self._fetch_online_range(
            start_date=None,
            end_date=None,
            max_pages=1,
            stop_after_first_source=True,
        )

    def fetch_range(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        force: bool = False,
        max_pages: int = DEFAULT_HISTORY_MAX_PAGES,
    ) -> list[dict[str, Any]]:
        """在线翻页采集指定报告期范围内的 SEMI WWSEMS 公报。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        if force:
            logger.debug("SEMI WWSEMS 范围刷新: 跳过调度层缓存并重新访问线上源")
        return self._fetch_online_range(
            start_date=start_date,
            end_date=end_date,
            max_pages=max_pages,
            stop_after_first_source=False,
        )

    def _fetch_online_range(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        max_pages: int,
        stop_after_first_source: bool,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        for url, base_url in SEMI_SOURCES:
            source_results: list[dict[str, Any]] = []
            seen_list_hashes: set[str] = set()
            try:
                for page_url in _paged_urls(url, max_pages=max_pages):
                    page_results, page_dates = self._fetch_list_page(
                        page_url,
                        base_url=base_url,
                        seen_list_hashes=seen_list_hashes,
                        start_date=start_date,
                        end_date=end_date,
                    )
                    if not page_results and not page_dates:
                        break
                    source_results.extend(page_results)
                    if _can_stop_history_scan(page_dates, start_date):
                        break
            except Exception as exc:
                logger.warning("抓取源异常 [%s]: %s", url, exc)
            if source_results:
                results.extend(source_results)
                if stop_after_first_source:
                    break

        if not stop_after_first_source:
            for article_url in SEMI_LEGACY_ARTICLE_URLS:
                if any(item.get("source_url") == article_url for item in results):
                    continue
                try:
                    parsed = self._fetch_article(article_url)
                    if parsed and _in_date_range(
                        parsed,
                        start_date=start_date,
                        end_date=end_date,
                    ):
                        results.append(parsed)
                except Exception as exc:
                    logger.warning("抓取历史公报详情失败 [%s]: %s", article_url, exc)

        return _dedupe_and_sort_results(results)

    def _fetch_list_page(
        self,
        page_url: str,
        *,
        base_url: str,
        seen_list_hashes: set[str],
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[list[dict[str, Any]], list[date]]:
        resp = requests.get(
            page_url,
            headers=SEMI_HEADERS,
            timeout=self.timeout,
            impersonate=self.impersonate,
        )
        list_bytes = response_content_bytes(resp)
        if resp.status_code != 200 or not list_bytes:
            return [], []

        list_hash = raw_content_sha256(list_bytes)
        if list_hash in seen_list_hashes:
            return [], []
        seen_list_hashes.add(list_hash)
        _write_snapshot(self.paths, f"{_snapshot_stem(page_url)}_list.html", list_bytes)

        results: list[dict[str, Any]] = []
        parsed_dates: list[date] = []
        seen_urls: set[str] = set()
        for full_url in extract_semi_press_release_links(list_bytes, base_url):
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            try:
                parsed = self._fetch_article(full_url)
                if not parsed:
                    continue
                trade_date = parsed.get("trade_date")
                if isinstance(trade_date, date):
                    parsed_dates.append(trade_date)
                if _in_date_range(parsed, start_date=start_date, end_date=end_date):
                    results.append(parsed)
            except Exception as e:
                logger.warning("抓取公报详情失败 [%s]: %s", full_url, e)
        return results, parsed_dates

    def _fetch_article(self, full_url: str) -> dict[str, Any] | None:
        art_resp = requests.get(
            full_url,
            headers=SEMI_HEADERS,
            timeout=self.timeout,
            impersonate=self.impersonate,
        )
        if art_resp.status_code != 200:
            return None
        article_bytes = response_content_bytes(art_resp)
        if not article_bytes:
            return None
        article_text = getattr(art_resp, "text", "") or article_bytes.decode(
            "utf-8", errors="ignore"
        )
        content_hash, snapshot_ref = _write_snapshot(
            self.paths, f"{_snapshot_stem(full_url)}.html", article_bytes
        )
        parsed = parse_semi_article_text(
            article_text,
            source_url=full_url,
            default_date=_response_last_modified_date(art_resp),
        )
        if parsed:
            parsed["raw_content_sha256"] = content_hash
            parsed["raw_snapshot_path"] = snapshot_ref
        return parsed

    def replay_cached_snapshots(self) -> list[dict[str, Any]]:
        """从本地 SEMI HTML 快照离线重放 RAW 字段，仅用于手工对账或 replay 脚本。"""
        results: list[dict[str, Any]] = []
        html_files = sorted(self.snapshot_dir.glob("*.html")) + sorted(
            self.snapshot_dir.glob("*.html.gz")
        )
        for html_file in html_files:
            if html_file.name.endswith("_list.html") or html_file.name.endswith("_list.html.gz"):
                continue
            try:
                content_bytes = raw_snapshot_content_bytes(html_file)
                html_text = content_bytes.decode("utf-8", errors="ignore")
                parsed = parse_semi_article_text(html_text)
                if parsed:
                    parsed["raw_content_sha256"] = raw_content_sha256(content_bytes)
                    parsed["raw_snapshot_path"] = raw_snapshot_path_value(
                        html_file, self.paths.raw_root
                    )
                    results.append(parsed)
            except Exception as exc:
                logger.debug("解析 SEMI 本地 HTML 快照失败 [%s]: %s", html_file.name, exc)
        return results


def _snapshot_stem(url: str) -> str:
    parsed = urlparse(url)
    raw_stem = f"{parsed.netloc}{parsed.path}" or "semi_snapshot"
    if parsed.query:
        raw_stem = f"{raw_stem}-{parsed.query}"
    stem = re.sub(r"[^0-9A-Za-z]+", "-", raw_stem).strip("-").lower()
    return stem[:120] or "semi_snapshot"


def _write_snapshot(
    paths: SemiconductorRawPaths,
    filename: str,
    content: str | bytes,
) -> tuple[str, str]:
    content_bytes = content if isinstance(content, bytes) else content.encode("utf-8")
    try:
        snapshot_path = save_raw_snapshot(
            "semi",
            filename,
            content_bytes,
            base_dir=paths.semiconductor_dir,
            compress=True,
        )
        return (
            raw_content_sha256(content_bytes),
            raw_snapshot_path_value(snapshot_path, paths.raw_root),
        )
    except Exception as exc:
        logger.debug("保存 SEMI HTML 快照失败 [%s]: %s", filename, exc)
        return raw_content_sha256(content_bytes), ""


def _paged_urls(url: str, *, max_pages: int) -> list[str]:
    if url == SEMI_EQUIPMENT_ARTICLE_ARCHIVE_URL:
        return [url]
    if max_pages <= 1:
        return [url]
    urls = [url]
    parsed = urlparse(url)
    query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for page in range(1, max_pages):
        page_query = {**query_items, "page": str(page)}
        urls.append(urlunparse(parsed._replace(query=urlencode(page_query))))
    return urls


def _in_date_range(
    item: dict[str, Any],
    *,
    start_date: date | None,
    end_date: date | None,
) -> bool:
    trade_date = item.get("trade_date")
    if not isinstance(trade_date, date):
        return False
    if start_date is not None and trade_date < start_date:
        return False
    return not (end_date is not None and trade_date > end_date)


def _can_stop_history_scan(page_dates: list[date], start_date: date | None) -> bool:
    return bool(start_date is not None and page_dates and max(page_dates) < start_date)


def _dedupe_and_sort_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique_items: dict[str, dict[str, Any]] = {}
    for item in items:
        key = str(item.get("report_quarter") or item.get("source_url") or len(unique_items))
        if key not in unique_items:
            unique_items[key] = item
    return sorted(
        unique_items.values(),
        key=lambda item: (
            item["trade_date"] if isinstance(item.get("trade_date"), date) else date.min
        ),
    )


def _response_last_modified_date(response: Any) -> date | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw_value = headers.get("Last-Modified") or headers.get("last-modified")
    if not raw_value:
        return None
    try:
        return parsedate_to_datetime(str(raw_value)).date()
    except (TypeError, ValueError, IndexError):
        return None
