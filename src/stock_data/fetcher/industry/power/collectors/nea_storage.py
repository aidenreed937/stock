"""国家能源局光伏装机 RAW CSV 读写。"""

import csv
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import get_month_end_date, now_utc_iso, parse_month_string
from stock_data.fetcher.industry.power.lineage import file_lineage
from stock_data.fetcher.industry.power.models import SolarCapacityRecord
from stock_data.fetcher.industry.power.schemas import SOLAR_CAPACITY_RAW_SCHEMA


def _safe_float(value: object) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None


def save_solar_capacity_raw_csv(
    file_path: Path | str,
    records: list[SolarCapacityRecord],
) -> None:
    """持久化标准化记录至 NEA RAW CSV 快照。"""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(SOLAR_CAPACITY_RAW_SCHEMA))
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "report_month": r.report_month,
                    "trade_date": r.trade_date.isoformat(),
                    "monthly_new_capacity_gw_raw": r.monthly_new_capacity_gw_raw or "",
                    "cumulative_capacity_gw_raw": r.cumulative_capacity_gw_raw or "",
                    "yoy_growth_raw": r.yoy_growth_raw or "",
                    "source": r.source or "NEA",
                    "source_url": r.source_url or "",
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status or "actual",
                    "collected_at": r.collected_at or now_utc_iso(),
                    "raw_content_sha256": r.raw_content_sha256 or "",
                    "raw_snapshot_path": r.raw_snapshot_path or "",
                }
            )


def load_solar_capacity_raw_csv(
    file_path: Path | str,
    raw_dir: Path | str,
) -> list[SolarCapacityRecord]:
    """从 NEA RAW CSV 中读取并标准化记录。"""
    p = Path(file_path)
    if not p.exists():
        return []

    content_hash, snapshot_ref = file_lineage(p, Path(raw_dir))
    records: list[SolarCapacityRecord] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            month_str = row["report_month"].strip()
            year, month = parse_month_string(month_str)
            records.append(
                SolarCapacityRecord(
                    report_month=month_str,
                    trade_date=get_month_end_date(year, month),
                    monthly_new_capacity_gw=(
                        _safe_float(row.get("monthly_new_capacity_gw_raw"))
                        if row.get("monthly_new_capacity_gw_raw")
                        else _safe_float(row.get("monthly_new_capacity_gw"))
                    ),
                    cumulative_capacity_gw=(
                        _safe_float(row.get("cumulative_capacity_gw_raw"))
                        if row.get("cumulative_capacity_gw_raw")
                        else _safe_float(row.get("cumulative_capacity_gw"))
                    ),
                    yoy_growth=(
                        _safe_float(row.get("yoy_growth_raw"))
                        if row.get("yoy_growth_raw")
                        else _safe_float(row.get("yoy_growth"))
                    ),
                    unit=row.get("unit") or "gw",
                    source=row.get("source") or "NEA",
                    source_url=row.get("source_url") or "http://www.nea.gov.cn/",
                    release_date=date.fromisoformat(row["release_date"].strip())
                    if row.get("release_date")
                    else None,
                    data_status=row.get("data_status") or "actual",
                    collected_at=row.get("collected_at") or now_utc_iso(),
                    monthly_new_capacity_gw_raw=(
                        row.get("monthly_new_capacity_gw_raw")
                        or row.get("monthly_new_capacity_gw")
                        or None
                    ),
                    cumulative_capacity_gw_raw=(
                        row.get("cumulative_capacity_gw_raw")
                        or row.get("cumulative_capacity_gw")
                        or None
                    ),
                    yoy_growth_raw=row.get("yoy_growth_raw") or row.get("yoy_growth") or None,
                    raw_content_sha256=row.get("raw_content_sha256") or content_hash,
                    raw_snapshot_path=row.get("raw_snapshot_path") or snapshot_ref,
                )
            )
    records.sort(key=lambda r: r.trade_date)
    return records


__all__ = ["load_solar_capacity_raw_csv", "save_solar_capacity_raw_csv"]
