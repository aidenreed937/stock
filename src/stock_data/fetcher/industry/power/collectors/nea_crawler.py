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

        if start_date is not None or end_date is not None:
            news_candidates.extend(self._search_bulletins(start_date=start_date, end_date=end_date))

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
    ) -> list[tuple[str, str]]:
        """通过 NEA 官方站内搜索补充首页未展示的历史统计通报。"""
        return _search_bulletins(start_date=start_date, end_date=end_date)


def _search_bulletins(
    *,
    start_date: date | None,
    end_date: date | None,
) -> list[tuple[str, str]]:
    """通过 NEA 官方站内搜索补充首页未展示的历史统计通报。"""
    del start_date, end_date
    candidates: list[tuple[str, str]] = []
    for page in range(1, 21):
        try:
            response = requests.get(
                NEA_SEARCH_URL,
                params={
                    "pageNo": str(page),
                    "pageSize": "50",
                    "siteId": "11200",
                    "keyword": "全国电力工业统计数据",
                    "sort": "1",
                    "isInclude": "1",
                    "neac": "",
                },
                headers=NEA_HEADERS,
                timeout=10,
            )
            if response.status_code != 200:
                continue
            payload = response.json()
            rows = payload.get("content", {}).get("result", [])
            if not rows:
                break
            for row in rows:
                title = BeautifulSoup(str(row.get("title") or ""), "html.parser").get_text(
                    strip=True
                )
                url_values = row.get("originUrl") or []
                url = str(url_values[0]) if url_values else ""
                if not url or _extract_month_key(title) is None:
                    continue
                candidates.append((title, url))
        except Exception as exc:  # noqa: BLE001
            logger.debug("NEA 站内历史搜索失败 (page=%d): %s", page, exc)
            break
    return candidates


def _extract_release_date(text: str) -> str | None:
    match = re.search(r"(20\d{2})[年\-/](\d{1,2})[月\-/](\d{1,2})日?", text)
    if match is None:
        return None
    year, month, day = (int(value) for value in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _extract_month_key(title: str) -> str | None:
    match = re.search(r"(20\d{2})年(?:1-)?(\d{1,2})月份", title)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
    year_match = re.search(r"(20\d{2})年全国电力工业统计数据", title)
    return f"{int(year_match.group(1)):04d}-12" if year_match else None


__all__ = ["NEA_BASE_URL", "NEA_HEADERS", "NEA_SEARCH_URL", "NeaBulletinCrawler"]
