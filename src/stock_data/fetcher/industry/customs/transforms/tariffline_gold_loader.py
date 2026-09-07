"""Tariffline RAW 快照读取与 HS8 明细聚合。"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.customs.models import CustomsTradeRecord
from stock_data.fetcher.industry.customs.parsers.catalog import (
    load_hs_catalog,
    parse_comtrade_items,
)

logger = logging.getLogger(__name__)


@dataclass
class _RawAggregate:
    """按 HS8、月份和方向汇总 Tariffline partner 明细。"""

    item: dict[str, Any]
    value: float = 0.0
    quantity: float = 0.0
    quantity_complete: bool = True
    units: set[str] = field(default_factory=set)
    snapshot_paths: set[str] = field(default_factory=set)
    content_hashes: set[str] = field(default_factory=set)


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text or text.lower() in {"none", "nan", "null"}:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize_code(value: Any) -> str:
    return str(value or "").strip().replace(".", "").replace(" ", "")


def _normalize_period(value: Any) -> str:
    text = str(value or "").strip().replace("-", "")
    return text if len(text) == 6 and text.isdigit() else ""


def _normalize_flow(value: Any) -> str:
    flow = str(value or "").strip().upper()
    return flow if flow in {"M", "X"} else ""


def _raw_item_fingerprint(item: dict[str, Any]) -> str:
    """生成整行 Tariffline 明细指纹。"""
    return json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _quantity_value(item: dict[str, Any]) -> float | None:
    quantity = _parse_float(item.get("qty"))
    return quantity if quantity is not None else _parse_float(item.get("netWgt"))


def _resolve_snapshot_path(raw_dir: Path, value: Any) -> Path:
    candidate = Path(str(value or ""))
    if candidate.is_absolute() or candidate.exists():
        return candidate
    return raw_dir / candidate


def _iter_manifest_snapshots(raw_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    manifest_path = raw_dir / "tariffline_manifest.jsonl"
    if not manifest_path.exists():
        return []

    latest: dict[str, tuple[Path, dict[str, Any]]] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict) or not entry.get("snapshot_path"):
            continue
        snapshot_path = _resolve_snapshot_path(raw_dir, entry["snapshot_path"])
        latest[str(snapshot_path.resolve())] = (snapshot_path, entry)

    snapshots = [
        (path, entry)
        for path, entry in latest.values()
        if entry.get("status") == "success" and path.is_file()
    ]
    return sorted(snapshots, key=lambda item: str(item[0]))


def _load_snapshot_items(snapshot_path: Path) -> list[dict[str, Any]]:
    """读取 Parquet RAW；迁移期间兼容旧 JSON.GZ 快照。"""
    if snapshot_path.name.endswith(".parquet"):
        frame = pl.read_parquet(snapshot_path)
        if "_empty" in frame.columns:
            return []
        return frame.to_dicts()

    content = snapshot_path.read_bytes()
    payload = json.loads(gzip.decompress(content))
    items = payload.get("data", []) if isinstance(payload, dict) else payload
    return items if isinstance(items, list) else []


def load_tariffline_records_with_stats(
    raw_dir: Path | str,
    catalog_path: Path | str,
) -> tuple[list[CustomsTradeRecord], int, int]:
    """读取已成功落盘的 Tariffline 快照，并合并 partner 维度。"""
    root = Path(raw_dir)
    catalog_map = load_hs_catalog(catalog_path)
    snapshots = _iter_manifest_snapshots(root)
    aggregates: dict[tuple[str, str, str], _RawAggregate] = {}
    seen_raw_items: set[str] = set()
    duplicate_rows = 0
    raw_rows = 0

    for snapshot_path, entry in snapshots:
        try:
            items = _load_snapshot_items(snapshot_path)
            content_hash = str(entry.get("source_content_sha256") or "")
            if not content_hash:
                content_hash = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        except (
            OSError,
            gzip.BadGzipFile,
            json.JSONDecodeError,
            TypeError,
            UnicodeDecodeError,
            pl.exceptions.PolarsError,
        ) as exc:
            logger.warning("解析 Tariffline RAW 失败 [%s]: %s", snapshot_path, exc)
            continue

        raw_rows += len(items)
        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue
            code = _normalize_code(raw_item.get("cmdCode"))
            period = _normalize_period(raw_item.get("period"))
            flow = _normalize_flow(raw_item.get("flowCode"))
            value = _parse_float(raw_item.get("primaryValue"))
            if not code or not period or not flow or value is None:
                continue

            key = (code, period, flow)
            fingerprint = _raw_item_fingerprint(raw_item)
            if fingerprint in seen_raw_items:
                duplicate_rows += 1
                aggregate = aggregates.get(key)
                if aggregate is not None:
                    aggregate.snapshot_paths.add(str(snapshot_path))
                    aggregate.content_hashes.add(content_hash)
                continue
            seen_raw_items.add(fingerprint)
            aggregate = aggregates.get(key)
            if aggregate is None:
                aggregate = _RawAggregate(item=dict(raw_item))
                aggregates[key] = aggregate
            aggregate.value += value
            quantity = _quantity_value(raw_item)
            if quantity is None:
                aggregate.quantity_complete = False
            else:
                aggregate.quantity += quantity
            aggregate.units.add(str(raw_item.get("qtyUnitAbbr") or "").strip())
            aggregate.snapshot_paths.add(str(snapshot_path))
            aggregate.content_hashes.add(content_hash)

    if duplicate_rows:
        logger.info("Tariffline RAW 完全重复明细已跳过: %d 行", duplicate_rows)

    aggregated_items: list[dict[str, Any]] = []
    provenance: dict[tuple[str, str, str], tuple[str, str]] = {}
    for (code, period, flow), aggregate in aggregates.items():
        item = dict(aggregate.item)
        item.update({"cmdCode": code, "period": period, "flowCode": flow})
        item["primaryValue"] = aggregate.value
        units = {unit for unit in aggregate.units if unit}
        if aggregate.quantity_complete and len(aggregate.units) <= 1:
            item["qty"] = aggregate.quantity
            item["netWgt"] = None
            if units:
                item["qtyUnitAbbr"] = next(iter(units))
        else:
            item["qty"] = None
            item["netWgt"] = None
            item["qtyUnitAbbr"] = next(iter(units)) if len(units) == 1 else "mixed"
        aggregated_items.append(item)
        provenance[(code, period, flow)] = (
            ";".join(sorted(aggregate.snapshot_paths)),
            ";".join(sorted(aggregate.content_hashes)),
        )

    records: list[CustomsTradeRecord] = []
    for record in parse_comtrade_items(aggregated_items, catalog_map):
        flow = "M" if record.trade_direction == "import" else "X"
        snapshot_ref, content_hash = provenance.get(
            (record.hs_code, record.report_month.replace("-", ""), flow), ("", "")
        )
        records.append(
            replace(record, raw_snapshot_path=snapshot_ref, raw_content_sha256=content_hash)
        )
    records.sort(key=lambda record: (record.report_month, record.hs_code, record.trade_direction))
    return records, len(snapshots), raw_rows


def load_tariffline_records(
    raw_dir: Path | str,
    catalog_path: Path | str = "config/data/customs/hs_codes_catalog.csv",
) -> list[CustomsTradeRecord]:
    """加载 Tariffline HS8 明细。"""
    records, _, _ = load_tariffline_records_with_stats(raw_dir, catalog_path)
    return records


__all__ = ["load_tariffline_records", "load_tariffline_records_with_stats"]
