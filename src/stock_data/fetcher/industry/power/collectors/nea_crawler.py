"""国家能源局 (NEA) 官方政务通报轻量与克制爬虫 (NeaBulletinCrawler)。"""

from __future__ import annotations

import gzip
import json
import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from stock_data.fetcher.industry.common import now_utc_iso, save_raw_snapshot
from stock_data.fetcher.industry.power.lineage import raw_content_sha256, raw_snapshot_path_value
from stock_data.fetcher.industry.power.parsers.nea import parse_solar_capacity_from_text
from stock_data.fetcher.industry.power.paths import PowerRawPaths

logger = logging.getLogger(__name__)

NEA_BASE_URL = "http://www.nea.gov.cn"
NEA_SEARCH_URL = "http://www.nea.gov.cn/was5/web/conwebsite/getNewsFromAllData"
NEA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
# 站内搜索接口缺少同源浏览器请求头时返回 403，必须补齐 Referer/Origin/X-Requested-With。
NEA_SEARCH_HEADERS = {
    **NEA_HEADERS,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{NEA_BASE_URL}/",
    "Origin": NEA_BASE_URL,
}
# 通报标题命名自 2026 年起由「全国电力工业统计数据」改为「全国电力统计数据」，
# 两套关键字的结果集互不覆盖（前者最新到 2025-11，后者才含 2026 年各月），必须同时检索。
NEA_SEARCH_KEYWORDS = ("全国电力统计数据", "全国电力工业统计数据")
# 未显式指定日期范围时只扫站内搜索第 1 页，既覆盖近月通报又避免每次同步都翻页。
NEA_SEARCH_DEFAULT_PAGES = 1
NEA_SEARCH_MAX_PAGES = 20


