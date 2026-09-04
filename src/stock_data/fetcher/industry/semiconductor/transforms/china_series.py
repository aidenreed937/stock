"""中国半导体月度区域增速事实整理。

只整理 SIA 新闻文本中直接披露的 China 月度增速；公开月报未披露月度绝对销售额时
保留为空，不用年度锚点摊分、MoM 链式推算或 YoY 校准回填。
"""

from __future__ import annotations

import calendar
import gzip
import logging
import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.semiconductor.parsers import (
    parse_sia_china_and_date,
)

logger = logging.getLogger(__name__)

CHINA_SERIES_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "release_date": pl.Date,
    "china_sales_usd": pl.Float64,
    "china_yoy_growth": pl.Float64,
    "china_mom_growth": pl.Float64,
    "anchor_flag": pl.Boolean,
    "calc_flag": pl.String,
    "yoy_check_diff": pl.Float64,
    "check_status": pl.String,
    "source_url": pl.String,
}

_YEAR_ABS_PATTERNS = (
    r"China[^.]{0,160}?(?:sales|revenue|market)[^.]{0,80}?\$?([\d.]+)\s*billion",
    r"China[^.]{0,120}?(?:were|totaled|was|reached)[^.]{0,60}?\$?([\d.]+)\s*billion",
)


def _extract_year_anchor(text: str, year: int) -> float | None:
    """从 SIA 新闻文本中提取指定年份的中国半导体年度销售额 (十亿美元)。"""
    for pat in _YEAR_ABS_PATTERNS:
        for match in re.finditer(pat, text, re.IGNORECASE):
            val = float(match.group(1))
            if 30.0 <= val <= 400.0:
                return round(val, 1)
    return None


def parse_sia_china_enriched(
    html_text: str,
    source_url: str,
) -> dict[str, object] | None:
    """增强版 SIA China 解析: 月度 YoY/MoM/绝对值 + 年度锚点元数据。"""
    base = parse_sia_china_and_date(html_text, source_url)
    if base is None:
        return None
    out: dict[str, object] = dict(base)

    rm = str(base["report_month"])
    y = int(rm[:4])
    for cand_year in (y, y - 1, y + 1):
        val = _extract_year_anchor(html_text, cand_year)
        if val is not None:
            out["anchor_year"] = cand_year
            out["china_year_sales_usd"] = val
            break
    else:
        out["anchor_year"] = None
        out["china_year_sales_usd"] = None
    return out


def build_china_series(
    records: Sequence[dict[str, object]],
    start_month: str = "2012-01",
    end_month: str | None = None,
) -> pl.DataFrame:
    """从 SIA 解析记录整理直接披露的 China 月度事实。"""
    rows_by_month: dict[str, dict[str, object]] = {}
    for record in records:
        report_month = str(record.get("report_month") or "")
        if not _month_in_range(report_month, start_month, end_month):
            continue
        if (
            record.get("china_sales_usd") is None
            and record.get("china_yoy_growth") is None
            and record.get("china_mom_growth") is None
        ):
            continue
        existing = rows_by_month.get(report_month)
        if existing is None or _disclosed_field_count(record) > _disclosed_field_count(existing):
            rows_by_month[report_month] = dict(record)

    if not rows_by_month:
        return pl.DataFrame(schema=CHINA_SERIES_SCHEMA)

    rows: list[dict[str, object]] = []
    for report_month, record in rows_by_month.items():
        year, month = int(report_month[:4]), int(report_month[5:7])
        rows.append(
            {
                "report_month": report_month,
                "trade_date": date(year, month, calendar.monthrange(year, month)[1]),
                "release_date": record.get("release_date"),
                "china_sales_usd": record.get("china_sales_usd"),
                "china_yoy_growth": record.get("china_yoy_growth"),
                "china_mom_growth": record.get("china_mom_growth"),
                "anchor_flag": False,
                "calc_flag": "source_reported",
                "yoy_check_diff": None,
                "check_status": "source_reported",
                "source_url": record.get("source_url") or "",
            }
        )
    return pl.DataFrame(rows, schema=CHINA_SERIES_SCHEMA).sort("report_month")


def save_china_series(df: pl.DataFrame, path: str | Path) -> int:
    """落盘 SIA China 直接披露序列到 curated 表。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(p)
    logger.info("China 直接披露序列落盘成功 [%s]: 共 %d 行", p.name, df.height)
    return df.height


def parse_sia_raw_dir(raw_dir: str | Path) -> list[dict[str, object]]:
    """扫描 SIA raw 新闻目录，解析全部 China 信息。"""
    records: list[dict[str, object]] = []
    files = sorted(Path(raw_dir).glob("*.html.gz"))
    for file_path in files:
        if file_path.name == "latest_news_list.html.gz":
            continue
        try:
            with gzip.open(file_path, "rt", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except Exception:
            continue
        parsed = parse_sia_china_enriched(text, str(file_path))
        if parsed:
            records.append(parsed)
    logger.info("SIA raw 解析完成: %d 篇新闻 -> %d 条 China 记录", len(files), len(records))
    return records


def _disclosed_field_count(record: dict[str, object]) -> int:
    keys = ("china_sales_usd", "china_yoy_growth", "china_mom_growth")
    return sum(record.get(key) is not None for key in keys)


def _month_in_range(report_month: str, start_month: str, end_month: str | None) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}", report_month):
        return False
    if report_month < start_month:
        return False
    return end_month is None or report_month <= end_month
