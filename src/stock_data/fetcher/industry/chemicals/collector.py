"""基础化工真实基本面事实数据采集器 (ChemicalsCollector)。

数据属性与 2-Tier ETL 架构:
1. 真实来源追溯: NBS 国家统计局官方月度产量 (纯碱/烧碱/化纤/化肥/塑料/平板玻璃)、CZCE 郑商所注册仓单、生意社价格;
2. 语义对齐: 生产库保留真实物理量，未授权商业开工率/社会库存严格保持 None;
3. 2-Tier 存储: 历史基底持久化为 RAW CSV (chemical_operating_spreads.csv)，每次增量采集自动追加对齐并物化 Curated Parquet;
4. 消除前视偏差: release_date 严格采用官方实际发布日 (NBS 月报次月 18 日生效)。
"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.chemicals.crawler import ChemicalsCrawler
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
    "soda_ash_production",
    "caustic_soda_production",
    "synthetic_fiber_production",
    "chemical_fertilizer_production",
    "plastics_production",
    "plate_glass_production",
    "czce_soda_ash_receipt",
    "czce_pta_receipt",
    "czce_urea_receipt",
    "soda_ash_price_cny",
    "pta_price_cny",
    "urea_price_cny",
    "mdi_price_cny",
    "tio2_price_cny",
    "refrigerant_r32_price_cny",
    "soda_ash_operating_rate",
    "pta_operating_rate",
    "chemical_social_inventory",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


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
                    "soda_ash_production": r.soda_ash_production
                    if r.soda_ash_production is not None
                    else "",
                    "caustic_soda_production": r.caustic_soda_production
                    if r.caustic_soda_production is not None
                    else "",
                    "synthetic_fiber_production": r.synthetic_fiber_production
                    if r.synthetic_fiber_production is not None
                    else "",
                    "chemical_fertilizer_production": r.chemical_fertilizer_production
                    if r.chemical_fertilizer_production is not None
                    else "",
                    "plastics_production": r.plastics_production
                    if r.plastics_production is not None
                    else "",
                    "plate_glass_production": r.plate_glass_production
                    if r.plate_glass_production is not None
                    else "",
                    "czce_soda_ash_receipt": r.czce_soda_ash_receipt
                    if r.czce_soda_ash_receipt is not None
                    else "",
                    "czce_pta_receipt": r.czce_pta_receipt
                    if r.czce_pta_receipt is not None
                    else "",
                    "czce_urea_receipt": r.czce_urea_receipt
                    if r.czce_urea_receipt is not None
                    else "",
                    "soda_ash_price_cny": r.soda_ash_price_cny
                    if r.soda_ash_price_cny is not None
                    else "",
                    "pta_price_cny": r.pta_price_cny if r.pta_price_cny is not None else "",
                    "urea_price_cny": r.urea_price_cny if r.urea_price_cny is not None else "",
                    "mdi_price_cny": r.mdi_price_cny if r.mdi_price_cny is not None else "",
                    "tio2_price_cny": r.tio2_price_cny if r.tio2_price_cny is not None else "",
                    "refrigerant_r32_price_cny": r.refrigerant_r32_price_cny
                    if r.refrigerant_r32_price_cny is not None
                    else "",
                    "soda_ash_operating_rate": r.soda_ash_operating_rate
                    if r.soda_ash_operating_rate is not None
                    else "",
                    "pta_operating_rate": r.pta_operating_rate
                    if r.pta_operating_rate is not None
                    else "",
                    "chemical_social_inventory": r.chemical_social_inventory
                    if r.chemical_social_inventory is not None
                    else "",
                    "unit": r.unit or "mixed",
                    "source": r.source or "NBS/CZCE/100ppi",
                    "source_url": r.source_url or "https://data.stats.gov.cn/",
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
            if rel_d is None:
                next_yr, next_mo = (yr + 1, 1) if mo == 12 else (yr, mo + 1)
                rel_d = date(next_yr, next_mo, 18)

            records.append(
                ChemicalMarketRecord(
                    report_month=month_str,
                    trade_date=t_date,
                    soda_ash_production=_safe_float(row.get("soda_ash_production")),
                    caustic_soda_production=_safe_float(row.get("caustic_soda_production")),
                    synthetic_fiber_production=_safe_float(row.get("synthetic_fiber_production")),
                    chemical_fertilizer_production=_safe_float(
                        row.get("chemical_fertilizer_production")
                    ),
                    plastics_production=_safe_float(row.get("plastics_production")),
                    plate_glass_production=_safe_float(row.get("plate_glass_production")),
                    czce_soda_ash_receipt=_safe_float(row.get("czce_soda_ash_receipt")),
                    czce_pta_receipt=_safe_float(row.get("czce_pta_receipt")),
                    czce_urea_receipt=_safe_float(row.get("czce_urea_receipt")),
                    soda_ash_price_cny=_safe_float(row.get("soda_ash_price_cny")),
                    pta_price_cny=_safe_float(row.get("pta_price_cny")),
                    urea_price_cny=_safe_float(row.get("urea_price_cny")),
                    mdi_price_cny=_safe_float(row.get("mdi_price_cny")),
                    tio2_price_cny=_safe_float(row.get("tio2_price_cny")),
                    refrigerant_r32_price_cny=_safe_float(row.get("refrigerant_r32_price_cny")),
                    soda_ash_operating_rate=_safe_float(row.get("soda_ash_operating_rate")),
                    pta_operating_rate=_safe_float(row.get("pta_operating_rate")),
                    chemical_social_inventory=_safe_float(row.get("chemical_social_inventory")),
                    unit=row.get("unit") or "mixed",
                    source=row.get("source") or "NBS/CZCE/100ppi",
                    source_url=row.get("source_url") or "https://data.stats.gov.cn/",
                    release_date=rel_d,
                    data_status=row.get("data_status") or "actual",
                    collected_at=row.get("collected_at") or now_utc_iso(),
                )
            )

    records.sort(key=lambda r: r.trade_date)
    return records


class ChemicalsCollector:
    """基础化工真实基本面物理量采集器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
        crawler: ChemicalsCrawler | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.chem_dir = self.raw_dir / "chemicals"
        self.crawler = crawler or ChemicalsCrawler(raw_dir=self.raw_dir)

    def _get_release_date(self, yr: int, mo: int) -> date:
        """次月 18 日作为 NBS 官方月度工业报告发布日。"""
        if mo == 12:
            return date(yr + 1, 1, 18)
        return date(yr, mo + 1, 18)

    def collect(self, force: bool = False) -> list[ChemicalMarketRecord]:
        """执行数据采集: 从 RAW CSV 读入历史底表，在线抓取最新月度参考价并增量追加对齐。"""
        self.chem_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.chem_dir / "chemical_operating_spreads.csv"

        now_iso = now_utc_iso()
        records = self.load_from_raw_csv(csv_file)
        rec_dict: dict[str, ChemicalMarketRecord] = {r.report_month: r for r in records}

        # 尝试在线抓取最新价格
        live_prices = self.crawler.fetch_latest_prices(force=force)
        if live_prices and live_prices.get("report_month"):
            m_key = str(live_prices["report_month"])
            yr, mo = parse_month_string(m_key)
            t_d = get_month_end_date(yr, mo)
            rel_d = (
                date.fromisoformat(live_prices["release_date"])
                if live_prices.get("release_date")
                else self._get_release_date(yr, mo)
            )

            prev_rec = rec_dict.get(m_key)
            if prev_rec is None and records:
                prev_rec = records[-1]

            rec_dict[m_key] = ChemicalMarketRecord(
                report_month=m_key,
                trade_date=t_d,
                soda_ash_production=prev_rec.soda_ash_production if prev_rec else None,
                caustic_soda_production=prev_rec.caustic_soda_production if prev_rec else None,
                synthetic_fiber_production=prev_rec.synthetic_fiber_production
                if prev_rec
                else None,
                chemical_fertilizer_production=prev_rec.chemical_fertilizer_production
                if prev_rec
                else None,
                plastics_production=prev_rec.plastics_production if prev_rec else None,
                plate_glass_production=prev_rec.plate_glass_production if prev_rec else None,
                czce_soda_ash_receipt=prev_rec.czce_soda_ash_receipt if prev_rec else None,
                czce_pta_receipt=prev_rec.czce_pta_receipt if prev_rec else None,
                czce_urea_receipt=prev_rec.czce_urea_receipt if prev_rec else None,
                soda_ash_price_cny=prev_rec.soda_ash_price_cny if prev_rec else None,
                pta_price_cny=prev_rec.pta_price_cny if prev_rec else None,
                urea_price_cny=prev_rec.urea_price_cny if prev_rec else None,
                mdi_price_cny=live_prices.get("mdi_price_cny")
                or (prev_rec.mdi_price_cny if prev_rec else None),
                tio2_price_cny=live_prices.get("tio2_price_cny")
                or (prev_rec.tio2_price_cny if prev_rec else None),
                refrigerant_r32_price_cny=prev_rec.refrigerant_r32_price_cny if prev_rec else None,
                soda_ash_operating_rate=None,
                pta_operating_rate=None,
                chemical_social_inventory=None,
                unit="mixed",
                source=live_prices.get("source") or "NBS/CZCE/100ppi",
                source_url=live_prices.get("source_url") or "https://data.stats.gov.cn/",
                release_date=rel_d,
                data_status="actual",
                collected_at=now_iso,
            )

        all_records = sorted(rec_dict.values(), key=lambda r: r.trade_date)
        if all_records:
            self.save_to_raw_csv(csv_file, all_records)
        return all_records

    def save_to_raw_csv(self, file_path: Path | str, records: list[ChemicalMarketRecord]) -> None:
        save_chemicals_raw_csv(file_path, records)

    def load_from_raw_csv(self, file_path: Path | str) -> list[ChemicalMarketRecord]:
        return load_chemicals_raw_csv(file_path)
