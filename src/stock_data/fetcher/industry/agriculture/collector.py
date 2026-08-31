"""农业农村部 (MARA) 能繁母猪存栏、生猪出栏价与猪粮比采集器 (AgriculturePorkCollector)。"""

from __future__ import annotations

import csv
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.agriculture.crawler import MaraPorkCrawler
from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
)
from stock_data.fetcher.industry.models import AgriculturePorkRecord

logger = logging.getLogger(__name__)

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


def parse_mara_pork_bulletin_text(text: str) -> dict[str, Any] | None:
    """从农业农村部生猪生产通报正文中提取能繁母猪存栏、生猪出栏价与猪粮比。"""
    clean_text = text.replace(" ", "").replace("\n", "").replace("\r", "")

    sow_val: float | None = None
    m_sow = re.search(r"能繁母猪存栏(?:量)?(?:约)?(\d+\.?\d*)\s*(万头|百万头)", clean_text)
    if m_sow:
        raw_val = float(m_sow.group(1))
        unit = m_sow.group(2)
        sow_val = round(raw_val * 0.01 if unit == "万头" else raw_val, 2)

    pig_price: float | None = None
    m_price = re.search(
        r"(?:生猪|生猪出栏|全国生猪)(?:平均)?价格(?:约)?(\d+\.?\d*)\s*(?:元/公斤|元/kg)", clean_text
    )
    if m_price:
        pig_price = round(float(m_price.group(1)), 2)

    ratio_val: float | None = None
    m_ratio = re.search(r"猪粮比价(?:约为|为)?(\d+\.?\d*):1?", clean_text)
    if m_ratio:
        ratio_val = round(float(m_ratio.group(1)), 2)

    if sow_val is None and pig_price is None:
        return None

    return {
        "sow_stock_million_heads": sow_val,
        "pig_price_cny_per_kg": pig_price,
        "hog_to_grain_ratio": ratio_val,
        "pig_farming_profit_cny_head": None,
        "source": "MARA/NBS",
        "source_url": "http://www.moa.gov.cn/nybgb/",
        "data_status": "actual",
        "collected_at": now_utc_iso(),
    }


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

    def _safe_float(val: str | None) -> float | None:
        if not val or not val.strip():
            return None
        try:
            return float(val.strip())
        except (ValueError, TypeError):
            return None

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


def compute_pork_derivatives(
    records: list[AgriculturePorkRecord],
) -> list[AgriculturePorkRecord]:
    """计算生猪存栏与价格的环比/同比衍生特征。"""
    updated: list[AgriculturePorkRecord] = []
    for i, rec in enumerate(records):
        sow_mom, sow_yoy, pig_yoy = None, None, None
        if (
            i > 0
            and records[i - 1].sow_stock_million_heads is not None
            and rec.sow_stock_million_heads is not None
        ):
            prev_sow = records[i - 1].sow_stock_million_heads
            if prev_sow and prev_sow > 0:
                sow_mom = round((rec.sow_stock_million_heads - prev_sow) / prev_sow, 4)

        if (
            i >= 12
            and records[i - 12].sow_stock_million_heads is not None
            and rec.sow_stock_million_heads is not None
        ):
            prev_y_sow = records[i - 12].sow_stock_million_heads
            if prev_y_sow and prev_y_sow > 0:
                sow_yoy = round((rec.sow_stock_million_heads - prev_y_sow) / prev_y_sow, 4)

        if (
            i >= 12
            and records[i - 12].pig_price_cny_per_kg is not None
            and rec.pig_price_cny_per_kg is not None
        ):
            prev_y_pig = records[i - 12].pig_price_cny_per_kg
            if prev_y_pig and prev_y_pig > 0:
                pig_yoy = round((rec.pig_price_cny_per_kg - prev_y_pig) / prev_y_pig, 4)

        updated.append(
            AgriculturePorkRecord(
                report_month=rec.report_month,
                trade_date=rec.trade_date,
                sow_stock_million_heads=rec.sow_stock_million_heads,
                sow_stock_yoy=sow_yoy,
                sow_stock_mom=sow_mom,
                pig_price_cny_per_kg=rec.pig_price_cny_per_kg,
                pig_price_yoy=pig_yoy,
                hog_to_grain_ratio=rec.hog_to_grain_ratio,
                pig_farming_profit_cny_head=rec.pig_farming_profit_cny_head,
                unit=rec.unit,
                source=rec.source,
                source_url=rec.source_url,
                release_date=rec.release_date,
                data_status=rec.data_status,
                collected_at=rec.collected_at,
            )
        )
    return updated


class AgriculturePorkCollector:
    """生猪养殖与产能周期 (能繁母猪/生猪价格/猪粮比) 采集适配器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.agri_raw_dir = self.raw_dir / "agriculture"
        self.crawler = MaraPorkCrawler(raw_dir=self.raw_dir)

    def collect(self) -> list[AgriculturePorkRecord]:
        """执行生猪产能数据采集: 在线抓取农业农村部最新月度通报并落盘，以最新采集为准。"""
        self.agri_raw_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.agri_raw_dir / "pork_capacity_monthly.csv"

        # 在线抓取农业农村部最新生猪月度通报
        live_data = self.crawler.fetch_latest_month()
        if not live_data or not live_data.get("report_month"):
            logger.warning("在线抓取农业农村部生猪月度通报失败")
            return []

        m_key = str(live_data["report_month"])
        yr, mo = parse_month_string(m_key)
        t_date = get_month_end_date(yr, mo)
        rec_live = AgriculturePorkRecord(
            report_month=m_key,
            trade_date=t_date,
            sow_stock_million_heads=live_data.get("sow_stock_million_heads"),
            sow_stock_yoy=None,
            sow_stock_mom=None,
            pig_price_cny_per_kg=live_data.get("pig_price_cny_per_kg"),
            pig_price_yoy=None,
            hog_to_grain_ratio=live_data.get("hog_to_grain_ratio"),
            pig_farming_profit_cny_head=live_data.get("pig_farming_profit_cny_head"),
            unit="million_heads/cny_per_kg",
            source=live_data.get("source") or "MARA/NBS",
            source_url=live_data.get("source_url") or "http://www.moa.gov.cn/",
            release_date=date.fromisoformat(live_data["release_date"])
            if live_data.get("release_date")
            else None,
            data_status=live_data.get("data_status") or "actual",
            collected_at=live_data.get("collected_at") or now_utc_iso(),
        )

        records = [rec_live]
        self.save_to_raw_csv(csv_file, records)
        return records

    def save_to_raw_csv(self, file_path: Path | str, records: list[AgriculturePorkRecord]) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        save_pork_raw_csv(file_path, records)

    def load_from_raw_csv(self, file_path: Path | str) -> list[AgriculturePorkRecord]:
        """从 RAW CSV 文件读取并标准化记录。"""
        return load_pork_raw_csv(file_path)
