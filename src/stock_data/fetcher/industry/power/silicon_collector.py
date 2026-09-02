"""中国有色金属工业协会硅业分会 (安泰科) 多晶硅/单晶硅片月度产出与运行指标采集适配器 (SiliconBranchCollector)。"""

from __future__ import annotations

import csv
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
)
from stock_data.fetcher.industry.models import (
    PolysiliconInventoryMonthlyRecord,
    PolysiliconSupplyMonthlyRecord,
    PvWaferMonthlyRecord,
    SiliconWaferMonthlyRecord,
)

logger = logging.getLogger(__name__)

SILICON_BRANCH_RELEASE_DAY = 7
SILICON_WAFER_FIELDNAMES = [
    "report_month",
    "trade_date",
    "polysilicon_output_w_tons",
    "polysilicon_output_yoy",
    "polysilicon_operating_rate",
    "derived_polysilicon_utilization_rate",
    "wafer_output_gw",
    "wafer_output_yoy",
    "wafer_operating_rate",
    "derived_wafer_utilization_rate",
    "polysilicon_inventory_w_tons",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


def parse_silicon_branch_bulletin_text(text: str) -> dict[str, Any]:
    """从硅业分会/安泰科官方月度通报或周评文本中正则抽取产出与开工率关键指标。"""
    results: dict[str, Any] = {
        "polysilicon_output_w_tons": None,
        "polysilicon_output_yoy": None,
        "polysilicon_operating_rate": None,
        "wafer_output_gw": None,
        "wafer_output_yoy": None,
        "wafer_operating_rate": None,
        "polysilicon_inventory_w_tons": None,
    }

    # 1. 多晶硅月度产量 (万吨)
    poly_m = re.search(r"多晶硅产量为?\s*([\d.]+)\s*万吨", text) or re.search(
        r"多晶硅产出\s*([\d.]+)\s*万吨", text
    )
    if poly_m:
        try:
            results["polysilicon_output_w_tons"] = float(poly_m.group(1))
        except ValueError:
            pass

    # 2. 硅片月度产出 (GW)
    wafer_m = re.search(r"硅片产出\s*([\d.]+)\s*GW", text, re.IGNORECASE) or re.search(
        r"硅片产量为?\s*([\d.]+)\s*GW", text, re.IGNORECASE
    )
    if wafer_m:
        try:
            results["wafer_output_gw"] = float(wafer_m.group(1))
        except ValueError:
            pass

    # 3. 多晶硅企业开工率 (%)
    poly_op_m = re.search(r"多晶硅.*?开工率为?\s*([\d.]+)%", text)
    if poly_op_m:
        try:
            results["polysilicon_operating_rate"] = float(poly_op_m.group(1))
        except ValueError:
            pass

    # 4. 硅片行业开工率 (%)
    wafer_op_m = re.search(r"硅片.*?开工率(?:在|为)?\s*([\d.]+)%", text)
    if wafer_op_m:
        try:
            results["wafer_operating_rate"] = float(wafer_op_m.group(1))
        except ValueError:
            pass

    # 5. 多晶硅社会库存 (万吨)
    inv_m = re.search(r"多晶硅库存.*?至\s*([\d.]+)\s*万吨", text)
    if inv_m:
        try:
            results["polysilicon_inventory_w_tons"] = float(inv_m.group(1))
        except ValueError:
            pass

    return results


class SiliconBranchCollector:
    """硅业分会多晶硅与单晶硅片月度基本面数据采集器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.csv_file = self.raw_dir / "power" / "silicon_wafer_monthly.csv"

    def _release_date(self, report_month: str) -> date:
        yr, mo = parse_month_string(report_month)
        if mo == 12:
            return date(yr + 1, 1, SILICON_BRANCH_RELEASE_DAY)
        return date(yr, mo + 1, SILICON_BRANCH_RELEASE_DAY)

    def collect(self) -> list[SiliconWaferMonthlyRecord]:
        """从本地 RAW CSV 读取并标准化为领域记录模型列表。"""
        if not self.csv_file.exists():
            logger.warning("硅业分会月度 RAW 快照不存在: %s", self.csv_file)
            return []
        return self.load_from_raw_csv(self.csv_file)

    def load_from_raw_csv(self, file_path: Path | str) -> list[SiliconWaferMonthlyRecord]:
        """从 RAW 快照 CSV 读取并解析为 SiliconWaferMonthlyRecord 列表。"""
        p = Path(file_path)
        if not p.exists():
            return []

        def _safe_float(val: str | None) -> float | None:
            if not val or not str(val).strip() or str(val).strip() in ("nan", "None", ""):
                return None
            try:
                return float(str(val).strip())
            except (ValueError, TypeError):
                return None

        records: list[SiliconWaferMonthlyRecord] = []
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                m_str = row["report_month"].strip()
                yr, mo = parse_month_string(m_str)
                t_date = get_month_end_date(yr, mo)
                rel_d = None
                if row.get("release_date"):
                    try:
                        rel_d = date.fromisoformat(row["release_date"].strip())
                    except ValueError:
                        pass
                if rel_d is None and row.get("data_status") != "missing_unverified":
                    rel_d = self._release_date(m_str)

                records.append(
                    SiliconWaferMonthlyRecord(
                        report_month=m_str,
                        trade_date=t_date,
                        polysilicon_output_w_tons=_safe_float(row.get("polysilicon_output_w_tons")),
                        polysilicon_output_yoy=_safe_float(row.get("polysilicon_output_yoy")),
                        polysilicon_operating_rate=_safe_float(
                            row.get("polysilicon_operating_rate")
                        ),
                        derived_polysilicon_utilization_rate=_safe_float(
                            row.get("derived_polysilicon_utilization_rate")
                        ),
                        wafer_output_gw=_safe_float(row.get("wafer_output_gw")),
                        wafer_output_yoy=_safe_float(row.get("wafer_output_yoy")),
                        wafer_operating_rate=_safe_float(row.get("wafer_operating_rate")),
                        derived_wafer_utilization_rate=_safe_float(
                            row.get("derived_wafer_utilization_rate")
                        ),
                        polysilicon_inventory_w_tons=_safe_float(
                            row.get("polysilicon_inventory_w_tons")
                        ),
                        unit=row.get("unit") or "ten_thousand_tons_and_gw",
                        source=row.get("source") or "Silicon_Branch_Antaike",
                        source_url=row.get("source_url") or "http://www.silicon.net.cn/",
                        release_date=rel_d,
                        data_status=row.get("data_status") or "actual",
                        collected_at=row.get("collected_at") or now_utc_iso(),
                    )
                )

        records.sort(key=lambda r: r.trade_date)
        logger.info("已读取硅业分会多晶硅与硅片月度数据 %d 行 (RAW: %s)", len(records), p)
        return records

    def save_to_raw_csv(
        self, file_path: Path | str, records: list[SiliconWaferMonthlyRecord]
    ) -> None:
        """持久化标准化记录至 RAW CSV 快照。"""
        save_silicon_records_to_raw_csv(file_path, records)

    def collect_supply(self) -> list[PolysiliconSupplyMonthlyRecord]:
        """提取标准化多晶硅供给事实记录列表。"""
        records = self.collect()
        supply_records: list[PolysiliconSupplyMonthlyRecord] = []
        for r in records:
            yr, _ = parse_month_string(r.report_month)
            cap = get_polysilicon_annual_capacity(yr)
            util = (
                r.derived_polysilicon_utilization_rate
                if r.derived_polysilicon_utilization_rate is not None
                else (
                    round((r.polysilicon_output_w_tons * 12.0 / cap) * 100.0, 2)
                    if r.polysilicon_output_w_tons is not None and cap > 0
                    else None
                )
            )
            supply_records.append(
                PolysiliconSupplyMonthlyRecord(
                    report_month=r.report_month,
                    trade_date=r.trade_date,
                    production_w_tons=r.polysilicon_output_w_tons,
                    production_yoy=r.polysilicon_output_yoy,
                    production_mom=None,
                    capacity_annual_w_tons=cap,
                    operating_rate=r.polysilicon_operating_rate,
                    derived_utilization_rate=util,
                    unit="ten_thousand_tons",
                    source=r.source,
                    source_url=r.source_url,
                    release_date=r.release_date,
                    data_status=r.data_status,
                    collected_at=r.collected_at,
                )
            )
        return supply_records

    def collect_inventory(self) -> list[PolysiliconInventoryMonthlyRecord]:
        """提取标准化多晶硅库存事实记录列表。"""
        records = self.collect()
        inventory_records: list[PolysiliconInventoryMonthlyRecord] = []
        for r in records:
            if r.polysilicon_inventory_w_tons is not None:
                inventory_records.append(
                    PolysiliconInventoryMonthlyRecord(
                        report_month=r.report_month,
                        trade_date=r.trade_date,
                        inventory_w_tons=r.polysilicon_inventory_w_tons,
                        inventory_change_w_tons=None,
                        inventory_weeks=None,
                        inventory_status="normal",
                        unit="ten_thousand_tons",
                        source=r.source,
                        source_url=r.source_url,
                        release_date=r.release_date,
                        data_status=r.data_status,
                        collected_at=r.collected_at,
                    )
                )
        return inventory_records

    def collect_wafer(self) -> list[PvWaferMonthlyRecord]:
        """提取标准化单晶硅片产出与折算需求事实记录列表。"""
        records = self.collect()
        wafer_records: list[PvWaferMonthlyRecord] = []
        for r in records:
            wafer_records.append(
                PvWaferMonthlyRecord(
                    report_month=r.report_month,
                    trade_date=r.trade_date,
                    wafer_output_gw=r.wafer_output_gw,
                    wafer_output_yoy=r.wafer_output_yoy,
                    wafer_operating_rate=r.wafer_operating_rate,
                    derived_wafer_utilization_rate=r.derived_wafer_utilization_rate,
                    silicon_consumption_ratio=None,
                    implied_silicon_demand_w_tons=None,
                    unit="gw/ten_thousand_tons",
                    source=r.source,
                    source_url=r.source_url,
                    release_date=r.release_date,
                    data_status=r.data_status,
                    collected_at=r.collected_at,
                )
            )
        return wafer_records


def get_polysilicon_annual_capacity(year: int) -> float:
    """按年份获取中国多晶硅名义年化产能基准 (万吨/年, 来源于 CPIA/硅业分会)。"""
    capacities = {
        2018: 38.8,
        2019: 45.2,
        2020: 52.0,
        2021: 62.3,
        2022: 120.3,
        2023: 240.0,
        2024: 310.0,
        2025: 348.0,
        2026: 348.0,
    }
    return capacities.get(year, 348.0 if year > 2026 else 38.8)


def save_silicon_records_to_raw_csv(
    file_path: Path | str, records: list[SiliconWaferMonthlyRecord]
) -> None:
    """持久化硅业分会标准化记录至 RAW CSV 快照。"""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SILICON_WAFER_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(_silicon_record_to_row(r))


def _silicon_record_to_row(r: SiliconWaferMonthlyRecord) -> dict[str, str | float]:
    return {
        "report_month": r.report_month,
        "trade_date": r.trade_date.isoformat(),
        "polysilicon_output_w_tons": r.polysilicon_output_w_tons
        if r.polysilicon_output_w_tons is not None
        else "",
        "polysilicon_output_yoy": r.polysilicon_output_yoy
        if r.polysilicon_output_yoy is not None
        else "",
        "polysilicon_operating_rate": r.polysilicon_operating_rate
        if r.polysilicon_operating_rate is not None
        else "",
        "derived_polysilicon_utilization_rate": r.derived_polysilicon_utilization_rate
        if r.derived_polysilicon_utilization_rate is not None
        else "",
        "wafer_output_gw": r.wafer_output_gw if r.wafer_output_gw is not None else "",
        "wafer_output_yoy": r.wafer_output_yoy if r.wafer_output_yoy is not None else "",
        "wafer_operating_rate": r.wafer_operating_rate
        if r.wafer_operating_rate is not None
        else "",
        "derived_wafer_utilization_rate": r.derived_wafer_utilization_rate
        if r.derived_wafer_utilization_rate is not None
        else "",
        "polysilicon_inventory_w_tons": r.polysilicon_inventory_w_tons
        if r.polysilicon_inventory_w_tons is not None
        else "",
        "unit": r.unit,
        "source": r.source,
        "source_url": r.source_url,
        "release_date": r.release_date.isoformat() if r.release_date else "",
        "data_status": r.data_status,
        "collected_at": r.collected_at or now_utc_iso(),
    }
