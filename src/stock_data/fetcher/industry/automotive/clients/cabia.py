"""CABIA 资源列表、详情页和 RAW 快照在线客户端。"""

from __future__ import annotations

import io
import json
import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import pypdf
from curl_cffi import requests

from stock_data.fetcher.industry.automotive.clients.cls import ClsBatteryClient
from stock_data.fetcher.industry.automotive.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.automotive.parsers.cabia import parse_cabia_battery_article
from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
    save_raw_snapshot,
)

logger = logging.getLogger(__name__)

CABIA_ONLINE_BASE_URL = "https://batteryalliancechina.org"
CABIA_RESOURCE_API_URL = f"{CABIA_ONLINE_BASE_URL}/api/resources"
CABIA_HEADERS = {
    "Accept": "application/json,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


class CabiaOnlineClient:
    """调用 CABIA 公开资源 API 并保存原始响应。"""

    def __init__(
        self,
        raw_dir: Path,
        *,
        timeout: int = 15,
        impersonate: str = "chrome120",
        resource_api_url: str | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.timeout = timeout
        self.impersonate = impersonate
        self.resource_api_url: str = (
            resource_api_url or os.getenv("STOCK_CABIA_RESOURCE_API_URL") or CABIA_RESOURCE_API_URL
        )
        self.cls_client = ClsBatteryClient(
            self.raw_dir,
            timeout=timeout,
            impersonate=impersonate,
        )
        self.last_errors: tuple[str, ...] = ()
        self.last_fetched_periods: tuple[str, ...] = ()

    def fetch(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        max_pages: int,
    ) -> dict[str, dict[str, Any]]:
        self.last_errors = ()
        self.last_fetched_periods = ()
        results: dict[str, dict[str, Any]] = {}
        total_pages = 1
        for page in range(1, max_pages + 1):
            page_url = _page_url(self.resource_api_url, page)
            try:
                response = requests.get(
                    page_url,
                    headers=CABIA_HEADERS,
                    timeout=self.timeout,
                    impersonate=self.impersonate,
                )
            except Exception as exc:  # noqa: BLE001
                self._add_error(f"CABIA 资源列表请求失败: {exc}")
                break

            content = _response_bytes(response)
            if getattr(response, "status_code", 0) != 200 or not content:
                self._add_error(
                    f"CABIA 资源列表 HTTP {getattr(response, 'status_code', 'unknown')}"
                )
                break

            list_hash, list_ref = self._save_snapshot(
                f"resource_list_{_timestamp_slug()}_{page}.json", content, compress=True
            )
            payload = _json_payload(response, content)
            items = _resource_items(payload)
            for item in items:
                if not isinstance(item, dict):
                    continue
                parsed = self._fetch_resource_item(
                    item,
                    start_date=start_date,
                    end_date=end_date,
                    list_hash=list_hash,
                    list_ref=list_ref,
                )
                if parsed is not None:
                    results[parsed["report_month"]] = parsed

            pagination = (
                payload.get("data", {}).get("pagination", {}) if isinstance(payload, dict) else {}
            )
            if isinstance(pagination, dict):
                try:
                    total_pages = max(1, int(pagination.get("totalPages", 1)))
                except (TypeError, ValueError):
                    total_pages = page
            if page >= min(total_pages, max_pages) or not items:
                break

        # 若 CABIA 官网未获取到结果或未覆盖请求窗口，尝试通过财联社电报流增量发现
        if not results:
            logger.info("CABIA 官网未解析出目标月报，尝试通过财联社电报流增量发现...")
            cls_results = self.cls_client.fetch(
                start_date=start_date,
                end_date=end_date,
            )
            for m, record in cls_results.items():
                if m not in results:
                    results[m] = record

        if not results and not self.last_errors:
            self._add_error("CABIA 官网及财联社电报流均未解析到可验证的动力电池月报")
        self.last_fetched_periods = tuple(sorted(results))
        return results

    def _fetch_resource_item(
        self,
        item: dict[str, Any],
        *,
        start_date: date | None,
        end_date: date | None,
        list_hash: str,
        list_ref: str,
    ) -> dict[str, Any] | None:
        if not _looks_like_monthly_report(item):
            return None

        inline_text = str(item.get("content") or item.get("excerpt") or "")
        inline_parsed = parse_cabia_battery_article(
            inline_text,
            source_url=str(item.get("source_url") or self.resource_api_url),
        )
        if inline_parsed and _in_range(inline_parsed["report_month"], start_date, end_date):
            inline_parsed["raw_content_sha256"] = list_hash
            inline_parsed["raw_snapshot_path"] = list_ref
            return inline_parsed

        urls = _resource_urls(item)
        for source_url in urls:
            try:
                response = requests.get(
                    source_url,
                    headers=CABIA_HEADERS,
                    timeout=self.timeout,
                    impersonate=self.impersonate,
                )
            except Exception as exc:  # noqa: BLE001
                self._add_error(f"CABIA 月报详情请求失败 [{source_url}]: {exc}")
                continue
            content = _response_bytes(response)
            if getattr(response, "status_code", 0) != 200 or not content:
                self._add_error(
                    f"CABIA 月报详情 HTTP {getattr(response, 'status_code', 'unknown')}"
                )
                continue

            is_pdf = "pdf" in str(getattr(response, "headers", {}).get("content-type", "")).lower()
            is_pdf = is_pdf or source_url.lower().split("?", 1)[0].endswith(".pdf")
            suffix = "pdf" if is_pdf else "html"
            content_hash, snapshot_ref = self._save_snapshot(
                f"detail_{_url_slug(source_url)}.{suffix}",
                content,
                compress=not is_pdf,
            )
            text = _pdf_text(content) if is_pdf else _response_text(response, content)
            parsed = parse_cabia_battery_article(text, source_url=source_url)
            if parsed and _in_range(parsed["report_month"], start_date, end_date):
                parsed["raw_content_sha256"] = content_hash
                parsed["raw_snapshot_path"] = snapshot_ref
                return parsed
            self._add_error(f"CABIA 月报未解析到装车量 [{source_url}]")
        if not urls:
            self._add_error("CABIA 月报没有可验证的正文或附件")
        return None

    def _save_snapshot(
        self,
        filename: str,
        content: bytes,
        *,
        compress: bool,
    ) -> tuple[str, str]:
        try:
            path = save_raw_snapshot(
                "automotive",
                f"cabia/{filename}",
                content,
                base_dir=self.raw_dir,
                compress=compress,
            )
            return raw_content_sha256(content), raw_snapshot_path_value(path, self.raw_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("保存 CABIA RAW 快照失败 [%s]: %s", filename, exc)
            return raw_content_sha256(content), ""

    def _add_error(self, message: str) -> None:
        self.last_errors = (*self.last_errors, message)
        logger.warning(message)


def _looks_like_monthly_report(item: dict[str, Any]) -> bool:
    text = " ".join(str(item.get(key) or "") for key in ("title", "name", "category", "excerpt"))
    return bool(re.search(r"20\d\d\s*年\s*(?:1-)?\d{1,2}\s*月", text)) and (
        "月度" in text or "动力电池" in text or "装车" in text
    )


def _resource_urls(item: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in ("download_url", "terms_pdf", "source_url"):
        value = str(item.get(key) or "").strip()
        if not value or value in candidates or not value.startswith(("http://", "https://")):
            continue
        if "example.com" in urlparse(value).netloc.lower():
            continue
        candidates.append(value)
    return candidates


def _resource_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return list(items)
    items = payload.get("items")
    if isinstance(items, list):
        return list(items)
    return []


def _page_url(url: str, page: int) -> str:
    if "{page}" in url:
        return url.format(page=page)
    if page == 1 and "page=" not in url:
        return url
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["page"] = str(page)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _response_bytes(response: Any) -> bytes:
    content = getattr(response, "content", b"")
    if isinstance(content, bytes) and content:
        return content
    if isinstance(content, str) and content:
        return content.encode("utf-8")
    text = getattr(response, "text", "")
    return text.encode("utf-8") if isinstance(text, str) else bytes(content or b"")


def _response_text(response: Any, content: bytes) -> str:
    text = getattr(response, "text", "")
    return text if isinstance(text, str) and text else content.decode("utf-8", errors="ignore")


def _json_payload(response: Any, content: bytes) -> Any:
    try:
        payload = response.json()
        if payload is not None:
            return payload
    except (AttributeError, ValueError, TypeError):
        pass
    try:
        return json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _pdf_text(content: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # noqa: BLE001
        logger.warning("解析 CABIA PDF 失败: %s", exc)
        return ""


def _in_range(report_month: str, start_date: date | None, end_date: date | None) -> bool:
    year, month = parse_month_string(report_month)
    month_start = date(year, month, 1)
    month_end = get_month_end_date(year, month)
    return not (
        (start_date is not None and month_end < start_date)
        or (end_date is not None and month_start > end_date)
    )


def _timestamp_slug() -> str:
    return re.sub(r"[^0-9A-Za-z]", "", now_utc_iso())[:20]


def _url_slug(url: str) -> str:
    parsed = urlparse(url)
    value = f"{parsed.netloc}{parsed.path}"
    if parsed.query:
        value = f"{value}-{parsed.query}"
    slug = re.sub(r"[^0-9A-Za-z]+", "-", value).strip("-").lower()
    return slug[:120] or "cabia_detail"


__all__ = [
    "CABIA_HEADERS",
    "CABIA_ONLINE_BASE_URL",
    "CABIA_RESOURCE_API_URL",
    "CabiaOnlineClient",
    "requests",
]
