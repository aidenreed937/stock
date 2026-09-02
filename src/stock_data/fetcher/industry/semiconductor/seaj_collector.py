"""SEAJ (日本半导体设备制造协会) 月度半导体设备出货额采集器 (SeajEquipmentCollector)。

数据属性与 2-Tier ETL 架构:
1. 阶段 1 产能建设领先指标: 设备订单与出货领先晶圆厂投产 1-2 年;
2. 权威官方源: SEAJ (https://www.seaj.or.jp/statistics/) 每月 20-25 日发布上月速报 (含 3MMA 与同比);
3. 2-Tier 存储: 历史基底持久化为 RAW CSV (seaj_equipment_billings.csv)，每次增量采集自动追加对齐并物化 Curated Parquet;
4. 消除前视偏差: release_date 严格采用官方实际发布日 (无前视)。
"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
)
from stock_data.fetcher.industry.models import SemiconductorEquipmentRecord
from stock_data.fetcher.industry.semiconductor.seaj_crawler import (
    SEAJ_STATISTICS_URL,
    SeajCrawler,
)

logger = logging.getLogger(__name__)

SEAJ_CSV_FIELDNAMES = [
    "report_month",
    "trade_date",
    "billings_jpy_billion",
    "billings_3mma_jpy",
    "yoy_growth",
    "yoy_growth_3mma",
    "mom_growth_3mma",
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


def load_seaj_raw_csv(file_path: Path | str) -> list[SemiconductorEquipmentRecord]:
    """从 RAW CSV 读取已持久化的月度半导体设备出货记录。"""
    p = Path(file_path)
    if not p.exists():
        return []

    records: list[SemiconductorEquipmentRecord] = []
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ym = row["report_month"].strip()
                yr, mo = parse_month_string(ym)
                t_date = get_month_end_date(yr, mo)

                rel_d = None
                if row.get("release_date"):
                    try:
                        rel_d = date.fromisoformat(row["release_date"].strip())
                    except ValueError:
                        pass
                if rel_d is None:
                    # 默认次月 25 日
                    next_yr, next_mo = (yr + 1, 1) if mo == 12 else (yr, mo + 1)
                    rel_d = date(next_yr, next_mo, 25)

                records.append(
                    SemiconductorEquipmentRecord(
                        report_month=ym,
                        trade_date=t_date,
                        billings_jpy_billion=float(row["billings_jpy_billion"]),
                        billings_3mma_jpy=_safe_float(row.get("billings_3mma_jpy")),
                        yoy_growth=_safe_float(row.get("yoy_growth")),
                        yoy_growth_3mma=_safe_float(row.get("yoy_growth_3mma")),
                        mom_growth_3mma=_safe_float(row.get("mom_growth_3mma")),
                        unit=row.get("unit") or "billion_jpy",
                        source=row.get("source") or "SEAJ",
                        source_url=row.get("source_url") or SEAJ_STATISTICS_URL,
                        release_date=rel_d,
                        data_status=row.get("data_status") or "actual",
                        collected_at=row.get("collected_at") or now_utc_iso(),
                    )
                )
    except Exception as exc:
        logger.warning("读取 SEAJ RAW CSV 失败: %s", exc)

    records.sort(key=lambda r: r.trade_date)
    return records


def save_seaj_raw_csv(file_path: Path | str, records: list[SemiconductorEquipmentRecord]) -> None:
    """持久化标准化记录至 RAW CSV 快照。"""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SEAJ_CSV_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "report_month": r.report_month,
                    "trade_date": r.trade_date.isoformat(),
                    "billings_jpy_billion": r.billings_jpy_billion,
                    "billings_3mma_jpy": r.billings_3mma_jpy
                    if r.billings_3mma_jpy is not None
                    else "",
                    "yoy_growth": r.yoy_growth if r.yoy_growth is not None else "",
                    "yoy_growth_3mma": r.yoy_growth_3mma if r.yoy_growth_3mma is not None else "",
                    "mom_growth_3mma": r.mom_growth_3mma if r.mom_growth_3mma is not None else "",
                    "unit": r.unit,
                    "source": r.source,
                    "source_url": r.source_url,
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status,
                    "collected_at": r.collected_at,
                }
            )


class SeajEquipmentCollector:
    """日本半导体设备制造协会 (SEAJ) 月度设备出货额采集器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.snapshot_dir = self.raw_dir / "semiconductor" / "seaj"
        self.crawler = SeajCrawler(raw_dir=self.raw_dir)

    def _get_release_date(self, yr: int, mo: int) -> date:
        """次月 25 日作为默认官方发布生效日 (release_date)。"""
        if mo == 12:
            next_yr, next_mo = yr + 1, 1
        else:
            next_yr, next_mo = yr, mo + 1
        return date(next_yr, next_mo, 25)

    def collect(self, force: bool = False) -> list[SemiconductorEquipmentRecord]:
        """执行数据采集: 从 RAW CSV 加载底表，在线抓取解析最新速报并增量追加对齐。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        csv_file = self.snapshot_dir / "seaj_equipment_billings.csv"

        now_iso = now_utc_iso()
        # 1. 加载本地 RAW CSV 已存记录
        records = self.load_from_raw_csv(csv_file)
        records_dict: dict[str, SemiconductorEquipmentRecord] = {r.report_month: r for r in records}

        # 2. 在线抓取并解析 SEAJ 官网最新速报 (增量覆盖/追加)
        try:
            live_items = self.crawler.fetch_latest(force=force)
            for item in live_items:
                ym = item["report_month"]
                yr, mo = parse_month_string(ym)
                t_date = get_month_end_date(yr, mo)
                rel_d = item.get("release_date") or self._get_release_date(yr, mo)

                records_dict[ym] = SemiconductorEquipmentRecord(
                    report_month=ym,
                    trade_date=t_date,
                    billings_jpy_billion=float(item["billings_jpy_billion"]),
                    billings_3mma_jpy=float(item["billings_3mma_jpy"])
                    if item.get("billings_3mma_jpy") is not None
                    else None,
                    yoy_growth=float(item["yoy_growth"])
                    if item.get("yoy_growth") is not None
                    else None,
                    yoy_growth_3mma=float(item["yoy_growth_3mma"])
                    if item.get("yoy_growth_3mma") is not None
                    else None,
                    mom_growth_3mma=float(item["mom_growth_3mma"])
                    if item.get("mom_growth_3mma") is not None
                    else None,
                    unit="billion_jpy",
                    source="SEAJ",
                    source_url=SEAJ_STATISTICS_URL,
                    release_date=rel_d,
                    data_status="actual",
                    collected_at=now_iso,
                )
        except Exception as exc:
            logger.warning("SEAJ 在线抓取解析失败: %s", exc)

        all_records = sorted(records_dict.values(), key=lambda r: r.trade_date)
        if all_records:
            self.save_to_raw_csv(csv_file, all_records)

        return all_records

    def load_from_raw_csv(self, file_path: Path | str) -> list[SemiconductorEquipmentRecord]:
        return load_seaj_raw_csv(file_path)

    def save_to_raw_csv(
        self, file_path: Path | str, records: list[SemiconductorEquipmentRecord]
    ) -> None:
        save_seaj_raw_csv(file_path, records)
