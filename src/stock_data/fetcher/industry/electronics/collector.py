"""消费电子终端 (智能手机 / PC / 创新渗透率) 季度出货采集器 (ConsumerElectronicsCollector)。"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.models import ConsumerElectronicsRecord

logger = logging.getLogger(__name__)

ELECTRONICS_CSV_FIELDNAMES = [
    "report_quarter",
    "trade_date",
    "global_smartphone_shipments_million",
    "china_smartphone_shipments_million",
    "global_pc_shipments_million",
    "ai_phone_penetration_rate",
    "ai_pc_penetration_rate",
    "smartphone_yoy_growth",
    "pc_yoy_growth",
    "apple_shipments_million",
    "transsion_shipments_million",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


def save_electronics_raw_csv(
    file_path: Path | str, records: list[ConsumerElectronicsRecord]
) -> None:
    """持久化标准化记录至 RAW CSV 快照。"""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ELECTRONICS_CSV_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "report_quarter": r.report_quarter,
                    "trade_date": r.trade_date.isoformat(),
                    "global_smartphone_shipments_million": r.global_smartphone_shipments_million
                    if r.global_smartphone_shipments_million is not None
                    else "",
                    "china_smartphone_shipments_million": r.china_smartphone_shipments_million
                    if r.china_smartphone_shipments_million is not None
                    else "",
                    "global_pc_shipments_million": r.global_pc_shipments_million
                    if r.global_pc_shipments_million is not None
                    else "",
                    "ai_phone_penetration_rate": r.ai_phone_penetration_rate
                    if r.ai_phone_penetration_rate is not None
                    else "",
                    "ai_pc_penetration_rate": r.ai_pc_penetration_rate
                    if r.ai_pc_penetration_rate is not None
                    else "",
                    "smartphone_yoy_growth": r.smartphone_yoy_growth
                    if r.smartphone_yoy_growth is not None
                    else "",
                    "pc_yoy_growth": r.pc_yoy_growth if r.pc_yoy_growth is not None else "",
                    "apple_shipments_million": r.apple_shipments_million
                    if r.apple_shipments_million is not None
                    else "",
                    "transsion_shipments_million": r.transsion_shipments_million
                    if r.transsion_shipments_million is not None
                    else "",
                    "unit": r.unit or "million_units/percent",
                    "source": r.source or "IDC/Canalys",
                    "source_url": r.source_url or "https://www.idc.com/",
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status or "actual",
                    "collected_at": r.collected_at or now_utc_iso(),
                }
            )


def load_electronics_raw_csv(
    file_path: Path | str,
) -> list[ConsumerElectronicsRecord]:
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

    records: list[ConsumerElectronicsRecord] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            q_str = row["report_quarter"].strip()
            t_date = date.fromisoformat(row["trade_date"].strip())
            rel_d = None
            if row.get("release_date"):
                try:
                    rel_d = date.fromisoformat(row["release_date"].strip())
                except ValueError:
                    pass

            records.append(
                ConsumerElectronicsRecord(
                    report_quarter=q_str,
                    trade_date=t_date,
                    global_smartphone_shipments_million=_safe_float(
                        row.get("global_smartphone_shipments_million")
                    ),
                    china_smartphone_shipments_million=_safe_float(
                        row.get("china_smartphone_shipments_million")
                    ),
                    global_pc_shipments_million=_safe_float(row.get("global_pc_shipments_million")),
                    ai_phone_penetration_rate=_safe_float(row.get("ai_phone_penetration_rate")),
                    ai_pc_penetration_rate=_safe_float(row.get("ai_pc_penetration_rate")),
                    smartphone_yoy_growth=_safe_float(row.get("smartphone_yoy_growth")),
                    pc_yoy_growth=_safe_float(row.get("pc_yoy_growth")),
                    apple_shipments_million=_safe_float(row.get("apple_shipments_million")),
                    transsion_shipments_million=_safe_float(row.get("transsion_shipments_million")),
                    unit=row.get("unit") or "million_units/percent",
                    source=row.get("source") or "IDC/Canalys",
                    source_url=row.get("source_url") or "",
                    release_date=rel_d,
                    data_status=row.get("data_status") or "actual",
                    collected_at=row.get("collected_at") or now_utc_iso(),
                )
            )

    records.sort(key=lambda r: r.trade_date)
    return records


class ConsumerElectronicsCollector:
    """消费电子终端季度出货与渗透率采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.elec_raw_dir = self.raw_dir / "electronics"

    def collect(self) -> list[ConsumerElectronicsRecord]:
        """执行消费电子数据采集: 本地真实快照优先 -> 派生计算落盘。"""
        self.elec_raw_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.elec_raw_dir / "electronics_shipments_quarterly.csv"

        records_map: dict[str, ConsumerElectronicsRecord] = {}
        if csv_file.exists():
            for rec in self.load_from_raw_csv(csv_file):
                records_map[rec.report_quarter] = rec

        if not records_map:
            logger.warning("未找到本地消费电子季度出货快照")
            return []

        records = sorted(records_map.values(), key=lambda r: r.trade_date)
        self.save_to_raw_csv(csv_file, records)
        return records

    def save_to_raw_csv(
        self, file_path: Path | str, records: list[ConsumerElectronicsRecord]
    ) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        save_electronics_raw_csv(file_path, records)

    def load_from_raw_csv(self, file_path: Path | str) -> list[ConsumerElectronicsRecord]:
        """从 RAW CSV 文件读取并标准化记录。"""
        return load_electronics_raw_csv(file_path)
