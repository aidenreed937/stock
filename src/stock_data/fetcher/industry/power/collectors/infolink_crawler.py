"""InfoLink 光伏现货价格在线爬虫。"""

import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from curl_cffi import requests

from stock_data.fetcher.industry.base_parser import HtmlParserProtocol
from stock_data.fetcher.industry.common import save_raw_snapshot
from stock_data.fetcher.industry.contracts import IndustryCollectionResult
from stock_data.fetcher.industry.power.lineage import (
    file_lineage,
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.power.parsers.infolink import (
    INFOLINK_SPOT_PRICE_URL,
    InfoLinkSpotPriceHtmlParser,
)
from stock_data.fetcher.industry.power.paths import PowerRawPaths

logger = logging.getLogger(__name__)

INFOLINK_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
INFOLINK_HISTORY_URL = "https://www.infolink-group.com/energy-article/cn/pv-spot-price-{date}"


class InfoLinkPvPriceCrawler:
    """InfoLink Consulting 官方光伏现货价格周度在线爬虫。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
        parser: HtmlParserProtocol[dict[str, Any]] | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.paths = PowerRawPaths(self.raw_dir)
        self.energy_dir = self.paths.infolink_dir
        self.parser = parser or InfoLinkSpotPriceHtmlParser()

    def _fetch_url(self, url: str) -> dict[str, Any] | None:
        """请求并解析单篇 InfoLink 文章，同时保存不可变 HTML 快照。"""
        try:
            logger.info("正在在线抓取 InfoLink 光伏价格文章: %s", url)
            resp = requests.get(
                url,
                headers=INFOLINK_HEADERS,
                impersonate="chrome120",
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning("访问 InfoLink 返回 HTTP %d: %s", resp.status_code, url)
                return None
            html_text = resp.text
            parsed = self.parser.parse(html_text, source_url=url)
            if not parsed:
                return None
            content_bytes = getattr(resp, "content", b"")
            if not isinstance(content_bytes, bytes) or not content_bytes:
                content_bytes = html_text.encode("utf-8")
            report_date = str(parsed.get("report_date") or "")
            snapshot_name = (
                f"pv_spot_price_{report_date.replace('-', '')}.html.gz"
                if report_date
                else "infolink_live_spot_price.html.gz"
            )
            snapshot_path = save_raw_snapshot(
                "power",
                f"infolink/{snapshot_name}",
                content_bytes,
                base_dir=self.raw_dir,
                compress=True,
            )
            parsed["raw_content_sha256"] = raw_content_sha256(content_bytes)
            parsed["raw_snapshot_path"] = raw_snapshot_path_value(snapshot_path, self.raw_dir)
            parsed["_html_text"] = html_text
            return parsed
        except Exception as exc:  # noqa: BLE001
            logger.warning("在线抓取 InfoLink 价格异常 [%s]: %s", url, exc)
            return None

    def _discover_history_urls(self) -> dict[str, str]:
        """从 InfoLink 最新文章页发现可用的历史周报链接。"""
        try:
            resp = requests.get(
                INFOLINK_SPOT_PRICE_URL,
                headers=INFOLINK_HEADERS,
                impersonate="chrome120",
                timeout=15,
            )
            if resp.status_code != 200:
                return {}
            text = resp.text
        except Exception as exc:  # noqa: BLE001
            logger.debug("InfoLink 历史文章发现失败: %s", exc)
            return {}

        return {
            match.group(1): match.group(0)
            for match in re.finditer(
                r"https://www\.infolink-group\.com/energy-article/cn/pv-spot-price-(20\d{6})",
                text,
            )
        }

    def fetch_live_spot_prices(self, force: bool = False) -> dict[str, Any] | None:
        """优先在线抓取最新报价，网络不可用时再回退本地快照。"""
        self.energy_dir.mkdir(parents=True, exist_ok=True)
        snapshot_file = self.paths.infolink_live_spot_price_html
        canonical_snapshot_file = self.paths.infolink_dir / "infolink_live_spot_price.html"

        parsed = self._fetch_url(INFOLINK_SPOT_PRICE_URL)
        if parsed:
            try:
                canonical_snapshot_file.parent.mkdir(parents=True, exist_ok=True)
                canonical_snapshot_file.write_text(
                    str(parsed.get("_html_text") or ""), encoding="utf-8"
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("保存 InfoLink 当前快照失败: %s", exc)
            parsed.pop("_html_text", None)
            return parsed

        if not force and snapshot_file.exists() and snapshot_file.stat().st_size > 0:
            try:
                html_text = snapshot_file.read_text(encoding="utf-8")
                parsed = self.parser.parse(html_text, source_url=INFOLINK_SPOT_PRICE_URL)
                if parsed:
                    content_hash, snapshot_ref = file_lineage(snapshot_file, self.raw_dir)
                    parsed.setdefault("raw_content_sha256", content_hash)
                    parsed.setdefault("raw_snapshot_path", snapshot_ref)
                    logger.debug(
                        "在线抓取失败，回退 InfoLink 本地 RAW 快照: %s", parsed.get("report_date")
                    )
                    return parsed
            except Exception as exc:  # noqa: BLE001
                logger.debug("读取 InfoLink 本地快照失败: %s", exc)
        return None

    def fetch_range(
        self,
        start_date: date,
        end_date: date,
        *,
        force: bool = False,
    ) -> IndustryCollectionResult:
        """按周发现/抓取 InfoLink 历史文章，支持范围内强制刷新。"""
        self.energy_dir.mkdir(parents=True, exist_ok=True)
        discovered = self._discover_history_urls()
        candidates: dict[str, str] = dict(discovered)
        cursor = start_date - timedelta(days=start_date.weekday())
        while cursor <= end_date:
            article_date = cursor + timedelta(days=2)
            if start_date <= article_date <= end_date:
                key = article_date.strftime("%Y%m%d")
                candidates.setdefault(key, INFOLINK_HISTORY_URL.format(date=key))
            cursor += timedelta(days=7)

        records: list[dict[str, Any]] = []
        errors: list[str] = []
        fetched: list[str] = []
        cached: list[str] = []
        for key, url in sorted(candidates.items()):
            try:
                article_date = date.fromisoformat(f"{key[:4]}-{key[4:6]}-{key[6:]}")
            except ValueError:
                continue
            if article_date < start_date or article_date > end_date:
                continue
            snapshot_file = self.energy_dir / f"pv_spot_price_{key}.html.gz"
            parsed: dict[str, Any] | None = None
            if not force and snapshot_file.exists():
                try:
                    import gzip

                    html_bytes = gzip.decompress(snapshot_file.read_bytes())
                    parsed = self.parser.parse(html_bytes.decode("utf-8"), source_url=url)
                    if parsed:
                        parsed["raw_content_sha256"] = raw_content_sha256(html_bytes)
                        parsed["raw_snapshot_path"] = raw_snapshot_path_value(
                            snapshot_file, self.raw_dir
                        )
                        cached.append(str(parsed.get("report_date") or article_date.isoformat()))
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{key}: 本地快照解析失败 ({exc})")
            if parsed is None:
                parsed = self._fetch_url(url)
            if parsed is None:
                errors.append(f"{key}: 文章不可用或解析失败")
                continue
            records.append(parsed)
            report_key = str(parsed.get("report_date") or article_date.isoformat())
            if report_key not in cached:
                fetched.append(report_key)
        expected = {
            key
            for key in candidates
            if start_date <= date.fromisoformat(f"{key[:4]}-{key[4:6]}-{key[6:]}") <= end_date
        }
        missing = sorted(
            expected
            - {item.replace("-", "") for item in fetched}
            - {item.replace("-", "") for item in cached}
        )
        status = "SUCCESS" if not errors and not missing else ("PARTIAL" if records else "FAILED")
        return IndustryCollectionResult(
            records,
            status=status,
            fetched_periods=fetched,
            cached_periods=cached,
            missing_periods=missing,
            errors=errors,
            updated=bool(records),
        )


__all__ = ["INFOLINK_HEADERS", "INFOLINK_HISTORY_URL", "InfoLinkPvPriceCrawler", "requests"]
