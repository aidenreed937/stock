"""CPCA 官方新能源月报目录与附件归档客户端。"""

from __future__ import annotations

import io
import logging
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from xml.etree import ElementTree

import pypdf
from bs4 import BeautifulSoup
from curl_cffi import requests

from stock_data.fetcher.industry.automotive.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.automotive.parsers.cpca import parse_cpca_bulletin_article
from stock_data.fetcher.industry.common import (
    get_month_end_date,
    parse_month_string,
    save_raw_snapshot,
)

logger = logging.getLogger(__name__)

CPCA_OFFICIAL_BASE_URL = "https://www.cpcaauto.com"
CPCA_REPORT_INDEX_URL = f"{CPCA_OFFICIAL_BASE_URL}/news.php?types=bgzl&anid=126"
CPCA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


class CpcaReportArchiveClient:
    """发现并解析 CPCA 官方新能源月报附件。"""

    def __init__(
        self,
        raw_dir: Path,
        *,
        timeout: int = 60,
        impersonate: str = "chrome120",
        max_history_pages: int = 12,
        report_index_url: str = CPCA_REPORT_INDEX_URL,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.timeout = timeout
        self.impersonate = impersonate
        self.max_history_pages = max_history_pages
        self.report_index_url = report_index_url
        self.last_errors: tuple[str, ...] = ()

    def fetch(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> list[dict[str, Any]]:
        self.last_errors = ()
        records: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for page in range(1, self.max_history_pages + 1):
            page_url = _page_url(self.report_index_url, page)
            response = self._get(page_url, "CPCA 月报目录")
            if response is None:
                break
            content = _response_bytes(response)
            if not content:
                break
            self._save_snapshot(f"report_index_{page}.html", content, compress=True)
            report_links = _report_links(BeautifulSoup(content, "html.parser"), page_url)
            if not report_links:
                break
            for report_month, detail_url, title in report_links:
                if detail_url in seen_urls or not _month_in_range(
                    report_month, start_date, end_date
                ):
                    continue
                seen_urls.add(detail_url)
                parsed = self._fetch_report(
                    report_month=report_month,
                    detail_url=detail_url,
                    title=title,
                )
                if parsed is not None:
                    records.append(parsed)
            if not _page_has_older_reports(report_links, start_date):
                break
        return records

    def _fetch_report(
        self,
        *,
        report_month: str,
        detail_url: str,
        title: str,
    ) -> dict[str, Any] | None:
        response = self._get(detail_url, "CPCA 月报详情")
        if response is None:
            return None
        page_content = _response_bytes(response)
        detail_snapshot = self._save_snapshot(
            f"report_detail_{_url_slug(detail_url)}.html", page_content, compress=True
        )
        soup = BeautifulSoup(page_content, "html.parser")
        download_url = _download_url(soup, detail_url)
        text = soup.get_text(" ", strip=True)
        archive_snapshot = ""
        archive_digest = ""
        if download_url:
            archive_response = self._get(download_url, "CPCA 月报附件")
            if archive_response is not None:
                archive_content = _response_bytes(archive_response)
                suffix = Path(urlparse(download_url).path).suffix.lower() or ".bin"
                archive_path = self._save_snapshot(
                    f"reports/{report_month}_{_url_slug(download_url)}{suffix}",
                    archive_content,
                    compress=False,
                )
                archive_snapshot = raw_snapshot_path_value(archive_path, self.raw_dir)
                archive_digest = raw_content_sha256(archive_content)
                text = "\n".join(filter(None, [text, _extract_archive_text(archive_path)]))
        parsed = parse_cpca_bulletin_article(
            f"{title}\n{text}",
            source_url=detail_url,
            report_month_hint=report_month,
        )
        if parsed is None:
            self._add_error(f"CPCA 月报未解析到可验证产销数据 [{report_month}]")
            return None
        parsed["raw_content_sha256"] = archive_digest or raw_content_sha256(page_content)
        parsed["raw_snapshot_path"] = archive_snapshot or raw_snapshot_path_value(
            detail_snapshot, self.raw_dir
        )
        return parsed

    def _get(self, url: str, description: str) -> Any | None:
        try:
            response = requests.get(
                url,
                headers=CPCA_HEADERS,
                timeout=self.timeout,
                impersonate=self.impersonate,
            )
        except Exception as exc:  # noqa: BLE001
            self._add_error(f"{description}请求失败 [{url}]: {exc}")
            return None
        if getattr(response, "status_code", 0) != 200:
            self._add_error(f"{description} HTTP {getattr(response, 'status_code', 'unknown')}")
            return None
        return response

    def _save_snapshot(self, filename: str, content: bytes, *, compress: bool) -> Path:
        return save_raw_snapshot(
            "automotive",
            f"cpca/{filename}",
            content,
            base_dir=self.raw_dir,
            compress=compress,
        )

    def _add_error(self, message: str) -> None:
        self.last_errors = (*self.last_errors, message)
        logger.warning(message)


def _report_links(soup: BeautifulSoup, page_url: str) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    for anchor in soup.find_all("a", href=True):
        title = anchor.get_text(" ", strip=True)
        match = re.search(r"20\d{2}\s*年\s*(?:1-)?\d{1,2}\s*月", title)
        if not match or "新能源" not in title or "月报" not in title:
            continue
        report_month = _normalize_month(match.group(0))
        results.append((report_month, urljoin(page_url, str(anchor["href"])), title))
    return results


def _download_url(soup: BeautifulSoup, detail_url: str) -> str | None:
    for anchor in soup.find_all("a", href=True):
        text = anchor.get_text(" ", strip=True)
        href = str(anchor["href"])
        if "下载" in text or Path(urlparse(href).path).suffix.lower() in {".rar", ".zip", ".pdf"}:
            return urljoin(detail_url, href)
    return None


def _extract_archive_text(path: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="cpca-report-") as temp_dir:
        target = Path(temp_dir)
        if path.suffix.lower() == ".pdf":
            return _pdf_text(path.read_bytes())
        if path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as archive:
                    archive.extractall(target)
            except (OSError, zipfile.BadZipFile):
                return ""
        elif bsdtar := shutil.which("bsdtar"):
            listed = subprocess.run(  # noqa: S603
                [bsdtar, "-tf", str(path)], capture_output=True, check=False, text=True
            )
            if listed.returncode != 0 or not _safe_archive_members(listed.stdout):
                return ""
            completed = subprocess.run(  # noqa: S603
                [bsdtar, "-xf", str(path), "-C", str(target)],
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                return ""
        else:
            return ""
        texts: list[str] = []
        for child in target.rglob("*"):
            if not child.is_file():
                continue
            suffix = child.suffix.lower()
            if suffix == ".pdf":
                texts.append(_pdf_text(child.read_bytes()))
            elif suffix == ".pptx":
                texts.append(_pptx_text(child))
            elif suffix in {".txt", ".html", ".htm"}:
                texts.append(child.read_text(encoding="utf-8", errors="ignore"))
        return "\n".join(texts)


def _pdf_text(content: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:  # noqa: BLE001
        return ""


def _pptx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            texts: list[str] = []
            namespace = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
            for name in archive.namelist():
                if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                    root = ElementTree.fromstring(archive.read(name))  # noqa: S314
                    texts.extend(node.text or "" for node in root.findall(".//a:t", namespace))
            return "\n".join(texts)
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError):
        return ""


def _safe_archive_members(listing: str) -> bool:
    for member in listing.splitlines():
        normalized = member.strip().replace("\\", "/")
        if not normalized or normalized.startswith("/") or "../" in f"{normalized}/":
            return False
    return True


def _page_url(url: str, page: int) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query["page"] = [str(page)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _page_has_older_reports(
    report_links: list[tuple[str, str, str]], start_date: date | None
) -> bool:
    if start_date is None:
        return True
    return any(_month_start(month) >= start_date.replace(day=1) for month, _, _ in report_links)


def _normalize_month(value: str) -> str:
    match = re.search(r"(20\d{2})\s*年\s*(?:1-)?(\d{1,2})\s*月", value)
    if match is None:
        raise ValueError(f"无法解析 CPCA 月份: {value}")
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"


def _month_start(value: str) -> date:
    year, month = parse_month_string(value)
    return date(year, month, 1)


def _month_in_range(value: str, start_date: date | None, end_date: date | None) -> bool:
    year, month = parse_month_string(value)
    month_start = date(year, month, 1)
    month_end = get_month_end_date(year, month)
    return not (
        (start_date is not None and month_end < start_date)
        or (end_date is not None and month_start > end_date)
    )


def _url_slug(url: str) -> str:
    parsed = urlparse(url)
    value = f"{parsed.netloc}{parsed.path}"
    return re.sub(r"[^0-9A-Za-z]+", "-", value).strip("-").lower()[:120] or "cpca"


def _response_bytes(response: Any) -> bytes:
    content = getattr(response, "content", b"")
    if isinstance(content, bytes) and content:
        return content
    text = getattr(response, "text", "")
    return text.encode("utf-8") if isinstance(text, str) else b""


__all__ = [
    "CPCA_HEADERS",
    "CPCA_OFFICIAL_BASE_URL",
    "CPCA_REPORT_INDEX_URL",
    "CpcaReportArchiveClient",
    "requests",
]
