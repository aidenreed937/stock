"""化工市场 RAW CSV 的读写解析。"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.chemicals.models import ChemicalMarketRecord
from stock_data.fetcher.industry.common import get_month_end_date, now_utc_iso, parse_month_string

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
    "spot_soda_ash_price_cny",
    "spot_pta_price_cny",
    "spot_urea_price_cny",
    "spot_mdi_price_cny",
    "spot_tio2_price_cny",
    "spot_refrigerant_r32_price_cny",
    "soda_ash_operating_rate",
    "pta_operating_rate",
    "chemical_social_inventory",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
    "raw_content_sha256",
    "raw_snapshot_path",
    "mdi_source",
    "mdi_source_url",
    "mdi_release_date",
    "mdi_raw_content_sha256",
    "mdi_raw_snapshot_path",
    "tio2_source",
    "tio2_source_url",
    "tio2_release_date",
    "tio2_raw_content_sha256",
    "tio2_raw_snapshot_path",
]


def save_chemicals_raw_csv(file_path: Path | str, records: list[ChemicalMarketRecord]) -> None:
    """持久化标准化记录至 RAW CSV 快照。"""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CHEMICALS_CSV_FIELDNAMES)
        writer.writeheader()
        for record in records:
            writer.writerow(_record_to_csv(record))


def load_chemicals_raw_csv(file_path: Path | str) -> list[ChemicalMarketRecord]:
    """从 RAW CSV 文件读取并标准化记录。"""
    path = Path(file_path)
    if not path.exists():
        return []

    records: list[ChemicalMarketRecord] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            month = row["report_month"].strip()
            year, month_number = parse_month_string(month)
            trade_date = get_month_end_date(year, month_number)
            mdi_source = row.get("mdi_source") or ""
            mdi_price = _safe_float(row.get("spot_mdi_price_cny") or row.get("mdi_price_cny"))
            if mdi_price is not None and not mdi_source:
                logger.warning("化工市场旧 RAW 缺少 MDI 字段级来源，拒绝载入该价格: %s", month)
                mdi_price = None
            tio2_source = row.get("tio2_source") or ""
            tio2_price = _safe_float(row.get("spot_tio2_price_cny") or row.get("tio2_price_cny"))
            if tio2_price is not None and not tio2_source:
                logger.warning("化工市场旧 RAW 缺少 TiO2 字段级来源，拒绝载入该价格: %s", month)
                tio2_price = None
            records.append(
                ChemicalMarketRecord(
                    report_month=month,
                    trade_date=trade_date,
                    soda_ash_production=_safe_float(row.get("soda_ash_production")),
                    caustic_soda_production=_safe_float(row.get("caustic_soda_production")),
                    synthetic_fiber_production=_safe_float(row.get("synthetic_fiber_production")),
                    chemical_fertilizer_production=_safe_float(
                        row.get("chemical_fertilizer_production")
                    ),
                    plastics_production=_safe_float(row.get("plastics_production")),
                    plate_glass_production=_safe_float(row.get("plate_glass_production")),
                    spot_soda_ash_price_cny=_safe_float(
                        row.get("spot_soda_ash_price_cny") or row.get("soda_ash_price_cny")
                    ),
                    spot_pta_price_cny=_safe_float(
                        row.get("spot_pta_price_cny") or row.get("pta_price_cny")
                    ),
                    spot_urea_price_cny=_safe_float(
                        row.get("spot_urea_price_cny") or row.get("urea_price_cny")
                    ),
                    spot_mdi_price_cny=mdi_price,
                    spot_tio2_price_cny=tio2_price,
                    spot_refrigerant_r32_price_cny=_safe_float(
                        row.get("spot_refrigerant_r32_price_cny")
                        or row.get("refrigerant_r32_price_cny")
                    ),
                    soda_ash_operating_rate=_safe_float(row.get("soda_ash_operating_rate")),
                    pta_operating_rate=_safe_float(row.get("pta_operating_rate")),
                    chemical_social_inventory=_safe_float(row.get("chemical_social_inventory")),
                    unit=row.get("unit") or "mixed",
                    source=row.get("source") or "",
                    source_url=row.get("source_url") or "",
                    release_date=_safe_date(row.get("release_date")),
                    data_status=row.get("data_status") or "actual",
                    collected_at=row.get("collected_at") or now_utc_iso(),
                    raw_content_sha256=row.get("raw_content_sha256") or "",
                    raw_snapshot_path=row.get("raw_snapshot_path") or "",
                    mdi_source=mdi_source,
                    mdi_source_url=row.get("mdi_source_url") or "",
                    mdi_release_date=_safe_date(row.get("mdi_release_date")),
                    mdi_raw_content_sha256=row.get("mdi_raw_content_sha256") or "",
                    mdi_raw_snapshot_path=row.get("mdi_raw_snapshot_path") or "",
                    tio2_source=tio2_source,
                    tio2_source_url=row.get("tio2_source_url") or "",
                    tio2_release_date=_safe_date(row.get("tio2_release_date")),
                    tio2_raw_content_sha256=row.get("tio2_raw_content_sha256") or "",
                    tio2_raw_snapshot_path=row.get("tio2_raw_snapshot_path") or "",
                )
            )
    records.sort(key=lambda record: record.trade_date)
    return records


def _record_to_csv(record: ChemicalMarketRecord) -> dict[str, object]:
    values = {
        field: getattr(record, field)
        for field in (
            "soda_ash_production",
            "caustic_soda_production",
            "synthetic_fiber_production",
            "chemical_fertilizer_production",
            "plastics_production",
            "plate_glass_production",
            "spot_soda_ash_price_cny",
            "spot_pta_price_cny",
            "spot_urea_price_cny",
            "spot_mdi_price_cny",
            "spot_tio2_price_cny",
            "spot_refrigerant_r32_price_cny",
            "soda_ash_operating_rate",
            "pta_operating_rate",
            "chemical_social_inventory",
        )
    }
    row: dict[str, object] = {
        "report_month": record.report_month,
        "trade_date": record.trade_date.isoformat(),
        **{field: value if value is not None else "" for field, value in values.items()},
        "unit": record.unit or "mixed",
        "source": record.source,
        "source_url": record.source_url,
        "release_date": record.release_date.isoformat() if record.release_date else "",
        "data_status": record.data_status or "actual",
        "collected_at": record.collected_at or now_utc_iso(),
        "raw_content_sha256": record.raw_content_sha256,
        "raw_snapshot_path": record.raw_snapshot_path,
        "mdi_source": record.mdi_source,
        "mdi_source_url": record.mdi_source_url,
        "mdi_release_date": record.mdi_release_date.isoformat() if record.mdi_release_date else "",
        "mdi_raw_content_sha256": record.mdi_raw_content_sha256,
        "mdi_raw_snapshot_path": record.mdi_raw_snapshot_path,
        "tio2_source": record.tio2_source,
        "tio2_source_url": record.tio2_source_url,
        "tio2_release_date": record.tio2_release_date.isoformat()
        if record.tio2_release_date
        else "",
        "tio2_raw_content_sha256": record.tio2_raw_content_sha256,
        "tio2_raw_snapshot_path": record.tio2_raw_snapshot_path,
    }
    return row


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _safe_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


__all__ = [
    "CHEMICALS_CSV_FIELDNAMES",
    "load_chemicals_raw_csv",
    "save_chemicals_raw_csv",
]
