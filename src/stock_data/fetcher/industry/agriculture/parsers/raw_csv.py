"""农业生猪 RAW CSV 快照读写。"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.agriculture.models import AgriculturePorkRecord
from stock_data.fetcher.industry.common import get_month_end_date, now_utc_iso, parse_month_string

PORK_CSV_FIELDNAMES = [
    "report_month",
    "trade_date",
    "sow_stock_million_heads",
    "sow_stock_yoy",
    "sow_stock_mom",
    "pig_price_cny_per_kg",
    "pig_price_yoy",
    "hog_to_grain_ratio",
    "pig_farming_profit_cny_head",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


def save_pork_raw_csv(file_path: Path | str, records: list[AgriculturePorkRecord]) -> None:
    """持久化标准化记录至 RAW CSV 快照。"""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PORK_CSV_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "report_month": r.report_month,
                    "trade_date": r.trade_date.isoformat(),
                    "sow_stock_million_heads": r.sow_stock_million_heads
                    if r.sow_stock_million_heads is not None
                    else "",
                    "sow_stock_yoy": r.sow_stock_yoy if r.sow_stock_yoy is not None else "",
                    "sow_stock_mom": r.sow_stock_mom if r.sow_stock_mom is not None else "",
                    "pig_price_cny_per_kg": r.pig_price_cny_per_kg
                    if r.pig_price_cny_per_kg is not None
                    else "",
                    "pig_price_yoy": r.pig_price_yoy if r.pig_price_yoy is not None else "",
                    "hog_to_grain_ratio": r.hog_to_grain_ratio
                    if r.hog_to_grain_ratio is not None
                    else "",
                    "pig_farming_profit_cny_head": r.pig_farming_profit_cny_head
                    if r.pig_farming_profit_cny_head is not None
                    else "",
                    "unit": r.unit or "million_heads/cny_per_kg",
                    "source": r.source or "MARA/NBS",
                    "source_url": r.source_url or "http://www.moa.gov.cn/",
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status or "actual",
                    "collected_at": r.collected_at or now_utc_iso(),
                }
            )


def load_pork_raw_csv(file_path: Path | str) -> list[AgriculturePorkRecord]:
    """从 RAW CSV 文件读取并标准化记录。"""
    p = Path(file_path)
    if not p.exists():
        return []

    records: list[AgriculturePorkRecord] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            month_str = row["report_month"].strip()
            yr, mo = parse_month_string(month_str)
            t_date = get_month_end_date(yr, mo)
            rel_d = None
            if row.get("release_date"):
                try:
                    rel_d = date.fromisoformat(row["release_date"].strip())
                except ValueError:
                    pass

            records.append(
                AgriculturePorkRecord(
                    report_month=month_str,
                    trade_date=t_date,
                    sow_stock_million_heads=_safe_float(row.get("sow_stock_million_heads")),
                    sow_stock_yoy=_safe_float(row.get("sow_stock_yoy")),
                    sow_stock_mom=_safe_float(row.get("sow_stock_mom")),
                    pig_price_cny_per_kg=_safe_float(row.get("pig_price_cny_per_kg")),
                    pig_price_yoy=_safe_float(row.get("pig_price_yoy")),
                    hog_to_grain_ratio=_safe_float(row.get("hog_to_grain_ratio")),
                    pig_farming_profit_cny_head=_safe_float(row.get("pig_farming_profit_cny_head")),
                    unit=row.get("unit") or "million_heads/cny_per_kg",
                    source=row.get("source") or "MARA/NBS",
                    source_url=row.get("source_url") or "",
                    release_date=rel_d,
                    data_status=row.get("data_status") or "actual",
                    collected_at=row.get("collected_at") or now_utc_iso(),
                )
            )

    records.sort(key=lambda r: r.trade_date)
    return records


def _safe_float(val: str | None) -> float | None:
    if not val or not val.strip():
        return None
    try:
        return float(val.strip())
    except (ValueError, TypeError):
        return None


__all__ = ["PORK_CSV_FIELDNAMES", "load_pork_raw_csv", "save_pork_raw_csv"]
