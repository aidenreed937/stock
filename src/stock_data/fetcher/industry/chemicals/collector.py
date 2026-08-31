"""基础化工大宗品 (MDI/制冷剂/钛白粉) 供需开工率与价差采集器 (ChemicalsCollector)。"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
)
from stock_data.fetcher.industry.models import ChemicalMarketRecord

logger = logging.getLogger(__name__)

CHEMICALS_CSV_FIELDNAMES = [
    "report_month",
    "trade_date",
    "mdi_operating_rate",
    "tio2_operating_rate",
    "refrigerant_r32_operating_rate",
    "mdi_gross_spread_cny",
    "tio2_spread_cny",
    "refrigerant_r32_price_cny",
    "chemical_inventory_days",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


def save_chemicals_raw_csv(file_path: Path | str, records: list[ChemicalMarketRecord]) -> None:
    """持久化标准化记录至 RAW CSV 快照。"""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CHEMICALS_CSV_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "report_month": r.report_month,
                    "trade_date": r.trade_date.isoformat(),
                    "mdi_operating_rate": r.mdi_operating_rate
                    if r.mdi_operating_rate is not None
                    else "",
                    "tio2_operating_rate": r.tio2_operating_rate
                    if r.tio2_operating_rate is not None
                    else "",
                    "refrigerant_r32_operating_rate": r.refrigerant_r32_operating_rate
                    if r.refrigerant_r32_operating_rate is not None
                    else "",
                    "mdi_gross_spread_cny": r.mdi_gross_spread_cny
                    if r.mdi_gross_spread_cny is not None
                    else "",
                    "tio2_spread_cny": r.tio2_spread_cny if r.tio2_spread_cny is not None else "",
                    "refrigerant_r32_price_cny": r.refrigerant_r32_price_cny
                    if r.refrigerant_r32_price_cny is not None
                    else "",
                    "chemical_inventory_days": r.chemical_inventory_days
                    if r.chemical_inventory_days is not None
                    else "",
                    "unit": r.unit or "percent/cny_per_ton",
                    "source": r.source or "Baichuan/Suntec",
                    "source_url": r.source_url or "https://www.suntec.com.cn/",
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status or "actual",
                    "collected_at": r.collected_at or now_utc_iso(),
                }
            )


def load_chemicals_raw_csv(file_path: Path | str) -> list[ChemicalMarketRecord]:
    """从 RAW CSV 文件读取并标准化记录。"""
    p = Path(file_path)
    if not p.exists():
        return []

    def _safe_float(val: str | None) -> float | None:
        if not val or not val.strip():
            return None
        try:
            return float(val.strip())
        except (ValueError, TypeError):
            return None

    records: list[ChemicalMarketRecord] = []
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
                ChemicalMarketRecord(
                    report_month=month_str,
                    trade_date=t_date,
                    mdi_operating_rate=_safe_float(row.get("mdi_operating_rate")),
                    tio2_operating_rate=_safe_float(row.get("tio2_operating_rate")),
                    refrigerant_r32_operating_rate=_safe_float(
                        row.get("refrigerant_r32_operating_rate")
                    ),
                    mdi_gross_spread_cny=_safe_float(row.get("mdi_gross_spread_cny")),
                    tio2_spread_cny=_safe_float(row.get("tio2_spread_cny")),
                    refrigerant_r32_price_cny=_safe_float(row.get("refrigerant_r32_price_cny")),
                    chemical_inventory_days=_safe_float(row.get("chemical_inventory_days")),
                    unit=row.get("unit") or "percent/cny_per_ton",
                    source=row.get("source") or "Baichuan/Suntec",
                    source_url=row.get("source_url") or "",
                    release_date=rel_d,
                    data_status=row.get("data_status") or "actual",
                    collected_at=row.get("collected_at") or now_utc_iso(),
                )
            )

    records.sort(key=lambda r: r.trade_date)
    return records


class ChemicalsCollector:
    """基础化工重点大宗品供需开工率与价差采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.chem_raw_dir = self.raw_dir / "chemicals"

    def collect(self) -> list[ChemicalMarketRecord]:
        """执行基础化工数据采集: 本地真实快照优先 -> 派生计算落盘。"""
        self.chem_raw_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.chem_raw_dir / "chemical_operating_spreads.csv"

        records_map: dict[str, ChemicalMarketRecord] = {}
        if csv_file.exists():
            for rec in self.load_from_raw_csv(csv_file):
                records_map[rec.report_month] = rec

        if not records_map:
            logger.warning("未找到本地基础化工月度快照")
            return []

        records = sorted(records_map.values(), key=lambda r: r.trade_date)
        self.save_to_raw_csv(csv_file, records)
        return records

    def save_to_raw_csv(self, file_path: Path | str, records: list[ChemicalMarketRecord]) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        save_chemicals_raw_csv(file_path, records)

    def load_from_raw_csv(self, file_path: Path | str) -> list[ChemicalMarketRecord]:
        """从 RAW CSV 文件读取并标准化记录。"""
        return load_chemicals_raw_csv(file_path)
