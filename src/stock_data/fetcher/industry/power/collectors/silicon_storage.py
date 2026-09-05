"""硅业分会月度 RAW CSV 与年度产能事实读写。"""

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.common import get_month_end_date, now_utc_iso, parse_month_string
from stock_data.fetcher.industry.power.lineage import file_lineage
from stock_data.fetcher.industry.power.models import SiliconWaferMonthlyRecord
from stock_data.fetcher.industry.power.paths import PowerRawPaths
from stock_data.fetcher.industry.power.schemas import SILICON_WAFER_RAW_SCHEMA

logger = logging.getLogger(__name__)

ACTUAL_SILICON_DATA_STATUSES = {"actual", "verified_industry_report"}
CAPACITY_RAW_CANDIDATES = (
    "power/polysilicon_wafer_capacity_annual.csv",
    "energy/polysilicon_wafer_capacity_annual.csv",
    "polysilicon_wafer_capacity_annual.csv",
)
SILICON_WAFER_FIELDNAMES = list(SILICON_WAFER_RAW_SCHEMA)


def safe_float(val: object) -> float | None:
    if not val or not str(val).strip() or str(val).strip() in ("nan", "None", ""):
        return None
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return None


def safe_int(val: object) -> int | None:
    if not val or not str(val).strip():
        return None
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return None


def records_from_online(rows: list[Any]) -> list[SiliconWaferMonthlyRecord]:
    records: list[SiliconWaferMonthlyRecord] = []
    for row in rows:
        if isinstance(row, SiliconWaferMonthlyRecord):
            records.append(row)
            continue
        if not isinstance(row, dict) or not row.get("report_month"):
            continue
        period = str(row["report_month"])
        year, month = parse_month_string(period)
        raw_values = {
            key: (str(row[key]) if row.get(key) is not None else None)
            for key in (
                "polysilicon_output_w_tons",
                "polysilicon_output_yoy",
                "polysilicon_operating_rate",
                "wafer_output_gw",
                "wafer_output_yoy",
                "wafer_operating_rate",
                "polysilicon_inventory_w_tons",
            )
        }
        records.append(
            SiliconWaferMonthlyRecord(
                report_month=period,
                trade_date=get_month_end_date(year, month),
                polysilicon_output_w_tons=safe_float(raw_values["polysilicon_output_w_tons"]),
                polysilicon_output_yoy=safe_float(raw_values["polysilicon_output_yoy"]),
                polysilicon_operating_rate=safe_float(raw_values["polysilicon_operating_rate"]),
                wafer_output_gw=safe_float(raw_values["wafer_output_gw"]),
                wafer_output_yoy=safe_float(raw_values["wafer_output_yoy"]),
                wafer_operating_rate=safe_float(raw_values["wafer_operating_rate"]),
                polysilicon_inventory_w_tons=safe_float(raw_values["polysilicon_inventory_w_tons"]),
                unit="ten_thousand_tons_and_gw",
                source=str(row.get("source") or "Silicon_Branch_Relayed_Solarbe"),
                source_url=str(row.get("source_url") or ""),
                release_date=(
                    date.fromisoformat(str(row["release_date"]))
                    if row.get("release_date")
                    else None
                ),
                data_status="actual",
                collected_at=now_utc_iso(),
                raw_content_sha256=str(row.get("raw_content_sha256") or ""),
                raw_snapshot_path=str(row.get("raw_snapshot_path") or ""),
                polysilicon_output_w_tons_raw=raw_values["polysilicon_output_w_tons"],
                polysilicon_output_yoy_raw=raw_values["polysilicon_output_yoy"],
                polysilicon_operating_rate_raw=raw_values["polysilicon_operating_rate"],
                wafer_output_gw_raw=raw_values["wafer_output_gw"],
                wafer_output_yoy_raw=raw_values["wafer_output_yoy"],
                wafer_operating_rate_raw=raw_values["wafer_operating_rate"],
                polysilicon_inventory_w_tons_raw=raw_values["polysilicon_inventory_w_tons"],
            )
        )
    return records


