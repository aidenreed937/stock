"""Susquehanna 半导体交期公开报道发现与解析。"""

from __future__ import annotations

import html
import logging
import re
from datetime import date
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from stock_data.fetcher.industry.common import save_raw_snapshot
from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.semiconductor.models import ChipLeadTimeRecord

logger = logging.getLogger(__name__)

_MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_PATTERN = re.compile(
    r"\b(" + "|".join(_MONTH_NAMES) + r")\b(?:\s+(20\d{2}))?", re.IGNORECASE
)
_WEEK_VALUE_PATTERN = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[- ]?\s*weeks?\b", re.IGNORECASE)
_LEAD_TIME_PATTERN = re.compile(r"\b(?:lead[- ]?times?|wait[- ]?times?)\b", re.IGNORECASE)
_SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}


class _VisibleTextParser(HTMLParser):
    """提取网页可见文本，避免引入额外正文抓取依赖。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self.parts.append(data.strip())


def html_to_visible_text(content: bytes | str, max_chars: int = 200_000) -> str:
    """把在线文章 HTML 转成可供规则解析的有限长度文本。"""
    raw = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else content
    parser = _VisibleTextParser()
    try:
        parser.feed(raw)
        parser.close()
        text = " ".join(parser.parts)
    except (AssertionError, ValueError):
        text = raw
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return text[:max_chars]


def parse_susquehanna_rss_feed(content: bytes | str) -> list[dict[str, str]]:
    """解析公开新闻 RSS，保留发现阶段的原始字段。"""
    raw = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else content
    item_blocks = re.findall(r"<item\b[^>]*>(.*?)</item>", raw, flags=re.IGNORECASE | re.DOTALL)
    if not item_blocks:
        logger.warning("Susquehanna 新闻 RSS 未发现 item 节点")
        return []

    items: list[dict[str, str]] = []
    for item in item_blocks:
        link = _rss_field(item, "link")
        title = _rss_field(item, "title")
        if not link or not title:
            continue
        items.append(
            {
                "title": title,
                "link": link,
                "description": _rss_field(item, "description"),
                "pub_date": _rss_field(item, "pubDate"),
                "source": _rss_field(item, "source"),
            }
        )
    return items


def _rss_field(item: str, name: str) -> str:
    match = re.search(
        rf"<{name}\b[^>]*>(.*?)</{name}>",
        item,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return ""
    value = match.group(1).strip()
    value = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", value, flags=re.DOTALL)
    return html.unescape(value).strip()


def parse_susquehanna_published_date(value: object) -> date | None:
    """把 RSS 或页面元数据中的发布日期解析为自然日。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError, OverflowError):
        return None


def parse_susquehanna_lead_time_article(
    title: str,
    article_text: str,
    source_url: str,
    published_date: date | None,
    *,
    infer_report_month: bool = False,
) -> dict[str, Any] | None:
    """从公开报道中提取 Susquehanna 月度总交期。

    分类交期只有在后续有明确且稳定的源端表格时才纳入，公开报道正文目前只采总交期，
    避免把新闻中的个别品类数字误当成可加权的全行业分类均值。
    """
    full_text = f"{title}\n{article_text}".strip()
    lowered = full_text.lower()
    if "susquehanna" not in lowered and "semisignals" not in lowered:
        return None

    value_match = _select_lead_time_value(full_text)
    if value_match is None:
        return None
    report_month, inferred = _extract_report_month(
        full_text,
        value_match.start(),
        published_date,
        infer_report_month=infer_report_month,
    )
    if report_month is None or published_date is None:
        return None

    host = urlsplit(source_url).netloc.lower().removeprefix("www.")
    publisher = {
        "seekingalpha.com": "Seeking Alpha",
        "finance.yahoo.com": "Yahoo Finance",
        "electronicsweekly.com": "Electronics Weekly",
        "theregister.com": "The Register",
        "techspot.com": "TechSpot",
        "astutegroup.com": "Astute Group",
        "bloomberg.com": "Bloomberg",
        "marketwatch.com": "MarketWatch",
        "ttnews.com": "Transport Topics",
    }.get(host, host or "Public Coverage")
    return {
        "report_month": report_month,
        "avg_lead_time_weeks": float(value_match.group(1)),
        "lead_time_raw": value_match.group(0).strip(),
        "source": f"Susquehanna/{publisher}",
        "source_url": source_url,
        "release_date": published_date,
        "data_status": "actual",
        "report_month_inferred": inferred,
    }


