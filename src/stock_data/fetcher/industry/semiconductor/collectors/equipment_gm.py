"""Quarterly equipment-maker gross-margin collectors with source watermarks."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import logging
import os
import re
import time
import urllib.request
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path
from typing import Any, ClassVar, cast
from urllib.parse import urljoin

import polars as pl

from stock_data.fetcher.industry.contracts import IndustryFrameResult
from stock_data.fetcher.industry.semiconductor.schemas import (
    EQUIPMENT_GM_ATOMIC_SCHEMA,
)

logger = logging.getLogger(__name__)

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{}.json"
SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{}/{}"
SEC_RAW_SUBDIR = Path("semiconductor/equipment/sec_edgar")
TEL_RAW_SUBDIR = Path("semiconductor/equipment/tel/ir_tanshin")
TEL_REPORT_URL = "https://www.tel.com/ir/library/report/"
TEL_BASE_URL = "https://www.tel.com"
_SEC_MIN_DATE = date(2015, 10, 1)
_SEC_FORMS = frozenset({"8-K", "8-K/A", "10-Q", "10-Q/A"})
_SEC_HEADERS = {
    "User-Agent": os.getenv("SEC_USER_AGENT", "stock-data-semiconductor/1.0 contact@example.com"),
    "Accept-Encoding": "gzip, deflate",
}
_TEL_HEADERS = {"User-Agent": "stock-data-semiconductor/1.0"}
_SEC_MANIFEST_FIELDS = (
    "company",
    "form",
    "filing_date",
    "accession",
    "primary_document",
    "exhibit",
    "source_url",
    "raw_path",
    "raw_content_sha256",
    "status",
    "collected_at",
)
_TEL_MANIFEST_FIELDS = (
    "company",
    "form",
    "filing_date",
    "report_quarter",
    "period_end",
    "accession",
    "source_url",
    "raw_path",
    "raw_content_sha256",
    "status",
    "collected_at",
)


def _parse_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _as_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _maybe_decompress(content: bytes) -> bytes:
    return gzip.decompress(content) if content[:2] == b"\x1f\x8b" else content


def _gzip_hash(path: Path) -> str:
    with gzip.open(path, "rb") as handle:
        return _content_hash(handle.read())


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _read_manifest(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [
            {str(key): str(value or "") for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def _write_manifest(path: Path, rows: list[dict[str, str]], fields: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    ordered = sorted(rows, key=lambda row: (row.get("filing_date", ""), row.get("raw_path", "")))
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in ordered)
    temporary.replace(path)


def _upsert_manifest(
    rows: list[dict[str, str]], entry: dict[str, str], *, key_fields: tuple[str, ...]
) -> None:
    key = tuple(entry.get(field, "") for field in key_fields)
    for index, existing in enumerate(rows):
        if tuple(existing.get(field, "") for field in key_fields) == key:
            rows[index] = entry
            return
    rows.append(entry)


def _normalize_accession(value: object) -> str:
    return str(value or "").replace("-", "").strip()


def _equipment_period_end(ticker: str, report_quarter: object) -> date | None:
    match = re.match(r"(?:FY)?(\d{4})-Q([1-4])$", str(report_quarter or "").strip(), re.I)
    if match is None:
        return None
    year, quarter = int(match.group(1)), int(match.group(2))
    if ticker == "AMAT":
        month = (1, 4, 7, 10)[quarter - 1]
    else:
        month = (9, 12, 3, 6)[quarter - 1]
        if quarter == 2:
            year -= 1
    return date(year, month, monthrange(year, month)[1])


def _tel_period_end(filename: str) -> date | None:
    match = re.match(r"(?:fy)?(\d{2})(?:q)([1-4])", filename, re.I)
    if match is None:
        return None
    number, quarter = int(match.group(1)), int(match.group(2))
    if 48 <= number <= 58:
        fiscal_year = 2000 + (number - 48 + 11)
    elif 20 <= number <= 30:
        fiscal_year = 2000 + number
    else:
        return None
    year, month = {
        1: (fiscal_year - 1, 6),
        2: (fiscal_year - 1, 9),
        3: (fiscal_year - 1, 12),
        4: (fiscal_year, 3),
    }[quarter]
    return date(year, month, monthrange(year, month)[1])


def _in_range(value: date | None, start_date: date | None, end_date: date | None) -> bool:
    if value is None:
        return False
    return (start_date is None or value >= start_date) and (end_date is None or value <= end_date)


def _filter_period_frame(
    frame: pl.DataFrame,
    column: str,
    start_date: date | None,
    end_date: date | None,
) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    result = frame
    if start_date is not None:
        result = result.filter(pl.col(column) >= pl.lit(start_date))
    if end_date is not None:
        result = result.filter(pl.col(column) <= pl.lit(end_date))
    return result


def _pick_earnings_exhibit(files: list[str], ticker: str) -> str | None:
    candidates = [
        name
        for name in files
        if name.lower().endswith((".htm", ".html"))
        and "r1.htm" not in name.lower()
        and "index" not in name.lower()
    ]
    for name in candidates:
        lowered = name.lower()
        if ticker == "LRCX":
            if "8kx" in lowered or "8k" in lowered.replace("x", "").replace("_", ""):
                continue
            if (
                "lrcx_exhibit" in lowered
                and "991" in lowered
                and re.search(r"xq[1-4]x\d{4}", lowered)
            ) or ("pressrelease" in lowered and "q" in lowered and re.search(r"\d{4}", lowered)):
                return name
        elif ticker == "KLAC":
            if any(word in lowered for word in ("dividend", "joint", "director", "hanley")):
                continue
            if "earningsrelease" in lowered or "exhibit991earnings" in lowered:
                return name
        elif not any(word in lowered for word in ("dividend", "eml", "credit")) and (
            "earnings" in lowered or "pressrelease" in lowered
        ):
            return name
    return None


def _build_atomic_frame(ticker: str, rows: list[dict[str, Any]]) -> pl.DataFrame:
    records: list[dict[str, Any]] = []
    for row in rows:
        quarter = str(row.get("report_quarter") or "").strip()
        release_date = _parse_date(row.get("release_date"))
        period_end = _equipment_period_end(ticker, quarter)
        if not quarter or release_date is None or period_end is None:
            continue
        records.append(
            {
                "company": ticker,
                "report_quarter": quarter,
                "report_period_end": period_end,
                "release_date": release_date,
                "gross_margin_pct": _as_float(row.get("gross_margin_pct")),
                "gm_guidance_next_pct": _as_float(row.get("gm_guidance_next_pct")),
                "services_share_pct": _as_float(row.get("services_share_pct")),
                "source": str(row.get("source") or ""),
                "data_status": str(row.get("data_status") or "actual"),
            }
        )
    if not records:
        return pl.DataFrame(schema=EQUIPMENT_GM_ATOMIC_SCHEMA)
    return (
        pl.DataFrame(records, schema=EQUIPMENT_GM_ATOMIC_SCHEMA)
        .unique(subset=["company", "report_quarter"], keep="last")
        .sort(["report_period_end", "release_date"])
    )


class EquipmentGmSecCollector:
    """Incrementally collect one US equipment maker's SEC filings."""

    ticker: ClassVar[str] = ""
    cik: ClassVar[str] = ""

    def __init__(
        self,
        raw_dir: Path | str,
        timeout: int = 30,
        lookback_days: int = 90,
        request_pause: float = 0.2,
    ) -> None:
        if not self.ticker or not self.cik:
            raise ValueError("SEC 设备商采集器缺少 ticker/cik")
        self.raw_root = Path(raw_dir)
        self.company_raw_dir = self.raw_root / SEC_RAW_SUBDIR / self.ticker
        self.manifest_path = self.company_raw_dir / "manifest.csv"
        self.timeout = timeout
        self.lookback_days = lookback_days
        self.request_pause = request_pause

    def collect_raw(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> IndustryFrameResult:
        del start_date, end_date
        manifest = self._load_or_seed_manifest()
        errors: list[str] = []
        fetched: list[str] = []
        try:
            filings = self._list_recent_filings(_latest_filing_date(manifest))
        except Exception as exc:  # noqa: BLE001
            logger.warning("SEC 提交列表获取失败 [%s]: %s", self.ticker, exc)
            filings = []
            errors.append(str(exc))

        for filing in filings:
            key = (str(filing["form"]), _normalize_accession(filing["accession"]))
            known = {
                (row.get("form", ""), _normalize_accession(row.get("accession", ""))): row
                for row in manifest
            }.get(key)
            if (
                not force
                and known is not None
                and known.get("status") in {"success", "seeded", "ignored"}
            ):
                continue
            try:
                entry = self._download_filing(filing, force=force)
            except Exception as exc:  # noqa: BLE001
                logger.warning("SEC 财报下载失败 [%s %s]: %s", self.ticker, key[1], exc)
                errors.append(f"{key[1]}: {exc}")
                continue
            _upsert_manifest(manifest, entry, key_fields=("form", "accession"))
            if entry.get("status") == "success":
                fetched.append(entry.get("filing_date", ""))

        _write_manifest(self.manifest_path, manifest, _SEC_MANIFEST_FIELDS)
        # 采集窗口只约束 SEC/IR 的发现与下载；解析器返回本地完整事实，
        # 让 Curated 以主键幂等合并并吸收更正/修订，而不因财年末与自然季度错位丢行。
        frame = self._parse_frame()
        status = (
            "SUCCESS" if not frame.is_empty() and not errors else "PARTIAL" if errors else "EMPTY"
        )
        return IndustryFrameResult(
            frame=frame,
            status=status,
            fetched_periods=tuple(sorted(set(fetched))),
            errors=tuple(errors),
        )

    def _load_or_seed_manifest(self) -> list[dict[str, str]]:
        manifest = _read_manifest(self.manifest_path)
        if manifest:
            return manifest
        self.company_raw_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.company_raw_dir.glob("*.gz")):
            parts = path.name.split("__", 3)
            if len(parts) != 4 or parts[0] != self.ticker:
                continue
            form = "10-Q" if "__10Q_" in path.name else "8-K"
            manifest.append(
                {
                    "company": self.ticker,
                    "form": form,
                    "filing_date": parts[1],
                    "accession": parts[2],
                    "primary_document": "",
                    "exhibit": parts[3].removesuffix(".gz"),
                    "source_url": "",
                    "raw_path": _relative_path(path, self.raw_root),
                    "raw_content_sha256": _gzip_hash(path),
                    "status": "seeded",
                    "collected_at": _now(),
                }
            )
        if manifest:
            _write_manifest(self.manifest_path, manifest, _SEC_MANIFEST_FIELDS)
        return manifest

    def _list_recent_filings(self, cursor: date | None) -> list[dict[str, str]]:
        data = self._get_json(SEC_SUBMISSIONS_URL.format(self.cik))
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        lower = (
            _SEC_MIN_DATE
            if cursor is None
            else max(_SEC_MIN_DATE, cursor - timedelta(days=self.lookback_days))
        )
        filings: list[dict[str, str]] = []
        for index, form_value in enumerate(forms):
            form = str(form_value)
            filing_date = str(recent.get("filingDate", [])[index])
            parsed_date = _parse_date(filing_date)
            if form not in _SEC_FORMS or parsed_date is None or parsed_date < lower:
                continue
            filings.append(
                {
                    "form": form,
                    "filing_date": filing_date,
                    "accession": str(recent.get("accessionNumber", [])[index]),
                    "primary_document": str(recent.get("primaryDocument", [])[index]),
                }
            )
        return filings

    def _download_filing(self, filing: dict[str, str], *, force: bool = False) -> dict[str, str]:
        form = filing["form"]
        accession = _normalize_accession(filing["accession"])
        accession_dir = SEC_ARCHIVE_URL.format(str(int(self.cik)), accession)
        exhibit = filing["primary_document"]
        if form.startswith("8-K"):
            index = self._get_json(f"{accession_dir}/index.json")
            items = index.get("directory", {}).get("item", [])
            files = [str(item.get("name", "")) for item in items if isinstance(item, dict)]
            exhibit = _pick_earnings_exhibit(files, self.ticker) or ""
            if not exhibit:
                return self._manifest_entry(filing, "", "ignored", "", "")
        source_url = f"{accession_dir}/{exhibit}"
        raw_name = f"{self.ticker}__{filing['filing_date']}__{accession}__{exhibit}.gz"
        raw_path = self.company_raw_dir / raw_name
        if raw_path.exists() and not force:
            return self._manifest_entry(
                filing,
                exhibit,
                "seeded",
                _relative_path(raw_path, self.raw_root),
                _gzip_hash(raw_path),
                source_url=source_url,
            )
        content = self._get_bytes(source_url)
        if form.startswith("8-K") and len(content) < 5000:
            content = self._get_bytes(f"{accession_dir}/{filing['primary_document']}")
            exhibit = filing["primary_document"]
            source_url = f"{accession_dir}/{exhibit}"
            if not _has_earnings_text(content):
                return self._manifest_entry(filing, exhibit, "ignored", "", "", source_url)
            raw_name = f"{self.ticker}__{filing['filing_date']}__{accession}__{exhibit}.gz"
            raw_path = self.company_raw_dir / raw_name
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(raw_path, "wb") as handle:
            handle.write(content)
        time.sleep(self.request_pause)
        return self._manifest_entry(
            filing,
            exhibit,
            "success",
            _relative_path(raw_path, self.raw_root),
            _content_hash(content),
            source_url=source_url,
        )

    def _manifest_entry(
        self,
        filing: dict[str, str],
        exhibit: str,
        status: str,
        raw_path: str,
        content_hash: str,
        source_url: str = "",
    ) -> dict[str, str]:
        return {
            "company": self.ticker,
            "form": filing["form"],
            "filing_date": filing["filing_date"],
            "accession": _normalize_accession(filing["accession"]),
            "primary_document": filing["primary_document"],
            "exhibit": exhibit,
            "source_url": source_url,
            "raw_path": raw_path,
            "raw_content_sha256": content_hash,
            "status": status,
            "collected_at": _now(),
        }

    def _parse_frame(self) -> pl.DataFrame:
        from importlib import import_module

        parser = import_module("scripts.equipment_giants_parse")

        rows = parser.parse_company(self.ticker, raw_dir=self.raw_root / SEC_RAW_SUBDIR)
        return _build_atomic_frame(self.ticker, rows)

    def _get_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers=_SEC_HEADERS)  # noqa: S310
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            payload = json.loads(_maybe_decompress(response.read()))
        if not isinstance(payload, dict):
            raise ValueError(f"SEC 响应不是 JSON 对象: {url}")
        return payload

    def _get_bytes(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers=_SEC_HEADERS)  # noqa: S310
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            return _maybe_decompress(bytes(response.read()))


