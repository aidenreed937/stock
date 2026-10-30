"""有色金属 RAW CSV 快照读写。"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.metals.models import NonFerrousMetalsRecord

logger = logging.getLogger(__name__)

METALS_CSV_FIELDNAMES = [
    "report_date",
    "trade_date",
    "lithium_carbonate_price",
    "shfe_copper_price",
    "shfe_aluminum_price",
    "sge_gold_price",
    "copper_inventory_ton",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


def save_metals_raw_csv(records: list[NonFerrousMetalsRecord], path: Path) -> None:
    """持久化 RAW 快照 CSV。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=METALS_CSV_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "report_date": r.report_date,
                    "trade_date": r.trade_date.isoformat(),
                    "lithium_carbonate_price": r.lithium_carbonate_price
                    if r.lithium_carbonate_price is not None
                    else "",
                    "shfe_copper_price": r.shfe_copper_price
                    if r.shfe_copper_price is not None
                    else "",
                    "shfe_aluminum_price": r.shfe_aluminum_price
                    if r.shfe_aluminum_price is not None
                    else "",
                    "sge_gold_price": r.sge_gold_price if r.sge_gold_price is not None else "",
                    "copper_inventory_ton": r.copper_inventory_ton
                    if r.copper_inventory_ton is not None
                    else "",
                    "unit": r.unit,
                    "source": r.source,
                    "source_url": r.source_url,
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status,
                    "collected_at": r.collected_at,
                }
            )
    logger.info("已保存真实有色大宗 RAW 快照: %s (共 %d 行)", path, len(records))


def load_metals_raw_csv(file_path: Path | str) -> list[NonFerrousMetalsRecord]:
    """从 RAW 快照 CSV 中读取并标准化。"""
    p = Path(file_path)
    if not p.exists():
        return []

    records: list[NonFerrousMetalsRecord] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            r_date_str = row["report_date"].strip()
            t_date = date.fromisoformat(
                row["trade_date"].strip() if row.get("trade_date") else r_date_str
            )
            records.append(
                NonFerrousMetalsRecord(
                    report_date=r_date_str,
                    trade_date=t_date,
                    lithium_carbonate_price=float(row["lithium_carbonate_price"])
                    if row.get("lithium_carbonate_price")
                    else None,
                    shfe_copper_price=float(row["shfe_copper_price"])
                    if row.get("shfe_copper_price")
                    else None,
                    shfe_aluminum_price=float(row["shfe_aluminum_price"])
                    if row.get("shfe_aluminum_price")
                    else None,
                    sge_gold_price=float(row["sge_gold_price"])
                    if row.get("sge_gold_price")
                    else None,
                    copper_inventory_ton=float(row["copper_inventory_ton"])
                    if row.get("copper_inventory_ton")
                    else None,
                    unit=row.get("unit") or "mixed",
                    source=row.get("source") or "AkShare",
                    source_url=row.get("source_url") or "",
                    release_date=date.fromisoformat(row["release_date"].strip())
                    if row.get("release_date")
                    else t_date,
                    data_status=row.get("data_status") or "actual",
                    collected_at=row.get("collected_at") or now_utc_iso(),
                )
            )
    records.sort(key=lambda r: r.trade_date)
    return records


__all__ = ["METALS_CSV_FIELDNAMES", "load_metals_raw_csv", "save_metals_raw_csv"]
