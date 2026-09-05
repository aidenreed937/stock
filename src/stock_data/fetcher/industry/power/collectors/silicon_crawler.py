"""硅业分会公开转载文章在线发现器。"""

import gzip
import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from curl_cffi import requests

from stock_data.fetcher.industry.common import save_raw_snapshot
from stock_data.fetcher.industry.contracts import IndustryCollectionResult
from stock_data.fetcher.industry.power.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.power.parsers.silicon import parse_silicon_branch_bulletin_text
from stock_data.fetcher.industry.power.paths import PowerRawPaths

logger = logging.getLogger(__name__)

SOLARBE_SILICON_SEARCH_URL = "https://news.solarbe.com/search/"
SOLARBE_SILICON_SOURCE = "Silicon_Branch_Relayed_Solarbe"
SOLARBE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def month_keys(start_date: date, end_date: date) -> list[str]:
    """生成包含边界月份的 YYYY-MM 列表。"""
    cursor = start_date.replace(day=1)
    end = end_date.replace(day=1)
    result: list[str] = []
    while cursor <= end:
        result.append(cursor.strftime("%Y-%m"))
        cursor = date(
            cursor.year + (cursor.month == 12),
            1 if cursor.month == 12 else cursor.month + 1,
            1,
        )
    return result


class SiliconBranchCrawler:
    """硅业分会公开转载文章在线发现器。"""

    def __init__(self, raw_dir: Path | str, timeout: int = 20) -> None:
        self.raw_root = Path(raw_dir)
        self.snapshot_dir = PowerRawPaths(self.raw_root).silicon_branch_dir
        self.timeout = timeout

    def fetch_latest(self, *, force: bool = False) -> IndustryCollectionResult:
        """在线发现最近几个月的转载文章，供无范围端点调用。"""
        end_date = date.today()
        start_date = (end_date - timedelta(days=120)).replace(day=1)
        periods = month_keys(start_date, end_date)
        result = self.fetch_range(
            start_date=start_date,
            end_date=end_date,
            periods=periods,
            force=force,
        )
        if result.records:
            return IndustryCollectionResult(
                result.records,
                status="PARTIAL" if result.errors else "SUCCESS",
                fetched_periods=result.fetched_periods,
                cached_periods=result.cached_periods,
                errors=result.errors,
                updated=result.updated,
            )
        return result

    def fetch_range(
        self,
        *,
        start_date: date,
        end_date: date,
        periods: list[str],
        force: bool = False,
    ) -> IndustryCollectionResult:
        if not periods:
            return IndustryCollectionResult([], status="SUCCESS")
        urls = self._discover_urls(start_date - timedelta(days=45), end_date + timedelta(days=45))
        records: list[dict[str, Any]] = []
        errors: list[str] = []
        cached_periods: list[str] = []
        expected = set(periods)
        for url, publication_date in urls:
            try:
                snapshot_path = (
                    self.snapshot_dir / f"solarbe_{publication_date.strftime('%Y%m%d')}.html.gz"
                )
                if not force and snapshot_path.exists():
                    content = gzip.decompress(snapshot_path.read_bytes())
                    html_text = content.decode("utf-8", errors="ignore")
                    cached_article = True
                else:
                    response = requests.get(
                        url,
                        headers=SOLARBE_HEADERS,
                        timeout=self.timeout,
                    )
                    if response.status_code != 200:
                        errors.append(f"{url}: HTTP {response.status_code}")
                        continue
                    content = getattr(response, "content", b"") or response.text.encode("utf-8")
                    html_text = response.text
                    cached_article = False
                soup = BeautifulSoup(html_text, "html.parser")
                article_text = soup.get_text(" ", strip=True)
                if re.search(r"来源[：:]\s*硅业分会", article_text) is None:
                    continue
                parsed = parse_silicon_branch_bulletin_text(article_text)
                month_number = parsed.pop("report_month_number", None)
                if not isinstance(month_number, int) or not 1 <= month_number <= 12:
                    continue
                report_year = publication_date.year
                if month_number > publication_date.month:
                    report_year -= 1
                report_month = f"{report_year:04d}-{month_number:02d}"
                if report_month not in expected:
                    continue
                if not cached_article:
                    snapshot_path = save_raw_snapshot(
                        "power",
                        f"silicon_branch/solarbe_{publication_date.strftime('%Y%m%d')}.html.gz",
                        content,
                        base_dir=self.raw_root,
                        compress=True,
                    )
                else:
                    cached_periods.append(report_month)
                release_match = re.search(
                    r"发布时间[：:]\s*(20\d{2})[-年](\d{1,2})[-月](\d{1,2})",
                    article_text,
                )
                release_date = None
                if release_match:
                    year, month, day = (int(value) for value in release_match.groups())
                    release_date = date(year, month, day).isoformat()
                records.append(
                    {
                        "report_month": report_month,
                        **parsed,
                        "source": SOLARBE_SILICON_SOURCE,
                        "source_url": url,
                        "release_date": release_date,
                        "raw_content_sha256": raw_content_sha256(content),
                        "raw_snapshot_path": raw_snapshot_path_value(snapshot_path, self.raw_root),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url}: {exc}")

        by_period: dict[str, dict[str, Any]] = {}
        for record in records:
            by_period.setdefault(str(record["report_month"]), record)
        missing = sorted(expected - set(by_period))
        if missing and not errors:
            status = "UNSUPPORTED_RANGE"
        else:
            status = (
                "SUCCESS" if not missing and not errors else ("PARTIAL" if records else "FAILED")
            )
        return IndustryCollectionResult(
            list(by_period.values()),
            status=status,
            fetched_periods=sorted(set(by_period) - set(cached_periods)),
            cached_periods=sorted(set(cached_periods)),
            missing_periods=missing,
            errors=errors,
            updated=bool(by_period),
        )

    def _discover_urls(self, start_date: date, end_date: date) -> list[tuple[str, date]]:
        urls: dict[str, date] = {}
        last_page = min(20, max(1, ((end_date - start_date).days // 7) + 5))
        for page in range(1, last_page + 1):
            try:
                response = requests.get(
                    SOLARBE_SILICON_SEARCH_URL,
                    params={"q": "硅业分会", "page": page},
                    headers=SOLARBE_HEADERS,
                    timeout=self.timeout,
                )
                if response.status_code != 200:
                    continue
                for match in re.finditer(
                    r"https://news\.solarbe\.com/(20\d{2})(\d{2})/(\d{2})/(\d+)\.html",
                    response.text,
                ):
                    year, month, day = (int(value) for value in match.groups()[:3])
                    publication_date = date(year, month, day)
                    if start_date - timedelta(days=370) <= publication_date <= end_date:
                        urls.setdefault(match.group(0), publication_date)
            except Exception as exc:  # noqa: BLE001
                logger.debug("发现硅业分会转载文章失败 (page=%d): %s", page, exc)
        return sorted(urls.items(), key=lambda item: item[1])


__all__ = [
    "SOLARBE_HEADERS",
    "SOLARBE_SILICON_SEARCH_URL",
    "SOLARBE_SILICON_SOURCE",
    "SiliconBranchCrawler",
    "month_keys",
    "requests",
]