class AmatEquipmentGmCollector(EquipmentGmSecCollector):
    ticker = "AMAT"
    cik = "0000006951"


class LrcxEquipmentGmCollector(EquipmentGmSecCollector):
    ticker = "LRCX"
    cik = "0000707549"


class KlacEquipmentGmCollector(EquipmentGmSecCollector):
    ticker = "KLAC"
    cik = "0000319201"


class TelEquipmentGmCollector:
    """Incrementally collect TEL's official quarterly result PDFs."""

    def __init__(self, raw_dir: Path | str, timeout: int = 30) -> None:
        self.raw_root = Path(raw_dir)
        self.raw_pdf_dir = self.raw_root / TEL_RAW_SUBDIR
        self.manifest_path = self.raw_pdf_dir / "manifest.csv"
        self.timeout = timeout

    def collect_raw(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> IndustryFrameResult:
        del start_date, end_date
        manifest = self._load_or_seed_manifest()
        errors: list[str] = []
        try:
            urls = self._list_urls()
        except Exception as exc:  # noqa: BLE001
            logger.warning("TEL IR 报告列表获取失败: %s", exc)
            urls = []
            errors.append(str(exc))

        known_names = {Path(row.get("raw_path", "")).name for row in manifest}
        for url in urls:
            name = url.rsplit("/", 1)[-1]
            period_end = _tel_period_end(name)
            raw_path = self.raw_pdf_dir / name
            if not force and name in known_names and raw_path.exists():
                continue
            try:
                content = self._get_bytes(urljoin(TEL_BASE_URL, url))
                if len(content) < 10000:
                    raise ValueError(f"PDF 内容过小: {len(content)} bytes")
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(content)
                entry = {
                    "company": "TEL",
                    "form": "quarterly_pdf",
                    "filing_date": "",
                    "report_quarter": "",
                    "period_end": period_end.isoformat() if period_end else "",
                    "accession": name,
                    "source_url": urljoin(TEL_BASE_URL, url),
                    "raw_path": _relative_path(raw_path, self.raw_root),
                    "raw_content_sha256": _content_hash(content),
                    "status": "success",
                    "collected_at": _now(),
                }
                _upsert_manifest(manifest, entry, key_fields=("accession",))
            except Exception as exc:  # noqa: BLE001
                logger.warning("TEL 财报下载失败 [%s]: %s", name, exc)
                errors.append(f"{name}: {exc}")

        frame = self._parse_frame()
        self._enrich_manifest(manifest, frame)
        _write_manifest(self.manifest_path, manifest, _TEL_MANIFEST_FIELDS)
        status = (
            "SUCCESS" if not frame.is_empty() and not errors else "PARTIAL" if errors else "EMPTY"
        )
        return IndustryFrameResult(frame=frame, status=status, errors=tuple(errors))

    def _load_or_seed_manifest(self) -> list[dict[str, str]]:
        manifest = _read_manifest(self.manifest_path)
        if manifest:
            return manifest
        self.raw_pdf_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.raw_pdf_dir.glob("*.pdf")):
            period_end = _tel_period_end(path.name)
            manifest.append(
                {
                    "company": "TEL",
                    "form": "quarterly_pdf",
                    "filing_date": "",
                    "report_quarter": "",
                    "period_end": period_end.isoformat() if period_end else "",
                    "accession": path.name,
                    "source_url": "",
                    "raw_path": _relative_path(path, self.raw_root),
                    "raw_content_sha256": _content_hash(path.read_bytes()),
                    "status": "seeded",
                    "collected_at": _now(),
                }
            )
        if manifest:
            _write_manifest(self.manifest_path, manifest, _TEL_MANIFEST_FIELDS)
        return manifest

    def _list_urls(self) -> list[str]:
        content = self._get_bytes(TEL_REPORT_URL).decode("utf-8", "ignore")
        seen: set[str] = set()
        urls: list[str] = []
        for url in re.findall(r'href="([^"]*tanshin-e\.pdf)"', content):
            if url not in seen:
                seen.add(url)
                urls.append(url)
        return urls

    def _parse_frame(self) -> pl.DataFrame:
        from importlib import import_module

        parser = import_module("scripts.tel_quarterly_parse")

        return cast("pl.DataFrame", parser.build_quarterly_frame(raw_dir=self.raw_pdf_dir))

    @staticmethod
    def _enrich_manifest(manifest: list[dict[str, str]], frame: pl.DataFrame) -> None:
        if frame.is_empty():
            return
        by_file = {str(row["file"]): row for row in frame.to_dicts()}
        for entry in manifest:
            row = by_file.get(Path(entry.get("raw_path", "")).name)
            if row is None:
                continue
            entry["report_quarter"] = str(row.get("report_quarter") or "")
            entry["period_end"] = str(row.get("period_end") or "")
            release_date = row.get("release_date")
            entry["filing_date"] = (
                release_date.isoformat() if isinstance(release_date, date) else ""
            )

    def _get_bytes(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers=_TEL_HEADERS)  # noqa: S310
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            return _maybe_decompress(bytes(response.read()))


def _latest_filing_date(manifest: list[dict[str, str]]) -> date | None:
    dates = [_parse_date(row.get("filing_date")) for row in manifest]
    valid = [value for value in dates if value is not None]
    return max(valid) if valid else None


def _has_earnings_text(content: bytes) -> bool:
    text = content.decode("utf-8", "ignore").lower()
    return "gross margin" in text or "revenue" in text


__all__ = [
    "AmatEquipmentGmCollector",
    "EquipmentGmSecCollector",
    "KlacEquipmentGmCollector",
    "LrcxEquipmentGmCollector",
    "TelEquipmentGmCollector",
]
