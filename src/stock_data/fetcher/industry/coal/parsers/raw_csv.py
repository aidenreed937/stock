"""煤炭 RAW CSV 快照读写。"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.coal.models import CoalMarketRecord
from stock_data.fetcher.industry.common import now_utc_iso

COAL_CSV_FIELDNAMES = [
    "report_date",
    "trade_date",
    "q5500_fob_price_cny",
    "coking_coal_price_cny",
    "power_plant_inventory_million_ton",
    "power_plant_daily_burn_ten_thousand_ton",
    "power_plant_available_days",
    "qinhuangdao_inventory_million_ton",
    "q5500_price_yoy",
    "q5500_price_mom",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


def save_coal_raw_csv(file_path: Path | str, records: list[CoalMarketRecord]) -> None:
    """持久化标准化记录至 RAW CSV 快照。"""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COAL_CSV_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "report_date": r.report_date,
                    "trade_date": r.trade_date.isoformat(),
                    "q5500_fob_price_cny": r.q5500_fob_price_cny
                    if r.q5500_fob_price_cny is not None
                    else "",
                    "coking_coal_price_cny": r.coking_coal_price_cny
                    if r.coking_coal_price_cny is not None
                    else "",
                    "power_plant_inventory_million_ton": r.power_plant_inventory_million_ton
                    if r.power_plant_inventory_million_ton is not None
                    else "",
                    "power_plant_daily_burn_ten_thousand_ton": r.power_plant_daily_burn_ten_thousand_ton
                    if r.power_plant_daily_burn_ten_thousand_ton is not None
                    else "",
                    "power_plant_available_days": r.power_plant_available_days
                    if r.power_plant_available_days is not None
                    else "",
                    "qinhuangdao_inventory_million_ton": r.qinhuangdao_inventory_million_ton
                    if r.qinhuangdao_inventory_million_ton is not None
                    else "",
                    "q5500_price_yoy": r.q5500_price_yoy if r.q5500_price_yoy is not None else "",
                    "q5500_price_mom": r.q5500_price_mom if r.q5500_price_mom is not None else "",
                    "unit": r.unit or "cny_per_ton/million_tons/days",
                    "source": r.source or "CCTD/Sxcoal",
                    "source_url": r.source_url or "https://www.cctd.com.cn/",
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status or "actual",
                    "collected_at": r.collected_at or now_utc_iso(),
                }
            )


def load_coal_raw_csv(file_path: Path | str) -> list[CoalMarketRecord]:
    """从 RAW CSV 文件读取并标准化记录。"""
    p = Path(file_path)
    if not p.exists():
        return []

    records: list[CoalMarketRecord] = []
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
                CoalMarketRecord(
                    report_date=rep_date_str,
                    trade_date=t_date,
                    q5500_fob_price_cny=_safe_float(row.get("q5500_fob_price_cny")),
                    coking_coal_price_cny=_safe_float(row.get("coking_coal_price_cny")),
                    power_plant_inventory_million_ton=_safe_float(
                        row.get("power_plant_inventory_million_ton")
                    ),
                    power_plant_daily_burn_ten_thousand_ton=_safe_float(
                        row.get("power_plant_daily_burn_ten_thousand_ton")
                    ),
                    power_plant_available_days=_safe_float(row.get("power_plant_available_days")),
                    qinhuangdao_inventory_million_ton=_safe_float(
                        row.get("qinhuangdao_inventory_million_ton")
                    ),
                    q5500_price_yoy=_safe_float(row.get("q5500_price_yoy")),
                    q5500_price_mom=_safe_float(row.get("q5500_price_mom")),
                    unit=row.get("unit") or "cny_per_ton/million_tons/days",
                    source=row.get("source") or "CCTD/Sxcoal",
                    source_url=row.get("source_url") or "https://www.cctd.com.cn/",
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


__all__ = ["COAL_CSV_FIELDNAMES", "load_coal_raw_csv", "save_coal_raw_csv"]