def load_silicon_records_from_raw_csv(
    file_path: Path | str,
    raw_dir: Path | str,
    *,
    include_unverified: bool = False,
) -> list[SiliconWaferMonthlyRecord]:
    """从 RAW 快照 CSV 读取并解析为 SiliconWaferMonthlyRecord 列表。"""
    p = Path(file_path)
    if not p.exists():
        return []

    content_hash, snapshot_ref = file_lineage(p, Path(raw_dir))
    records: list[SiliconWaferMonthlyRecord] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data_status = str(row.get("data_status") or "").strip() or "actual"
            if not include_unverified and data_status not in ACTUAL_SILICON_DATA_STATUSES:
                continue
            m_str = row["report_month"].strip()
            yr, mo = parse_month_string(m_str)
            rel_d = None
            if row.get("release_date"):
                try:
                    rel_d = date.fromisoformat(row["release_date"].strip())
                except ValueError:
                    pass
            records.append(
                SiliconWaferMonthlyRecord(
                    report_month=m_str,
                    trade_date=get_month_end_date(yr, mo),
                    polysilicon_output_w_tons=safe_float(
                        row.get("polysilicon_output_w_tons_raw")
                        or row.get("polysilicon_output_w_tons")
                    ),
                    polysilicon_output_yoy=safe_float(
                        row.get("polysilicon_output_yoy_raw") or row.get("polysilicon_output_yoy")
                    ),
                    polysilicon_operating_rate=safe_float(
                        row.get("polysilicon_operating_rate_raw")
                        or row.get("polysilicon_operating_rate")
                    ),
                    derived_polysilicon_utilization_rate=safe_float(
                        row.get("derived_polysilicon_utilization_rate")
                    ),
                    wafer_output_gw=safe_float(
                        row.get("wafer_output_gw_raw") or row.get("wafer_output_gw")
                    ),
                    wafer_output_yoy=safe_float(
                        row.get("wafer_output_yoy_raw") or row.get("wafer_output_yoy")
                    ),
                    wafer_operating_rate=safe_float(
                        row.get("wafer_operating_rate_raw") or row.get("wafer_operating_rate")
                    ),
                    derived_wafer_utilization_rate=safe_float(
                        row.get("derived_wafer_utilization_rate")
                    ),
                    polysilicon_inventory_w_tons=safe_float(
                        row.get("polysilicon_inventory_w_tons_raw")
                        or row.get("polysilicon_inventory_w_tons")
                    ),
                    unit=row.get("unit") or "ten_thousand_tons_and_gw",
                    source=row.get("source") or "Silicon_Branch_Antaike",
                    source_url=row.get("source_url") or "http://www.silicon.net.cn/",
                    release_date=rel_d,
                    data_status=data_status,
                    collected_at=row.get("collected_at") or now_utc_iso(),
                    raw_content_sha256=row.get("raw_content_sha256") or content_hash,
                    raw_snapshot_path=row.get("raw_snapshot_path") or snapshot_ref,
                    capacity_raw_content_sha256=row.get("capacity_raw_content_sha256") or "",
                    capacity_raw_snapshot_path=row.get("capacity_raw_snapshot_path") or "",
                    polysilicon_output_w_tons_raw=(
                        row.get("polysilicon_output_w_tons_raw")
                        or row.get("polysilicon_output_w_tons")
                        or None
                    ),
                    polysilicon_output_yoy_raw=(
                        row.get("polysilicon_output_yoy_raw")
                        or row.get("polysilicon_output_yoy")
                        or None
                    ),
                    polysilicon_operating_rate_raw=(
                        row.get("polysilicon_operating_rate_raw")
                        or row.get("polysilicon_operating_rate")
                        or None
                    ),
                    wafer_output_gw_raw=(
                        row.get("wafer_output_gw_raw") or row.get("wafer_output_gw") or None
                    ),
                    wafer_output_yoy_raw=(
                        row.get("wafer_output_yoy_raw") or row.get("wafer_output_yoy") or None
                    ),
                    wafer_operating_rate_raw=(
                        row.get("wafer_operating_rate_raw")
                        or row.get("wafer_operating_rate")
                        or None
                    ),
                    polysilicon_inventory_w_tons_raw=(
                        row.get("polysilicon_inventory_w_tons_raw")
                        or row.get("polysilicon_inventory_w_tons")
                        or None
                    ),
                    polysilicon_capacity_annual_w_tons_raw=(
                        row.get("polysilicon_capacity_annual_w_tons_raw")
                        or row.get("polysilicon_capacity_annual_w_tons")
                        or None
                    ),
                    wafer_capacity_annual_gw_raw=(
                        row.get("wafer_capacity_annual_gw_raw")
                        or row.get("wafer_capacity_annual_gw")
                        or None
                    ),
                    polysilicon_capacity_annual_w_tons=safe_float(
                        row.get("polysilicon_capacity_annual_w_tons_raw")
                        or row.get("polysilicon_capacity_annual_w_tons")
                    ),
                    wafer_capacity_annual_gw=safe_float(
                        row.get("wafer_capacity_annual_gw_raw")
                        or row.get("wafer_capacity_annual_gw")
                    ),
                )
            )

    records.sort(key=lambda r: r.trade_date)
    logger.info("已读取硅业分会多晶硅与硅片月度数据 %d 行 (RAW: %s)", len(records), p)
    return records


