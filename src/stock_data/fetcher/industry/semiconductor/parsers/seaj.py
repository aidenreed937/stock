"""SEAJ 半导体设备出货 RAW 解析器。"""

from __future__ import annotations

import io
import logging
import math
import re
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

import pypdf
from bs4 import BeautifulSoup
from bs4.element import Tag

logger = logging.getLogger(__name__)

DEFAULT_SEAJ_STATISTICS_URL = "https://www.seaj.or.jp/statistics/"


@dataclass(frozen=True)
class SeajPressReleaseTarget:
    """SEAJ 最新速报 PDF 链接与发布日期。"""

    pdf_url: str | None
    release_date: date | None


class SeajPdfParser:
    """SEAJ 官方速报 PDF 结构化解析器。"""

    def parse_pdf_bytes(
        self,
        pdf_bytes: bytes,
        release_date: date | None = None,
        release_dates: Mapping[str, date] | None = None,
    ) -> list[dict[str, Any]]:
        """从 SEAJ 出货速报 PDF 字节流中解析历史月份 3MMA 出货额与同比/环比增速。"""
        results: list[dict[str, Any]] = []
        if not pdf_bytes:
            return results

        try:
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            logger.warning("解析 SEAJ PDF 失败: %s", exc)
            return results

        return parse_seaj_pdf_text(
            full_text,
            release_date=release_date,
            release_dates=release_dates,
        )


def parse_seaj_historical_xls(
    xls_bytes: bytes,
    *,
    start_year: int | None = None,
    end_year: int | None = None,
) -> list[dict[str, Any]]:
    """解析 SEAJ 官方历史 Excel 中的日本制设备 3MMA 销售额。"""
    if not xls_bytes:
        return []

    try:
        import pandas as pd

        frame = pd.read_excel(
            io.BytesIO(xls_bytes),
            header=None,
            engine="xlrd",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("解析 SEAJ 历史 Excel 失败: %s", exc)
        return []

    current_year: int | None = None
    results: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False, name=None):
        if len(row) < 6:
            continue

        parsed_year = _parse_xls_year(row[0])
        if parsed_year is not None:
            current_year = parsed_year
        month = _parse_xls_month(row[1])
        if current_year is None or month is None:
            continue
        if start_year is not None and current_year < start_year:
            continue
        if end_year is not None and current_year > end_year:
            continue

        billings = _parse_xls_number(row[4])
        if billings is None:
            continue
        yoy = _parse_xls_number(row[5])
        results.append(
            {
                "report_month": f"{current_year:04d}-{month:02d}",
                "billings_3mma_jpy": round(billings / 1000.0, 2),
                "yoy_growth_3mma": round(yoy, 4) if yoy is not None else None,
                "sales_3mma_raw": _xls_cell_string(row[4]),
                "yoy_growth_3mma_raw": _xls_cell_string(row[5]),
            }
        )

    deduped = {str(item["report_month"]): item for item in results}
    return [deduped[month] for month in sorted(deduped)]


def parse_seaj_pdf_text(
    full_text: str,
    release_date: date | None = None,
    release_dates: Mapping[str, date] | None = None,
) -> list[dict[str, Any]]:
    """从 SEAJ PDF 提取后的文本解析月度设备出货表。"""
    table_pattern = re.compile(
        r"(\d{4})/(\d{1,2})(?:\([^\)]*\))?\s+([\d,]+)\s+"
        r"([+\-]?[\d\.]+%?)\s+([+\-]?[\d\.]+%?)",
        re.MULTILINE,
    )

    matches = list(table_pattern.finditer(full_text))
    latest_ym = max(
        (f"{int(match.group(1)):04d}-{int(match.group(2)):02d}" for match in matches),
        default=None,
    )
    resolved_release_dates = dict(release_dates or {})
    if latest_ym is not None and release_date is not None:
        resolved_release_dates[latest_ym] = release_date

    results: list[dict[str, Any]] = []
    for match in matches:
        yr_str, mo_str, bill_str, mom_str, yoy_str = match.groups()
        try:
            yr = int(yr_str)
            mo = int(mo_str)
            report_month = f"{yr:04d}-{mo:02d}"
            bill_raw = float(bill_str.replace(",", ""))
            b_3mma = round(bill_raw / 1000.0, 2)
            mom = round(float(mom_str.replace(",", "").replace("%", "")) / 100.0, 4)
            yoy = round(float(yoy_str.replace(",", "").replace("%", "")) / 100.0, 4)

            row_rel_date = resolved_release_dates.get(report_month)
            if row_rel_date is None:
                continue

            results.append(
                {
                    "report_month": report_month,
                    "billings_jpy_raw": bill_str,
                    "sales_3mma_raw": bill_str,
                    "billings_3mma_jpy": b_3mma,
                    "mom_reported": mom_str,
                    "yoy_reported": yoy_str,
                    "mom_growth_3mma_raw": mom_str,
                    "yoy_growth_3mma_raw": yoy_str,
                    "mom_growth_3mma": mom,
                    "yoy_growth_3mma": yoy,
                    "release_date": row_rel_date,
                }
            )
        except (ValueError, TypeError):
            continue

    return results


