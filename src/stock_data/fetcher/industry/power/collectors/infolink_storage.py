"""InfoLink 光伏价格 RAW CSV 读写与价格派生。"""

import csv
from dataclasses import replace
from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.power.lineage import file_lineage
from stock_data.fetcher.industry.power.models import SolarPriceChainRecord
from stock_data.fetcher.industry.power.parsers.infolink import INFOLINK_SPOT_PRICE_URL
from stock_data.fetcher.industry.power.schemas import SOLAR_PRICE_CHAIN_RAW_SCHEMA

PV_PRICE_FIELDNAMES = list(SOLAR_PRICE_CHAIN_RAW_SCHEMA)


def _safe_float(val: str | None) -> float | None:
    if not val or not str(val).strip() or str(val).strip() in ("nan", "None", ""):
        return None
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return None


def load_pv_price_raw_csv(file_path: Path | str) -> list[SolarPriceChainRecord]:
    """从 RAW CSV 文件读取并标准化记录。"""
    p = Path(file_path)
    if not p.exists():
        return []

    raw_root = p.parents[2] if p.parent.name == "infolink" else p.parent.parent
    content_hash, snapshot_ref = file_lineage(p, raw_root)
    records: list[SolarPriceChainRecord] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rep_date_str = row["report_date"].strip()
            t_date = date.fromisoformat(row["trade_date"].strip() or rep_date_str)
            rel_d = None
            if row.get("release_date"):
                try:
                    rel_d = date.fromisoformat(row["release_date"].strip())
                except ValueError:
                    pass

            records.append(
                SolarPriceChainRecord(
                    report_date=rep_date_str,
                    trade_date=t_date,
                    polysilicon_price_cny_kg=(
                        _safe_float(row.get("polysilicon_price_cny_kg_raw"))
                        if row.get("polysilicon_price_cny_kg_raw")
                        else _safe_float(row.get("polysilicon_price_cny_kg"))
                    ),
                    wafer_price_cny_piece=(
                        _safe_float(row.get("wafer_price_cny_piece_raw"))
                        if row.get("wafer_price_cny_piece_raw")
                        else _safe_float(row.get("wafer_price_cny_piece"))
                    ),
                    cell_price_cny_watt=(
                        _safe_float(row.get("cell_price_cny_watt_raw"))
                        if row.get("cell_price_cny_watt_raw")
                        else _safe_float(row.get("cell_price_cny_watt"))
                    ),
                    module_price_cny_watt=(
                        _safe_float(row.get("module_price_cny_watt_raw"))
                        if row.get("module_price_cny_watt_raw")
                        else _safe_float(row.get("module_price_cny_watt"))
                    ),
                    module_price_yoy=_safe_float(row.get("module_price_yoy")),
                    module_price_mom=_safe_float(row.get("module_price_mom")),
                    price_cycle_stage=row.get("price_cycle_stage") or None,
                    unit=row.get("unit") or "cny_per_unit",
                    source=row.get("source") or "InfoLink Consulting",
                    source_url=row.get("source_url") or INFOLINK_SPOT_PRICE_URL,
                    release_date=rel_d,
                    data_status=row.get("data_status") or "actual",
                    collected_at=row.get("collected_at") or now_utc_iso(),
                    polysilicon_price_cny_kg_raw=(
                        row.get("polysilicon_price_cny_kg_raw")
                        or row.get("polysilicon_price_cny_kg")
                        or None
                    ),
                    wafer_price_cny_piece_raw=(
                        row.get("wafer_price_cny_piece_raw")
                        or row.get("wafer_price_cny_piece")
                        or None
                    ),
                    cell_price_cny_watt_raw=(
                        row.get("cell_price_cny_watt_raw") or row.get("cell_price_cny_watt") or None
                    ),
                    module_price_cny_watt_raw=(
                        row.get("module_price_cny_watt_raw")
                        or row.get("module_price_cny_watt")
                        or None
                    ),
                    raw_content_sha256=row.get("raw_content_sha256") or content_hash,
                    raw_snapshot_path=row.get("raw_snapshot_path") or snapshot_ref,
                )
            )

    records.sort(key=lambda r: r.trade_date)
    return records


def save_pv_price_raw_csv(file_path: Path | str, records: list[SolarPriceChainRecord]) -> None:
    """持久化标准化记录至 RAW CSV 快照。"""
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PV_PRICE_FIELDNAMES)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "report_date": r.report_date,
                    "trade_date": r.trade_date.isoformat(),
                    "polysilicon_price_cny_kg_raw": r.polysilicon_price_cny_kg_raw
                    or (
                        str(r.polysilicon_price_cny_kg)
                        if r.polysilicon_price_cny_kg is not None
                        else ""
                    ),
                    "wafer_price_cny_piece_raw": r.wafer_price_cny_piece_raw
                    or (
                        str(r.wafer_price_cny_piece) if r.wafer_price_cny_piece is not None else ""
                    ),
                    "cell_price_cny_watt_raw": r.cell_price_cny_watt_raw
                    or (str(r.cell_price_cny_watt) if r.cell_price_cny_watt is not None else ""),
                    "module_price_cny_watt_raw": r.module_price_cny_watt_raw
                    or (
                        str(r.module_price_cny_watt) if r.module_price_cny_watt is not None else ""
                    ),
                    "source": r.source or "InfoLink Consulting",
                    "source_url": r.source_url or INFOLINK_SPOT_PRICE_URL,
                    "release_date": r.release_date.isoformat() if r.release_date else "",
                    "data_status": r.data_status or "actual",
                    "collected_at": r.collected_at or now_utc_iso(),
                    "raw_content_sha256": r.raw_content_sha256 or "",
                    "raw_snapshot_path": r.raw_snapshot_path or "",
                }
            )


def compute_pv_price_derivatives(
    records: list[SolarPriceChainRecord],
) -> list[SolarPriceChainRecord]:
    """计算组件价格周环比与 52 周同比派生特征。"""
    updated: list[SolarPriceChainRecord] = []
    for i, rec in enumerate(records):
        mom: float | None = None
        if (
            i > 0
            and records[i - 1].module_price_cny_watt is not None
            and rec.module_price_cny_watt is not None
        ):
            prev_price = records[i - 1].module_price_cny_watt
            if prev_price and prev_price > 0:
                mom = round((rec.module_price_cny_watt - prev_price) / prev_price, 4)

        yoy: float | None = None
        if (
            i >= 52
            and records[i - 52].module_price_cny_watt is not None
            and rec.module_price_cny_watt is not None
        ):
            previous_year_price = records[i - 52].module_price_cny_watt
            if previous_year_price and previous_year_price > 0:
                yoy = round(
                    (rec.module_price_cny_watt - previous_year_price) / previous_year_price,
                    4,
                )
        updated.append(replace(rec, module_price_yoy=yoy, module_price_mom=mom))
    return updated


__all__ = [
    "compute_pv_price_derivatives",
    "load_pv_price_raw_csv",
    "save_pv_price_raw_csv",
]
