"""航运 RAW CSV 快照读写。"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.shipping.models import ShippingIndicesRecord

logger = logging.getLogger(__name__)

SHIPPING_CSV_FIELDNAMES = [
    "trade_date",
    "bdi_index",
    "bdti_index",
    "bcti_index",
    "scfi_index",
    "bdi_ma200_bias",
    "bdti_ma200_bias",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


def save_shipping_raw_csv(records: list[ShippingIndicesRecord], path: Path) -> None:
    """持久化 RAW 快照 CSV。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SHIPPING_CSV_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "trade_date": r.trade_date.isoformat(),
                    "bdi_index": r.bdi_index if r.bdi_index is not None else "",
                    "bdti_index": r.bdti_index if r.bdti_index is not None else "",
                    "bcti_index": r.bcti_index if r.bcti_index is not None else "",
                    "scfi_index": r.scfi_index if r.scfi_index is not None else "",
                    "bdi_ma200_bias": r.bdi_ma200_bias if r.bdi_ma200_bias is not None else "",
                    "bdti_ma200_bias": r.bdti_ma200_bias if r.bdti_ma200_bias is not None else "",
                    "unit": r.unit,
                    "source": r.source,
                    "source_url": r.source_url,
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status,
                    "collected_at": r.collected_at,
                }
            )
    logger.info("已保存真实航运运价 RAW 快照: %s (共 %d 行)", path, len(records))


def load_shipping_raw_records(file_path: Path | str) -> list[ShippingIndicesRecord]:
    """从航运 RAW 快照 CSV 中读取并标准化。"""
    p = Path(file_path)
    if not p.exists():
        return []

    records: list[ShippingIndicesRecord] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t_date = date.fromisoformat(row["trade_date"].strip())
            records.append(
                ShippingIndicesRecord(
                    trade_date=t_date,
                    bdi_index=_safe_float(row.get("bdi_index")),
                    bdti_index=_safe_float(row.get("bdti_index")),
                    bcti_index=_safe_float(row.get("bcti_index")),
                    scfi_index=_safe_float(row.get("scfi_index")),
                    bdi_ma200_bias=_safe_float(row.get("bdi_ma200_bias")),
                    bdti_ma200_bias=_safe_float(row.get("bdti_ma200_bias")),
                    unit=row.get("unit") or "index_points",
                    source=row.get("source") or "Baltic_Exchange",
                    source_url=row.get("source_url") or "",
                    release_date=date.fromisoformat(row["release_date"])
                    if row.get("release_date")
                    else None,
                    data_status=row.get("data_status") or "actual",
                    collected_at=row.get("collected_at") or now_utc_iso(),
                )
            )
    records.sort(key=lambda r: r.trade_date)
    return records


def _safe_float(val: str | None) -> float | None:
    if not val or not val.strip():
        return None
    try:
        return float(val.strip())
    except (ValueError, TypeError):
        return None


__all__ = ["SHIPPING_CSV_FIELDNAMES", "load_shipping_raw_records", "save_shipping_raw_csv"]
