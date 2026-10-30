"""基础化工月度事实采集器。

spot_mdi/spot_tio2 月度参考价改从本地 chemical_spot_price.parquet
（MDI/TiO2 现货出厂基准价日频序列）按月聚合，不再走 mdi/tio2 频道爬虫。
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.chemicals.models import ChemicalMarketRecord
from stock_data.fetcher.industry.chemicals.parsers.raw_csv import (
    CHEMICALS_CSV_FIELDNAMES,
    load_chemicals_raw_csv,
    save_chemicals_raw_csv,
)
from stock_data.fetcher.industry.chemicals.paths import ChemicalsRawPaths
from stock_data.fetcher.industry.chemicals.quality import validate_chemical_market_records
from stock_data.fetcher.industry.common import get_month_end_date, now_utc_iso, parse_month_string
from stock_data.fetcher.industry.contracts import IndustryCollectionResult

logger = logging.getLogger(__name__)

_SPOT_REFERENCE_SYMBOLS = ("MDI", "TiO2")
_SPOT_REFERENCE_FILE = "chemical_spot_price.parquet"


class ChemicalsCollector:
    """读取 NBS/交易所历史 RAW，并从现货基准表派生 MDI/TiO2 月度参考价。"""

    def __init__(
        self,
        raw_dir: Path | str,
        curated_dir: Path | str | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.chem_dir = self.raw_dir / "chemicals"
        if curated_dir is None:
            # 运行约定: data/raw/industry <-> data/curated/industry
            curated_dir = Path(self.raw_dir).parent.parent / "curated" / "industry"
        self.curated_dir = Path(curated_dir)
        self.collection_errors: list[str] = []
        self.fetched_periods: set[str] = set()
        self.cached_periods: set[str] = set()
        self.missing_periods: set[str] = set()

    def collect(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
        as_of_date: date | None = None,
    ) -> list[ChemicalMarketRecord]:
        """读取历史事实并按月合并现货基准表派生的 MDI/钛白粉参考价。"""
        self.collection_errors = []
        self.fetched_periods = set()
        self.cached_periods = set()
        self.missing_periods = set()
        self.chem_dir.mkdir(parents=True, exist_ok=True)
        paths = ChemicalsRawPaths(self.raw_dir)
        csv_file = paths.market_csv
        records = self.load_from_raw_csv(csv_file)
        by_month = {record.report_month: record for record in records}

        spot_by_month = _load_spot_reference_prices(self.curated_dir)
        for report_month, spot_ref in spot_by_month.items():
            by_month[report_month] = self._merge_live_prices(by_month.get(report_month), spot_ref)
            self.cached_periods.add(report_month)

        all_records = sorted(by_month.values(), key=lambda record: record.trade_date)
        requested_records = [
            record
            for record in all_records
            if (start_date is None or record.trade_date >= start_date)
            and (end_date is None or record.trade_date <= end_date)
        ]
        valid_records, validation_errors = validate_chemical_market_records(
            requested_records,
            as_of_date=as_of_date,
        )
        self.collection_errors.extend(validation_errors)
        if all_records:
            # 保留原始事实快照；不合格记录只阻断 Curated，不被静默抹除。
            self.save_to_raw_csv(csv_file, all_records)
        requested_months = _requested_months(start_date, end_date)
        covered_months = {record.report_month for record in valid_records}
        self.missing_periods = requested_months - covered_months
        self.cached_periods.update(covered_months - self.fetched_periods)
        return valid_records

    def collect_result(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> IndustryCollectionResult:
        """采集月度事实并返回统一的缓存、缺口和质量状态。"""
        records = self.collect(
            force=force,
            start_date=start_date,
            end_date=end_date,
            as_of_date=date.today(),
        )
        missing = tuple(sorted(self.missing_periods))
        errors = tuple(self.collection_errors)
        if not records and missing:
            status = "MISSING_RANGE"
        elif errors and not records:
            status = "FAILED"
        elif errors or missing:
            status = "PARTIAL"
        elif self.fetched_periods:
            status = "SUCCESS"
        elif records:
            status = "NO_CHANGE"
        else:
            status = "EMPTY"
        return IndustryCollectionResult(
            records,
            status=status,
            fetched_periods=tuple(sorted(self.fetched_periods)),
            cached_periods=tuple(sorted(self.cached_periods)),
            missing_periods=missing,
            errors=errors,
            updated=bool(self.fetched_periods),
        )

    def save_to_raw_csv(self, file_path: Path | str, records: list[ChemicalMarketRecord]) -> None:
        """保存化工月度 RAW CSV。"""
        save_chemicals_raw_csv(file_path, records)

    def load_from_raw_csv(self, file_path: Path | str) -> list[ChemicalMarketRecord]:
        """读取化工月度 RAW CSV。"""
        return load_chemicals_raw_csv(file_path)

    @staticmethod
    def _merge_live_prices(
        existing: ChemicalMarketRecord | None, live: dict[str, Any]
    ) -> ChemicalMarketRecord:
        report_month = str(live["report_month"])
        year, month = parse_month_string(report_month)
        trade_date = get_month_end_date(year, month)
        now_iso = now_utc_iso()
        mdi_price = _as_float(live.get("mdi_price_cny"))
        tio2_price = _as_float(live.get("tio2_price_cny"))
        release_date = _as_date(live.get("release_date"))

        record = existing or ChemicalMarketRecord(
            report_month=report_month,
            trade_date=trade_date,
        )
        merged = replace(
            record,
            report_month=report_month,
            trade_date=trade_date,
            unit="mixed",
            source=record.source or str(live.get("source") or ""),
            source_url=record.source_url or str(live.get("source_url") or ""),
            release_date=record.release_date or release_date,
            data_status=str(live.get("data_status") or "actual"),
            collected_at=now_iso,
            raw_content_sha256=str(live.get("raw_content_sha256") or ""),
            raw_snapshot_path=str(live.get("raw_snapshot_path") or ""),
        )
        if mdi_price is not None:
            merged = replace(
                merged,
                spot_mdi_price_cny=mdi_price,
                mdi_source=str(live.get("mdi_source") or live.get("source") or ""),
                mdi_source_url=str(live.get("mdi_source_url") or live.get("source_url") or ""),
                mdi_release_date=_as_date(live.get("mdi_release_date")) or release_date,
                mdi_raw_content_sha256=str(live.get("mdi_raw_content_sha256") or ""),
                mdi_raw_snapshot_path=str(live.get("mdi_raw_snapshot_path") or ""),
            )
        if tio2_price is not None:
            merged = replace(
                merged,
                spot_tio2_price_cny=tio2_price,
                tio2_source=str(live.get("tio2_source") or live.get("source") or ""),
                tio2_source_url=str(live.get("tio2_source_url") or live.get("source_url") or ""),
                tio2_release_date=_as_date(live.get("tio2_release_date")) or release_date,
                tio2_raw_content_sha256=str(live.get("tio2_raw_content_sha256") or ""),
                tio2_raw_snapshot_path=str(live.get("tio2_raw_snapshot_path") or ""),
            )
        return merged


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _requested_months(
    start_date: date | None,
    end_date: date | None,
) -> set[str]:
    if start_date is None and end_date is None:
        return set()
    cursor = (start_date or end_date).replace(day=1)  # type: ignore[union-attr]
    end = (end_date or start_date).replace(day=1)  # type: ignore[union-attr]
    months: set[str] = set()
    while cursor <= end:
        months.add(cursor.strftime("%Y-%m"))
        cursor = (
            cursor.replace(year=cursor.year + 1, month=1)
            if cursor.month == 12
            else cursor.replace(month=cursor.month + 1)
        )
    return months


def _load_spot_reference_prices(curated_dir: Path) -> dict[str, dict[str, Any]]:
    """从 chemical_spot_price.parquet 按月聚合 MDI/钛白粉现货参考价。

    返回结构与旧 mdi/tio2 频道爬虫的 live dict 兼容，便于复用
    :meth:`ChemicalsCollector._merge_live_prices` 的字段级血统合并。
    """
    spot_file = curated_dir / _SPOT_REFERENCE_FILE
    if not spot_file.exists():
        return {}
    try:
        df = pl.read_parquet(spot_file)
    except Exception as e:
        logger.debug("读取现货基准表失败 [%s]: %s", spot_file, e)
        return {}
    if df.is_empty():
        return {}
    df = df.filter(pl.col("symbol").is_in(_SPOT_REFERENCE_SYMBOLS)).sort(["symbol", "trade_date"])
    if df.is_empty():
        return {}

    by_month: dict[str, dict[str, Any]] = {}
    for row in df.iter_rows(named=True):
        symbol = str(row["symbol"])
        month = row["trade_date"].strftime("%Y-%m")
        key = "mdi" if symbol == "MDI" else "tio2"
        ref = by_month.setdefault(
            month,
            {
                "report_month": month,
                "source": "100ppi/Spot_Benchmark",
                "source_url": "",
                "release_date": None,
                "data_status": "cached",
                "collected_at": now_utc_iso(),
                "raw_content_sha256": "",
                "raw_snapshot_path": "",
            },
        )
        ref[f"{key}_price_cny"] = float(row["spot_price_cny"])
        ref[f"{key}_source"] = "100ppi"
        ref[f"{key}_source_url"] = str(row.get("source_url") or "")
        ref[f"{key}_release_date"] = row.get("release_date") or row["trade_date"]
        ref[f"{key}_raw_content_sha256"] = str(row.get("raw_content_sha256") or "")
        ref[f"{key}_raw_snapshot_path"] = str(row.get("raw_snapshot_path") or "")
        if ref["release_date"] is None:
            ref["release_date"] = ref[f"{key}_release_date"]
    # 取每个(品种, 月份)的最后一条(最新 trade_date)作为该月参考价
    return {
        month: ref
        for month, ref in by_month.items()
        if ref.get("mdi_price_cny") is not None or ref.get("tio2_price_cny") is not None
    }


__all__ = [
    "CHEMICALS_CSV_FIELDNAMES",
    "ChemicalsCollector",
    "load_chemicals_raw_csv",
    "save_chemicals_raw_csv",
]
