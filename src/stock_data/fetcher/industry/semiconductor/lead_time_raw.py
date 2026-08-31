"""芯片交付周期 RAW 快照文件加载与归档工具。"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import (
    get_month_end_date,
    now_utc_iso,
    parse_month_string,
    save_raw_snapshot,
)
from stock_data.fetcher.industry.models import ChipLeadTimeRecord

logger = logging.getLogger(__name__)


def determine_lead_time_status(avg_weeks: float, thresholds: dict[str, float] | None = None) -> str:
    """根据交付周期周数及配置阈值判定供需紧张状态。"""
    th = thresholds or {"overheating": 26.0, "tight": 18.0, "normal": 13.0}
    if avg_weeks >= th.get("overheating", 26.0):
        return "overheating"
    if avg_weeks >= th.get("tight", 18.0):
        return "tight"
    if avg_weeks >= th.get("normal", 13.0):
        return "normal"
    return "easing"


def archive_lead_time_raw_snapshot(
    raw_dir: Path,
    month_key: str,
    record: ChipLeadTimeRecord,
    cat_averages: dict[str, float],
    sku_details: dict[str, Any],
) -> Path:
    """将实时采集结果归档到 RAW 目录。"""
    content = {
        "report_month": month_key,
        "trade_date": record.trade_date.isoformat(),
        "avg_lead_time_weeks": record.avg_lead_time_weeks,
        "category_averages": cat_averages,
        "sku_details": sku_details,
        "collected_at": record.collected_at,
    }
    return save_raw_snapshot(
        source_name="lead_time",
        snapshot_filename=f"chip_lead_time_{month_key}.json",
        content=content,
        base_dir=raw_dir,
    )


def load_lead_time_raw_records(
    lead_time_raw_dir: Path,
    thresholds: dict[str, float] | None = None,
) -> list[ChipLeadTimeRecord]:
    """从本地 RAW 目录加载所有历史快照 (自动合并解析 *.csv 与 *.json 原始文件)。"""
    if not lead_time_raw_dir.exists():
        return []

    records_map: dict[str, ChipLeadTimeRecord] = {}

    # 1. 扫描所有 CSV 原始历史文件
    for csv_file in sorted(lead_time_raw_dir.glob("*.csv")):
        try:
            with csv_file.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    m_key = row.get("month") or row.get("report_month")
                    if not m_key:
                        continue
                    m_key = m_key.strip()
                    yr, mo = parse_month_string(m_key)
                    trade_d = get_month_end_date(yr, mo)
                    avg_val = float(row.get("avg", 0) or row.get("avg_lead_time_weeks", 0))
                    records_map[m_key] = ChipLeadTimeRecord(
                        report_month=m_key,
                        trade_date=trade_d,
                        avg_lead_time_weeks=avg_val,
                        mcu_lead_time_weeks=float(
                            row.get("mcu", 0) or row.get("mcu_lead_time_weeks", 0)
                        )
                        or None,
                        analog_lead_time_weeks=float(
                            row.get("analog", 0) or row.get("analog_lead_time_weeks", 0)
                        )
                        or None,
                        discrete_lead_time_weeks=float(
                            row.get("discrete", 0) or row.get("discrete_lead_time_weeks", 0)
                        )
                        or None,
                        compute_lead_time_weeks=float(
                            row.get("compute", 0) or row.get("compute_lead_time_weeks", 0)
                        )
                        or None,
                        lead_time_yoy_weeks=None,
                        lead_time_mom_weeks=None,
                        lead_time_status=determine_lead_time_status(avg_val, thresholds),
                        unit="weeks",
                        source=row.get("source", "External Bulletin"),
                        source_url="",
                        release_date=trade_d,
                        data_status="actual",
                        collected_at=now_utc_iso(),
                    )
        except Exception as e:
            logger.warning("解析芯片交期 RAW CSV [%s] 失败: %s", csv_file.name, e)

    # 2. 扫描所有月度 JSON 快照
    for json_file in sorted(lead_time_raw_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            m_key = data.get("report_month")
            if not m_key or "avg_lead_time_weeks" not in data:
                continue

            yr, mo = parse_month_string(m_key)
            trade_d = get_month_end_date(yr, mo)
            avg_val = float(data["avg_lead_time_weeks"])
            cat_avg = data.get("category_averages", {})

            records_map[m_key] = ChipLeadTimeRecord(
                report_month=m_key,
                trade_date=trade_d,
                avg_lead_time_weeks=avg_val,
                mcu_lead_time_weeks=cat_avg.get("mcu"),
                analog_lead_time_weeks=cat_avg.get("analog"),
                discrete_lead_time_weeks=cat_avg.get("discrete"),
                compute_lead_time_weeks=cat_avg.get("compute"),
                lead_time_yoy_weeks=None,
                lead_time_mom_weeks=None,
                lead_time_status=determine_lead_time_status(avg_val, thresholds),
                unit="weeks",
                source=data.get("source", "Mouser/Distributor"),
                source_url=data.get("source_url", "https://api.mouser.com"),
                release_date=trade_d,
                data_status="actual",
                collected_at=data.get("collected_at", now_utc_iso()),
            )
        except Exception as e:
            logger.warning("解析芯片交期 RAW JSON 快照 [%s] 失败: %s", json_file.name, e)

    records = list(records_map.values())
    records.sort(key=lambda r: r.trade_date)
    return records
