"""白酒批价 RAW CSV 快照读写。"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.consumer.models import LiquorWholesaleRecord

LIQUOR_PRICE_FIELDNAMES = [
    "report_date",
    "trade_date",
    "moutai_loose_price_cny",
    "moutai_boxed_price_cny",
    "wuliangye_puwu_price_cny",
    "guojiao1573_price_cny",
    "moutai_loose_price_yoy",
    "moutai_loose_price_mom",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


def save_liquor_raw_csv(file_path: Path | str, records: list[LiquorWholesaleRecord]) -> None:
    """持久化标准化记录至 RAW CSV 快照。"""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LIQUOR_PRICE_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "report_date": r.report_date,
                    "trade_date": r.trade_date.isoformat(),
                    "moutai_loose_price_cny": r.moutai_loose_price_cny
                    if r.moutai_loose_price_cny is not None
                    else "",
                    "moutai_boxed_price_cny": r.moutai_boxed_price_cny
                    if r.moutai_boxed_price_cny is not None
                    else "",
                    "wuliangye_puwu_price_cny": r.wuliangye_puwu_price_cny
                    if r.wuliangye_puwu_price_cny is not None
                    else "",
                    "guojiao1573_price_cny": r.guojiao1573_price_cny
                    if r.guojiao1573_price_cny is not None
                    else "",
                    "moutai_loose_price_yoy": r.moutai_loose_price_yoy
                    if r.moutai_loose_price_yoy is not None
                    else "",
                    "moutai_loose_price_mom": r.moutai_loose_price_mom
                    if r.moutai_loose_price_mom is not None
                    else "",
                    "unit": r.unit or "cny_per_bottle",
                    "source": r.source or "TodayLiquorPrice",
                    "source_url": r.source_url or "",
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status or "actual",
                    "collected_at": r.collected_at or now_utc_iso(),
                }
            )


def load_liquor_raw_csv(file_path: Path | str) -> list[LiquorWholesaleRecord]:
    """从 RAW CSV 文件读取并标准化记录。"""
    p = Path(file_path)
    if not p.exists():
        return []

    records: list[LiquorWholesaleRecord] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rep_date_str = row["report_date"].strip()
            t_date = date.fromisoformat(row["trade_date"].strip() or rep_date_str)
            rel_d = None
            if row.get("release_date"):
                try:
                    rel_d = date.fromisoformat(row["release_date"].strip())
                except ValueError:
                    pass

            records.append(
                LiquorWholesaleRecord(
                    report_date=rep_date_str,
                    trade_date=t_date,
                    moutai_loose_price_cny=_safe_float(row.get("moutai_loose_price_cny")),
                    moutai_boxed_price_cny=_safe_float(row.get("moutai_boxed_price_cny")),
                    wuliangye_puwu_price_cny=_safe_float(row.get("wuliangye_puwu_price_cny")),
                    guojiao1573_price_cny=_safe_float(row.get("guojiao1573_price_cny")),
                    moutai_loose_price_yoy=_safe_float(row.get("moutai_loose_price_yoy")),
                    moutai_loose_price_mom=_safe_float(row.get("moutai_loose_price_mom")),
                    unit=row.get("unit") or "cny_per_bottle",
                    source=row.get("source") or "TodayLiquorPrice",
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


__all__ = ["LIQUOR_PRICE_FIELDNAMES", "load_liquor_raw_csv", "save_liquor_raw_csv"]