def parse_seaj_release_calendar_text(full_text: str) -> dict[str, date]:
    """从 SEAJ 官方发布日期日历提取报告月与实际列出的发布日期。"""
    pattern = re.compile(
        r"(?P<year>20\d\d)年\s*(?P<month>\d{1,2})月度.*?"
        r"(?P<release_year>20\d\d)/(?P<release_month>\d{1,2})/(?P<release_day>\d{1,2})"
    )
    releases: dict[str, date] = {}
    for match in pattern.finditer(full_text):
        try:
            report_month = f"{int(match.group('year')):04d}-{int(match.group('month')):02d}"
            release_date = date(
                int(match.group("release_year")),
                int(match.group("release_month")),
                int(match.group("release_day")),
            )
        except ValueError:
            continue
        releases[report_month] = release_date
    return releases


def parse_seaj_release_calendar_pdf(pdf_bytes: bytes) -> dict[str, date]:
    """解析 SEAJ 官方发布日期日历 PDF。"""
    if not pdf_bytes:
        return {}
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        logger.warning("解析 SEAJ 发布日期日历失败: %s", exc)
        return {}
    return parse_seaj_release_calendar_text(text)


def parse_seaj_press_release_target(
    html_text: str,
    base_url: str = DEFAULT_SEAJ_STATISTICS_URL,
) -> SeajPressReleaseTarget:
    """从 SEAJ statistics 首页解析最新半导体制造装置出货速报 PDF 链接。"""
    soup = BeautifulSoup(html_text, "html.parser")
    for tr in soup.find_all("tr"):
        row_text = tr.get_text(separator=" ", strip=True)
        if "半導体製造装置（日本製）" not in row_text or "販売高速報値" not in row_text:
            continue

        release_date = _parse_japanese_release_date(row_text)
        pdf_url = None
        anchor = tr.find("a", href=True)
        if isinstance(anchor, Tag):
            href = anchor.get("href")
            if isinstance(href, str):
                pdf_url = urllib.parse.urljoin(base_url, href)
        return SeajPressReleaseTarget(pdf_url=pdf_url, release_date=release_date)

    return SeajPressReleaseTarget(pdf_url=None, release_date=None)


def parse_seaj_historical_xls_url(
    html_text: str,
    base_url: str = DEFAULT_SEAJ_STATISTICS_URL,
) -> str | None:
    """从 SEAJ statistics 首页解析半导体设备历史 Excel 下载链接。"""
    soup = BeautifulSoup(html_text, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if not isinstance(href, str) or not href.lower().endswith((".xls", ".xlsx")):
            continue
        row = anchor.find_parent("tr")
        context = row.get_text(separator=" ", strip=True) if isinstance(row, Tag) else ""
        if "販売高速報値" not in context or "半導体" not in context:
            continue
        return urllib.parse.urljoin(base_url, href)
    return None


def _parse_xls_year(value: Any) -> int | None:
    text = _xls_cell_string(value)
    if text is None:
        return None
    match = re.match(r"^(20\d{2})", text)
    return int(match.group(1)) if match else None


def _parse_xls_month(value: Any) -> int | None:
    text = _xls_cell_string(value)
    if text is None:
        return None
    match = re.match(r"^(\d{1,2})", text)
    if match is None:
        return None
    month = int(match.group(1))
    return month if 1 <= month <= 12 else None


def _parse_xls_number(value: Any) -> float | None:
    text = _xls_cell_string(value)
    if text is None:
        return None
    try:
        number = float(text.replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if "%" in text:
        number /= 100.0
    return number


def _xls_cell_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "<na>"}:
        return None
    return text


def _parse_japanese_release_date(text: str) -> date | None:
    match = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", text)
    if not match:
        return None
    return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