def save_silicon_records_to_raw_csv(
    file_path: Path | str,
    records: list[SiliconWaferMonthlyRecord],
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
        "polysilicon_output_w_tons_raw": r.polysilicon_output_w_tons_raw
        or (str(r.polysilicon_output_w_tons) if r.polysilicon_output_w_tons is not None else ""),
        "polysilicon_output_yoy_raw": r.polysilicon_output_yoy_raw
        or (str(r.polysilicon_output_yoy) if r.polysilicon_output_yoy is not None else ""),
        "polysilicon_operating_rate_raw": r.polysilicon_operating_rate_raw
        or (str(r.polysilicon_operating_rate) if r.polysilicon_operating_rate is not None else ""),
        "wafer_output_gw_raw": r.wafer_output_gw_raw
        or (str(r.wafer_output_gw) if r.wafer_output_gw is not None else ""),
        "wafer_output_yoy_raw": r.wafer_output_yoy_raw
        or (str(r.wafer_output_yoy) if r.wafer_output_yoy is not None else ""),
        "wafer_operating_rate_raw": r.wafer_operating_rate_raw
        or (str(r.wafer_operating_rate) if r.wafer_operating_rate is not None else ""),
        "polysilicon_inventory_w_tons_raw": r.polysilicon_inventory_w_tons_raw
        or (
            str(r.polysilicon_inventory_w_tons)
            if r.polysilicon_inventory_w_tons is not None
            else ""
        ),
        "polysilicon_capacity_annual_w_tons_raw": r.polysilicon_capacity_annual_w_tons_raw
        or (
            str(r.polysilicon_capacity_annual_w_tons)
            if r.polysilicon_capacity_annual_w_tons is not None
            else ""
        ),
        "wafer_capacity_annual_gw_raw": r.wafer_capacity_annual_gw_raw
        or (str(r.wafer_capacity_annual_gw) if r.wafer_capacity_annual_gw is not None else ""),
        "source": r.source,
        "source_url": r.source_url,
        "release_date": r.release_date.isoformat() if r.release_date else "",
        "data_status": r.data_status,
        "collected_at": r.collected_at or now_utc_iso(),
        "raw_content_sha256": r.raw_content_sha256 or "",
        "raw_snapshot_path": r.raw_snapshot_path or "",
        "capacity_raw_content_sha256": r.capacity_raw_content_sha256 or "",
        "capacity_raw_snapshot_path": r.capacity_raw_snapshot_path or "",
    }


def load_capacity_row(year: int, raw_dir: Path | str) -> tuple[dict[str, str] | None, Path | None]:
    """读取指定年度产能记录并返回其实际 RAW 文件路径。"""
    raw_root = Path(raw_dir)
    paths = PowerRawPaths(raw_root)
    candidates = (paths.silicon_capacity_annual_csv,) + tuple(
        raw_root / rel_path for rel_path in CAPACITY_RAW_CANDIDATES
    )
    seen: set[Path] = set()
    for capacity_csv in candidates:
        if capacity_csv in seen:
            continue
        seen.add(capacity_csv)
        if not capacity_csv.exists():
            continue
        with capacity_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if safe_int(row.get("year")) == year:
                    return row, capacity_csv
    return None, None


def get_polysilicon_annual_capacity(
    year: int,
    raw_dir: Path | str = "data/raw/industry",
) -> float | None:
    """从 RAW 年度产能事实表读取中国多晶硅名义年化产能 (万吨/年)。"""
    row, _ = load_capacity_row(year, raw_dir)
    return safe_float(row.get("polysilicon_capacity_w_tons")) if row else None


def get_wafer_annual_capacity(
    year: int,
    raw_dir: Path | str = "data/raw/industry",
) -> float | None:
    """从 RAW 年度产能事实表读取硅片名义年化产能 (GW/年)。"""
    row, _ = load_capacity_row(year, raw_dir)
    return safe_float(row.get("wafer_capacity_gw")) if row else None


__all__ = [
    "ACTUAL_SILICON_DATA_STATUSES",
    "get_polysilicon_annual_capacity",
    "get_wafer_annual_capacity",
    "load_capacity_row",
    "load_silicon_records_from_raw_csv",
    "records_from_online",
    "safe_float",
    "save_silicon_records_to_raw_csv",
]
