"""消费电子终端 (智能手机 / PC / 创新渗透率) 季度出货采集器 (ConsumerElectronicsCollector)。"""

from __future__ import annotations

import calendar
import csv
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.electronics.crawler import ConsumerElectronicsCrawler
from stock_data.fetcher.industry.electronics.models import ConsumerElectronicsRecord

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
        self.crawler = ConsumerElectronicsCrawler(raw_dir=self.raw_dir)

    def collect(self, force: bool = False) -> list[ConsumerElectronicsRecord]:
        """执行消费电子数据采集: 抓取最新 IDC 季度数据并落盘，以最新采集为准。"""
        self.elec_raw_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.elec_raw_dir / "electronics_shipments_quarterly.csv"

        # 在线/本地快照抓取最新 IDC 季度 PR
        live_data = self.crawler.fetch_latest_quarter(force=force)
        if not live_data or not live_data.get("report_quarter"):
            logger.warning("在线抓取 IDC 季度出货数据失败")
            return []

        q_key = str(live_data["report_quarter"])
        year = int(q_key[:4])
        q_num = int(q_key[-1])
        t_date = date(year, q_num * 3, calendar.monthrange(year, q_num * 3)[1])
        rec_live = ConsumerElectronicsRecord(
            report_quarter=q_key,
            trade_date=t_date,
            global_smartphone_shipments_million=live_data.get(
                "global_smartphone_shipments_million"
            ),
            china_smartphone_shipments_million=live_data.get("china_smartphone_shipments_million"),
            global_pc_shipments_million=live_data.get("global_pc_shipments_million"),
            ai_phone_penetration_rate=None,
            ai_pc_penetration_rate=None,
            smartphone_yoy_growth=live_data.get("smartphone_yoy_growth"),
            pc_yoy_growth=live_data.get("pc_yoy_growth"),
            apple_shipments_million=live_data.get("apple_shipments_million"),
            transsion_shipments_million=live_data.get("transsion_shipments_million"),
            unit="million_units/percent",
            source=live_data.get("source") or "IDC",
            source_url=live_data.get("source_url") or "https://www.idc.com/",
            release_date=date.fromisoformat(live_data["release_date"])
            if live_data.get("release_date")
            else None,
            data_status=live_data.get("data_status") or "actual",
            collected_at=live_data.get("collected_at") or now_utc_iso(),
        )

        records = [rec_live]
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