class NeaBulletinCrawler:
    """国家能源局《全国电力工业统计数据》克制爬虫。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.paths = PowerRawPaths(self.raw_dir)
        self.nea_dir = self.paths.nea_dir
        self.cache_file = self.paths.nea_dir / "bulletins_manifest.json.gz"
        self.legacy_cache_files = tuple(
            directory / "bulletins_manifest.json.gz" for directory in self.paths.legacy_nea_dirs
        )
        self.last_fetched_periods: tuple[str, ...] = ()
        self.last_errors: tuple[str, ...] = ()

    def fetch_latest_bulletins(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        force: bool = False,
    ) -> dict[str, dict[str, Any]]:
        """从国家能源局官网克制抓取最新电力统计通报并合并本地缓存。"""
        self.nea_dir.mkdir(parents=True, exist_ok=True)
        cached_data: dict[str, dict[str, Any]] = self._load_cache()
        fetched_periods: list[str] = []
        errors: list[str] = []

        def in_range(month_key: str) -> bool:
            year, month = (int(part) for part in month_key.split("-", 1))
            month_start = date(year, month, 1)
            month_end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
            if start_date is not None and month_end <= start_date:
                return False
            if end_date is not None and month_start > end_date:
                return False
            return True

        def fetch_detail(month_key: str, title: str, url: str) -> None:
            if not in_range(month_key):
                return
            if month_key in fetched_periods:
                return
            if (
                not force
                and month_key in cached_data
                and cached_data[month_key].get("cumulative_gw") is not None
            ):
                return
            logger.info("发现国家能源局新统计通报: [%s] -> %s", title, url)
            time.sleep(1.0)  # 克制爬取间隔
            try:
                doc_r = requests.get(url, headers=NEA_HEADERS, timeout=10)
                if doc_r.status_code != 200:
                    errors.append(f"{month_key}: HTTP {doc_r.status_code}")
                    return
                doc_r.encoding = "utf-8"
                html_bytes = getattr(doc_r, "content", b"") or doc_r.text.encode("utf-8")
                doc_soup = BeautifulSoup(doc_r.text, "html.parser")
                body_text = doc_soup.get_text()
                cap_gw, yoy = parse_solar_capacity_from_text(body_text)
                if cap_gw is None:
                    errors.append(f"{month_key}: 未解析到太阳能累计装机")
                    return
                snapshot_dir = self.nea_dir / "bulletins"
                snapshot_dir.mkdir(parents=True, exist_ok=True)
                snapshot_path = save_raw_snapshot(
                    "power",
                    f"nea/bulletins/{month_key}.html.gz",
                    html_bytes,
                    base_dir=self.raw_dir,
                    compress=True,
                )
                fetched_periods.append(month_key)
                cached_data[month_key] = {
                    "report_month": month_key,
                    "title": title,
                    "url": url,
                    "cumulative_gw": cap_gw,
                    "yoy_growth": yoy,
                    "release_date": _extract_release_date(body_text),
                    "collected_at": now_utc_iso(),
                    "raw_content_sha256": raw_content_sha256(html_bytes),
                    "raw_snapshot_path": raw_snapshot_path_value(snapshot_path, self.raw_dir),
                }
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{month_key}: {exc}")

        # 扫描官网首页获取通报链接 (仅发单次轻量 GET 请求)
        news_candidates: list[tuple[str, str]] = []
        try:
            logger.info("正在克制扫描国家能源局官网首页发布列表: %s", NEA_BASE_URL)
            r = requests.get(NEA_BASE_URL, headers=NEA_HEADERS, timeout=10)
            if r.status_code != 200:
                logger.warning("访问国家能源局官网首页返回 HTTP %d", r.status_code)
                errors.append(f"首页 HTTP {r.status_code}")
            else:
                r.encoding = "utf-8"
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    title = a.get_text(strip=True)
                    href_str = str(a["href"])
                    if "全国电力统计数据" in title or "全国电力工业统计数据" in title:
                        full_url = (
                            href_str
                            if href_str.startswith("http")
                            else f"{NEA_BASE_URL}/{href_str.lstrip('/')}"
                        )
                        news_candidates.append((title, full_url))
        except Exception as e:
            logger.warning("访问国家能源局首页异常: %s", e)
            errors.append(str(e))

        # 首页列表滚动很快：通报离开首页后就再也发现不了，因此站内搜索始终启用，
        # 兜底补齐「同步跑晚了」漏掉的月份；显式传日期范围时加深翻页。
        news_candidates.extend(
            self._search_bulletins(
                start_date=start_date,
                end_date=end_date,
                max_pages=(
                    NEA_SEARCH_MAX_PAGES
                    if start_date is not None or end_date is not None
                    else NEA_SEARCH_DEFAULT_PAGES
                ),
            )
        )

        # 合并首页发现的链接与历史 manifest 中已有的 URL，支持指定范围强刷。
        known_candidates = {
            (month, info.get("title", ""), info.get("url", ""))
            for month, info in cached_data.items()
            if info.get("url")
        }
        for title, url in news_candidates:
            m_match = _extract_month_key(title)
            if m_match:
                known_candidates.add((m_match, title, url))

        # 过滤未抓取的新通报
        for title, url in news_candidates:
            # 正则解析通报对应月份 (如 2026年1-7月份 -> 2026-07)
            month_key = _extract_month_key(title)
            if not month_key:
                continue
            fetch_detail(month_key, title, url)

        if force and (start_date is not None or end_date is not None):
            for month_key, title, url in sorted(known_candidates):
                fetch_detail(month_key, title, url)

        self._save_cache(cached_data)
        self.last_fetched_periods = tuple(sorted(set(fetched_periods)))
        self.last_errors = tuple(errors)
        return cached_data

    def fetch_range(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        *,
        force: bool = False,
    ) -> dict[str, dict[str, Any]]:
        """按指定月份范围发现并抓取 NEA 通报，保留旧接口返回形态。"""
        return self.fetch_latest_bulletins(
            start_date=start_date,
            end_date=end_date,
            force=force,
        )

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        """读取本地已压缩归档的官方通报缓存。"""
        for cache_file in (self.cache_file, *self.legacy_cache_files):
            if not cache_file.exists():
                continue
            try:
                from typing import cast

                with gzip.open(cache_file, "rt", encoding="utf-8") as f:
                    return cast("dict[str, dict[str, Any]]", json.load(f))
            except Exception as e:
                logger.warning("读取 NEA 通报缓存失败: %s", e)
        return {}

    def _save_cache(self, data: dict[str, dict[str, Any]]) -> None:
        """持久化官方通报缓存。"""
        try:
            with gzip.open(self.cache_file, "wt", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("保存 NEA 通报缓存失败: %s", e)

    def _search_bulletins(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        max_pages: int = NEA_SEARCH_DEFAULT_PAGES,
    ) -> list[tuple[str, str]]:
        """通过 NEA 官方站内搜索补充首页未展示的历史统计通报。"""
        return _search_bulletins(start_date=start_date, end_date=end_date, max_pages=max_pages)


def _search_bulletins(
    *,
    start_date: date | None,
    end_date: date | None,
    max_pages: int = NEA_SEARCH_DEFAULT_PAGES,
) -> list[tuple[str, str]]:
    """通过 NEA 官方站内搜索补充首页未展示的统计通报。

    站内搜索覆盖面远大于首页（可回溯多年），是「同步跑晚、通报已滚出首页」场景下
    唯一可用的兜底发现路径。
    """
    del start_date, end_date
    candidates: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for keyword in NEA_SEARCH_KEYWORDS:
        for page in range(1, max(max_pages, 1) + 1):
            rows = _search_page(keyword=keyword, page=page)
            if not rows:
                break
            for row in rows:
                title = BeautifulSoup(str(row.get("title") or ""), "html.parser").get_text(
                    strip=True
                )
                url_values = row.get("originUrl") or []
                url = str(url_values[0]) if url_values else ""
                if not url or url in seen_urls or _extract_month_key(title) is None:
                    continue
                seen_urls.add(url)
                candidates.append((title, url))
    return candidates


def _search_page(*, keyword: str, page: int) -> list[dict[str, Any]]:
    """请求站内搜索单页结果；异常或非 200 返回空列表（缺口如实留给上层）。"""
    try:
        response = requests.get(
            NEA_SEARCH_URL,
            params={
                "pageNo": str(page),
                "pageSize": "50",
                "siteId": "11200",
                "keyword": keyword,
                "sort": "1",
                "isInclude": "1",
                "neac": "",
            },
            headers=NEA_SEARCH_HEADERS,
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("NEA 站内搜索异常 (keyword=%s page=%d): %s", keyword, page, exc)
        return []
    if response.status_code != 200:
        logger.debug(
            "NEA 站内搜索 HTTP %s (keyword=%s page=%d)", response.status_code, keyword, page
        )
        return []
    try:
        content = response.json().get("content")
    except Exception as exc:  # noqa: BLE001
        logger.debug("NEA 站内搜索响应解析失败 (keyword=%s page=%d): %s", keyword, page, exc)
        return []
    if not isinstance(content, dict):
        return []
    rows = content.get("result")
    return rows if isinstance(rows, list) else []


def _extract_release_date(text: str) -> str | None:
    """从通报页面提取发布日期 (ISO)。

    必须优先锚定「发布时间：」标注：正文标题里的报告期区间（如「2026年1-6月份」）会被
    通用日期正则误读成 2026-01-06，污染下游的 release_date 生效时点。
    """
    patterns = (
        r"发布时间[：:\s]*(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})",
        r"(20\d{2})年(\d{1,2})月(\d{1,2})日",
        r"(20\d{2})-(\d{1,2})-(\d{1,2})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match is None:
            continue
        year, month, day = (int(value) for value in match.groups())
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            continue
    return None


def _extract_month_key(title: str) -> str | None:
    """从通报标题解析报告月份 (YYYY-MM)。

    区间分隔符可能是半角连字符（1-7月份）或全角破折号（1—8月份）等，需一并识别；
    年份通报（「2025年全国电力统计数据」）回退为 12 月。
    """
    match = re.search(r"(20\d{2})年(?:1\s*[-—–－~～至/]\s*)?(\d{1,2})月份", title)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
    year_match = re.search(r"(20\d{2})年(?:全国电力(?:工业)?统计数据)", title)
    return f"{int(year_match.group(1)):04d}-12" if year_match else None


__all__ = [
    "NEA_BASE_URL",
    "NEA_HEADERS",
    "NEA_SEARCH_DEFAULT_PAGES",
    "NEA_SEARCH_HEADERS",
    "NEA_SEARCH_KEYWORDS",
    "NEA_SEARCH_MAX_PAGES",
    "NEA_SEARCH_URL",
    "NeaBulletinCrawler",
]