def _select_lead_time_value(text: str) -> re.Match[str] | None:
    matches = list(_WEEK_VALUE_PATTERN.finditer(text))
    if not matches:
        return None
    lead_positions = [match.start() for match in _LEAD_TIME_PATTERN.finditer(text)]
    if not lead_positions:
        return matches[0]

    def score(match: re.Match[str]) -> tuple[float, int]:
        distance = min(abs(match.start() - position) for position in lead_positions)
        window = text[max(0, match.start() - 180) : match.end() + 180].lower()
        context_score = sum(
            8.0
            for keyword in ("average", "overall", "industry", "semiconductor", "chip")
            if keyword in window
        )
        return context_score - distance / 10.0, -match.start()

    return max(matches, key=score)


def _extract_report_month(
    text: str,
    value_position: int,
    published_date: date | None,
    *,
    infer_report_month: bool,
) -> tuple[str | None, bool]:
    candidates = list(_MONTH_PATTERN.finditer(text))
    if candidates:
        candidate = min(candidates, key=lambda match: abs(match.start() - value_position))
        month = _MONTH_NAMES[candidate.group(1).lower()]
        year = int(candidate.group(2)) if candidate.group(2) else None
        if year is None and published_date is not None:
            year = published_date.year
            if month > published_date.month:
                year -= 1
        if year is not None:
            return f"{year:04d}-{month:02d}", False

    if not infer_report_month or published_date is None:
        return None, False
    year = published_date.year
    month = published_date.month - 1
    if month == 0:
        year -= 1
        month = 12
    return f"{year:04d}-{month:02d}", True


def archive_susquehanna_raw_snapshot(
    raw_dir: Path,
    record: ChipLeadTimeRecord,
    source_content: bytes,
    *,
    source_kind: str = "article_html",
    report_month_inferred: bool = False,
) -> tuple[Path, Path]:
    """归档 Susquehanna 报道原文和结构化 RAW 元数据。"""
    if record.release_date is None:
        raise ValueError("Susquehanna 交期 RAW 快照缺少公开发布日期，拒绝归档")
    if not source_content:
        raise ValueError("Susquehanna 交期 RAW 快照内容为空，拒绝归档")

    content_hash = raw_content_sha256(source_content)
    suffix = (
        ".html"
        if source_kind == "article_html"
        else ".json"
        if source_kind.endswith("json")
        else ".txt"
    )
    source_path = save_raw_snapshot(
        source_name="lead_time",
        snapshot_filename=f"susquehanna_{record.report_month}_{content_hash[:12]}{suffix}",
        content=source_content,
        base_dir=raw_dir,
    )
    metadata = {
        "report_month": record.report_month,
        "trade_date": record.trade_date.isoformat(),
        "avg_lead_time_weeks": record.avg_lead_time_weeks,
        "category_averages": {},
        "lead_time_raw": record.lead_time_raw,
        "source": record.source,
        "source_url": record.source_url,
        "release_date": record.release_date.isoformat(),
        "data_status": record.data_status,
        "collected_at": record.collected_at,
        "raw_content_sha256": content_hash,
        "raw_snapshot_path": raw_snapshot_path_value(source_path, raw_dir),
        "source_kind": source_kind,
        "report_month_inferred": report_month_inferred,
    }
    metadata_path = save_raw_snapshot(
        source_name="lead_time",
        snapshot_filename=f"chip_lead_time_{record.report_month}.json",
        content=metadata,
        base_dir=raw_dir,
    )
    return source_path, metadata_path
