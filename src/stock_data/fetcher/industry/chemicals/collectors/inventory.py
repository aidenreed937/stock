"""化工期货注册仓单库存采集器（本地 RAW 优先，可选郑商所官方在线补拉）。

默认只消费本地 RAW CSV（``chemicals/futures_inventory/{symbol}.csv``），
不发起网络请求；``enable_online=True`` 时按请求窗口直连郑商所
DFSStaticFiles 仓单日报（FutureDataWhsheet.xls|xlsx，缓存优先）补拉缺失日期，
再经由 2-Tier ETL 物化 Curated。历史全量回放仍可用
``scripts/backfill_czce_futures_inventory.py``（复用本采集器的 backfill_raw）。
RAW 按品种 CSV 保存，缺失范围如实上报，不联网补数、不伪造（除非显式打开在线模式）。
"""

from __future__ import annotations

import csv
import hashlib
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.chemicals.collectors.official import (
    build_inventory_record,
    czce_trading_dates,
    download_czce_inventory_file,
    parse_czce_inventory_frame,
    parse_dce_inventory_text,
    snapshot_ref,
)
from stock_data.fetcher.industry.chemicals.schemas import (
    FUTURES_INVENTORY_COLLECTION_SCHEMA,
    FUTURES_INVENTORY_RAW_SCHEMA,
    FUTURES_INVENTORY_SCHEMA,
)
from stock_data.fetcher.industry.chemicals.transforms.inventory import (
    build_futures_inventory_curated_frame,
    build_futures_inventory_raw_frame,
)
from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.contracts import IndustryFrameResult

logger = logging.getLogger(__name__)

# 核心化工与大宗工业品映射表
CHEMICAL_FUTURES_SYMBOLS = {
    "SA": {"name": "纯碱", "industry_code": "220200", "unit": "contracts", "exchange": "CZCE"},
    "SH": {"name": "烧碱", "industry_code": "220200", "unit": "contracts", "exchange": "CZCE"},
    "TA": {"name": "PTA", "industry_code": "220400", "unit": "contracts", "exchange": "CZCE"},
    "UR": {"name": "尿素", "industry_code": "220800", "unit": "contracts", "exchange": "CZCE"},
    "MA": {"name": "甲醇", "industry_code": "220300", "unit": "contracts", "exchange": "CZCE"},
    "PP": {"name": "聚丙烯", "industry_code": "220500", "unit": "contracts", "exchange": "DCE"},
    "L": {"name": "塑料", "industry_code": "220500", "unit": "contracts", "exchange": "DCE"},
    "FG": {"name": "玻璃", "industry_code": "220200", "unit": "contracts", "exchange": "CZCE"},
    "EG": {"name": "乙二醇", "industry_code": "220400", "unit": "contracts", "exchange": "DCE"},
    "V": {"name": "聚氯乙烯", "industry_code": "220200", "unit": "contracts", "exchange": "DCE"},
    "EB": {"name": "苯乙烯", "industry_code": "220400", "unit": "contracts", "exchange": "DCE"},
}

# 交易所官方来源标签与默认入口（仅作为本地 RAW 行缺失 source 时的回退）
_OFFICIAL_SOURCE_TAGS = {
    "CZCE": "Exchange_Official/CZCE",
    "DCE": "Exchange_Official/DCE",
    "SHFE": "Exchange_Official/SHFE",
    "INE": "Exchange_Official/INE",
}

_OFFICIAL_SOURCE_URLS = {
    "CZCE": "https://www.czce.com.cn/",
    "DCE": "https://www.dce.com.cn/",
    "SHFE": "https://www.shfe.com.cn/",
    "INE": "https://www.ine.cn/",
}


def _official_source_tag(exchange: str) -> str:
    return _OFFICIAL_SOURCE_TAGS.get(exchange.upper(), f"Exchange_Official/{exchange}")


def _official_source_url(exchange: str) -> str:
    return _OFFICIAL_SOURCE_URLS.get(exchange.upper(), "https://www.czce.com.cn/")


def _read_symbol_raw_csv(inv_dir: Path, symbol: str) -> dict[str, dict[str, Any]]:
    csv_path = inv_dir / f"{symbol}.csv"
    if not csv_path.exists():
        return {}

    def _flt(key: str, row: dict[str, str]) -> float | None:
        value = row.get(key)
        return float(value) if value and value.strip() else None

    exchange = str(CHEMICAL_FUTURES_SYMBOLS.get(symbol, {}).get("exchange") or "unknown")
    source = _official_source_tag(exchange)
    source_url = _official_source_url(exchange)
    records: dict[str, dict[str, Any]] = {}
    with csv_path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            date_text = row["trade_date"].strip()
            row_source = row.get("source") or source
            if row_source in {"Eastmoney", "Eastmoney/CZCE/DCE"}:
                row_source = f"Eastmoney/{exchange}"
            records[date_text] = {
                "symbol": symbol,
                "name": row.get("name")
                or CHEMICAL_FUTURES_SYMBOLS.get(symbol, {}).get("name", symbol),
                "industry_code": row.get("industry_code")
                or CHEMICAL_FUTURES_SYMBOLS.get(symbol, {}).get("industry_code", ""),
                "trade_date": date.fromisoformat(date_text),
                "inventory": _flt("inventory", row),
                "change": _flt("change", row),
                "unit": row.get("unit") or "contracts",
                "source": row_source,
                "source_url": row.get("source_url") or source_url,
                "release_date": date.fromisoformat(row["release_date"].strip())
                if row.get("release_date")
                else date.fromisoformat(date_text),
                "collected_at": row.get("collected_at") or now_utc_iso(),
                "raw_content_sha256": row.get("raw_content_sha256") or "",
                "raw_snapshot_path": row.get("raw_snapshot_path") or "",
            }
    return records


def _write_symbol_raw_csv(inv_dir: Path, symbol: str, records: dict[str, dict[str, Any]]) -> None:
    csv_path = inv_dir / f"{symbol}.csv"
    rows = sorted(records.values(), key=lambda row: row["trade_date"])
    fieldnames = [
        "trade_date",
        "symbol",
        "name",
        "industry_code",
        "inventory",
        "change",
        "unit",
        "source",
        "source_url",
        "release_date",
        "collected_at",
        "raw_content_sha256",
        "raw_snapshot_path",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "trade_date": row["trade_date"].isoformat(),
                    "symbol": row["symbol"],
                    "name": row["name"],
                    "industry_code": row["industry_code"],
                    "inventory": row["inventory"] if row["inventory"] is not None else "",
                    "change": row["change"] if row["change"] is not None else "",
                    "unit": row["unit"],
                    "source": row["source"],
                    "source_url": row["source_url"],
                    "release_date": row["release_date"].isoformat(),
                    "collected_at": row["collected_at"],
                    "raw_content_sha256": row.get("raw_content_sha256") or "",
                    "raw_snapshot_path": row.get("raw_snapshot_path") or "",
                }
            )


class FuturesInventoryCollector:
    """化工商品期货注册仓单库存采集器（默认离线，可选郑商所官方在线补拉）。"""

    def __init__(self, raw_dir: Path | str, enable_online: bool = False) -> None:
        self.raw_dir = Path(raw_dir)
        self.inv_dir = self.raw_dir / "chemicals" / "futures_inventory"
        self.inv_dir.mkdir(parents=True, exist_ok=True)
        self.enable_online = enable_online
        self.missing_periods: dict[str, tuple[tuple[str, str], ...]] = {}
        self.collection_errors: list[str] = []
        self.fetched_periods: set[str] = set()
        self.cached_periods: set[str] = set()

    def _load_symbol_raw_csv(self, symbol: str) -> dict[str, dict[str, Any]]:
        return _read_symbol_raw_csv(self.inv_dir, symbol)

    def _save_symbol_raw_csv(self, symbol: str, records: dict[str, dict[str, Any]]) -> None:
        _write_symbol_raw_csv(self.inv_dir, symbol, records)

    def collect(
        self,
        symbols: list[str] | None = None,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        """采集仓单：默认仅消费本地 RAW CSV；``enable_online=True`` 时先补拉缺失窗口。

        ``force`` 参数保留仅为兼容调用方签名；本地覆盖不足时如实写入
        ``missing_periods``，离线模式不联网补数、不伪造。
        """
        self.collection_errors = []
        self.missing_periods = {}
        self.fetched_periods = set()
        self.cached_periods = set()
        if self.enable_online and start_date is not None and end_date is not None:
            _, fetched = self.backfill_raw(start_date, end_date, download=True)
            self.fetched_periods.update(fetched)
        target_symbols = symbols or list(CHEMICAL_FUTURES_SYMBOLS.keys())
        all_records: list[dict[str, Any]] = []

        for sym in target_symbols:
            rec_dict = self._load_symbol_raw_csv(sym)

            expected_dates = _inventory_trading_dates(
                start_date,
                end_date,
                exchange=str(CHEMICAL_FUTURES_SYMBOLS.get(sym, {}).get("exchange") or ""),
            )
            calendar_unavailable = (
                start_date is not None and end_date is not None and expected_dates is None
            )
            if calendar_unavailable:
                logger.warning(f"{sym}: 无法取得可信期货交易日历，将以源端实际日期判断覆盖")
            dates = {date.fromisoformat(value) for value in rec_dict}
            trusted_local_exact = (
                calendar_unavailable
                and start_date == end_date
                and start_date is not None
                and start_date in dates
                and rec_dict[start_date.isoformat()].get("inventory") is not None
            )
            missing = (
                _missing_date_ranges(
                    dates,
                    start_date,
                    end_date,
                    expected_dates=expected_dates,
                )
                if not calendar_unavailable
                else ()
                if trusted_local_exact
                else _requested_range_marker(start_date, end_date)
                if not dates
                else ()
            )
            self.missing_periods[sym] = missing

            if start_date is not None and end_date is not None:
                period_label = f"{sym}:{start_date.isoformat()}..{end_date.isoformat()}"
                if not missing:
                    self.cached_periods.add(period_label)
            if missing and not force:
                logger.warning("期货仓单存在日期缺口 [%s]: %s", sym, missing)

            if rec_dict:
                self._save_symbol_raw_csv(sym, rec_dict)
                all_records.extend(
                    record
                    for record in rec_dict.values()
                    if (start_date is None or record["trade_date"] >= start_date)
                    and (end_date is None or record["trade_date"] <= end_date)
                )

        if not all_records:
            return pl.DataFrame(schema=FUTURES_INVENTORY_SCHEMA)

        df = (
            _inventory_collection_frame(all_records)
            .unique(subset=["symbol", "trade_date"], keep="last")
            .sort(["symbol", "trade_date"])
        )
        return df

    def backfill_raw(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        *,
        download: bool = True,
    ) -> tuple[dict[str, int], set[str]]:
        """回填郑商所化工仓单 RAW CSV（仅写 RAW，不物化 Curated）。

        ``download=True`` 时按交易日历逐日下载官方日报（缓存优先）；
        ``download=False`` 时仅回放本地 ``czce_daily`` 快照。返回 (summary, fetched)。
        """
        cache_dir = self.inv_dir / "czce_daily"
        cache_dir.mkdir(parents=True, exist_ok=True)
        czce_meta = {
            symbol: meta
            for symbol, meta in CHEMICAL_FUTURES_SYMBOLS.items()
            if meta.get("exchange") == "CZCE"
        }
        if not czce_meta:
            return {}, set()

        now_iso = now_utc_iso()
        sym_records: dict[str, list[dict[str, str]]] = {sym: [] for sym in czce_meta}
        fetched: set[str] = set()

        if download:
            dates = czce_trading_dates(start_date, end_date) or set()
            ordered = [download_czce_inventory_file(d, cache_dir) for d in sorted(dates)]
        else:
            ordered = []
            for file in sorted(cache_dir.glob("*/*.xls*")):
                stem = file.stem
                try:
                    d = date(int(stem[:4]), int(stem[4:6]), int(stem[6:8]))
                except ValueError:
                    continue
                ordered.append((d, file, file.suffix.lstrip("."), file.read_bytes()))

        for t_date, local_path, ext, content in ordered:
            if content is None or local_path is None or ext is None:
                continue
            sha = hashlib.sha256(content).hexdigest()
            rel_snap = snapshot_ref(local_path, self.raw_dir)
            parsed = parse_czce_inventory_frame(content, ext, czce_meta)
            for sym, (inv_val, chg_val) in parsed.items():
                if inv_val is None and chg_val is None:
                    continue
                sym_records[sym].append(
                    build_inventory_record(
                        sym,
                        czce_meta[sym],
                        t_date,
                        inv_val,
                        chg_val,
                        ext,
                        sha,
                        rel_snap,
                        now_iso,
                    )
                )
                fetched.add(f"{sym}:{t_date.isoformat()}")

        summary: dict[str, int] = {}
        for sym in czce_meta:
            rec_dict = self._load_symbol_raw_csv(sym)
            for record in sym_records[sym]:
                rec_dict[record["trade_date"]] = {
                    **record,
                    "trade_date": date.fromisoformat(record["trade_date"]),
                    "release_date": date.fromisoformat(record["release_date"]),
                }
            self._save_symbol_raw_csv(sym, rec_dict)
            summary[sym] = len(rec_dict)

        dce_summary, dce_fetched = self.backfill_dce_raw(start_date, end_date)
        summary.update(dce_summary)
        fetched.update(dce_fetched)
        return summary, fetched

    def backfill_dce_raw(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[dict[str, int], set[str]]:
        """回填大商所化工仓单 RAW CSV（仅从本地 dce 快照回放，不直接连外网）。

        快照默认位于 ``data/raw/industry/chemicals/futures_inventory/dce/{YYYY}/{YYYYMMDD}.*``。
        由 ``scripts/cdp/dce_cdp_automation.py`` 抓取落地。
        """
        dce_dir = self.inv_dir / "dce"
        if not dce_dir.exists():
            return {}, set()

        dce_meta = {
            symbol: meta
            for symbol, meta in CHEMICAL_FUTURES_SYMBOLS.items()
            if meta.get("exchange") == "DCE"
        }
        if not dce_meta:
            return {}, set()

        now_iso = now_utc_iso()
        sym_records: dict[str, list[dict[str, str]]] = {sym: [] for sym in dce_meta}
        fetched: set[str] = set()

        for file in sorted(dce_dir.glob("*/*")):
            if not file.is_file():
                continue
            stem = file.stem
            try:
                t_date = date(int(stem[:4]), int(stem[4:6]), int(stem[6:8]))
            except ValueError:
                continue
            if start_date is not None and t_date < start_date:
                continue
            if end_date is not None and t_date > end_date:
                continue

            content = file.read_bytes()
            if not content:
                continue
            sha = hashlib.sha256(content).hexdigest()
            rel_snap = snapshot_ref(file, self.raw_dir)
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = content.decode("gb18030", errors="replace")

            parsed = parse_dce_inventory_text(text, dce_meta)
            for sym, (inv_val, chg_val) in parsed.items():
                if inv_val is None and chg_val is None:
                    continue
                sym_records[sym].append(
                    build_inventory_record(
                        sym,
                        dce_meta[sym],
                        t_date,
                        inv_val,
                        chg_val,
                        file.suffix.lstrip(".") or "txt",
                        sha,
                        rel_snap,
                        now_iso,
                    )
                )
                fetched.add(f"{sym}:{t_date.isoformat()}")

        summary: dict[str, int] = {}
        for sym in dce_meta:
            rec_dict = self._load_symbol_raw_csv(sym)
            for record in sym_records[sym]:
                rec_dict[record["trade_date"]] = {
                    **record,
                    "trade_date": date.fromisoformat(record["trade_date"]),
                    "release_date": date.fromisoformat(record["release_date"]),
                }
            self._save_symbol_raw_csv(sym, rec_dict)
            summary[sym] = len(rec_dict)
        return summary, fetched

    def collect_result(
        self,
        symbols: list[str] | None = None,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> IndustryFrameResult:
        """采集仓单并保留缺口/错误状态，供任务 runner fail-closed 判定。"""
        frame = self.collect(
            symbols=symbols,
            force=force,
            start_date=start_date,
            end_date=end_date,
        )
        missing = tuple(
            f"{symbol}:{start}..{end}"
            for symbol, ranges in sorted(self.missing_periods.items())
            for start, end in ranges
        )
        errors = tuple(self.collection_errors)
        if frame.is_empty() and missing:
            status = "MISSING_RANGE"
        elif errors and frame.is_empty():
            status = "FAILED"
        elif errors or missing:
            status = "PARTIAL"
        elif frame.is_empty():
            status = "EMPTY"
        else:
            status = "SUCCESS"
        return IndustryFrameResult(
            frame=frame,
            status=status,
            fetched_periods=tuple(sorted(self.fetched_periods)),
            cached_periods=tuple(sorted(self.cached_periods)),
            missing_periods=missing,
            errors=errors,
            updated=bool(self.fetched_periods),
        )

    def load_from_raw(
        self,
        symbols: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        """离线读取已落盘仓单 RAW，不触发上游请求。"""
        target_symbols = symbols or list(CHEMICAL_FUTURES_SYMBOLS)
        records: list[dict[str, Any]] = []
        for symbol in target_symbols:
            records.extend(self._load_symbol_raw_csv(symbol).values())
        records = [
            record
            for record in records
            if (start_date is None or record["trade_date"] >= start_date)
            and (end_date is None or record["trade_date"] <= end_date)
        ]
        if not records:
            return pl.DataFrame(schema=FUTURES_INVENTORY_SCHEMA)
        return (
            _inventory_collection_frame(records)
            .unique(subset=["symbol", "trade_date"], keep="last")
            .sort(["symbol", "trade_date"])
            .select(list(FUTURES_INVENTORY_SCHEMA))
        )


def _inventory_collection_frame(records: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(records, schema=FUTURES_INVENTORY_COLLECTION_SCHEMA).select(
        list(FUTURES_INVENTORY_COLLECTION_SCHEMA)
    )


def _missing_date_ranges(
    dates: set[date],
    start_date: date | None,
    end_date: date | None,
    *,
    expected_dates: set[date] | None = None,
) -> tuple[tuple[str, str], ...]:
    """按工作日集合检查请求窗口缺口，避免只看首尾水位掩盖内部断档。"""
    if start_date is None or end_date is None or start_date > end_date:
        return ()

    if expected_dates is None:
        expected_dates = set()
        cursor = start_date
        while cursor <= end_date:
            if cursor.weekday() < 5:
                expected_dates.add(cursor)
            cursor += timedelta(days=1)
    missing = sorted(expected_dates - dates)

    if not missing:
        return ()
    ranges: list[tuple[str, str]] = []
    range_start = range_end = missing[0]
    for current in missing[1:]:
        if current == range_end + timedelta(days=1):
            range_end = current
            continue
        ranges.append((range_start.isoformat(), range_end.isoformat()))
        range_start = range_end = current
    ranges.append((range_start.isoformat(), range_end.isoformat()))
    return tuple(ranges)


_L2_CALENDAR_CACHE: set[date] | None = None


def _l2_trading_dates() -> set[date] | None:
    """本地回退交易日历：申万 L2 行业日频（A 股交易日历，与 CZCE 回填脚本同源）。"""
    global _L2_CALENDAR_CACHE
    if _L2_CALENDAR_CACHE is not None:
        return _L2_CALENDAR_CACHE
    l2_path = Path("data/curated/mart/industry_l2_daily.parquet")
    if not l2_path.exists():
        return None
    try:
        df = pl.read_parquet(l2_path)
        _L2_CALENDAR_CACHE = set(df["trade_date"].unique().to_list())
        return _L2_CALENDAR_CACHE
    except Exception as exc:
        logger.warning("读取 L2 交易日历失败: %s", exc)
        return None


def _inventory_trading_dates(
    start_date: date | None,
    end_date: date | None,
    *,
    exchange: str = "",
) -> set[date] | None:
    """读取交易所专属期货日历；缺失时用本地 L2 交易日历回退，仍失败才返回 None。"""
    if start_date is None or end_date is None or start_date > end_date:
        return None
    calendar_names = {
        "CZCE": ("XZCE", "CZCE"),
        "DCE": ("XDCE", "DCE"),
        "SHFE": ("XSHG_FUTURES", "SHFE"),
        "INE": ("XINE", "INE"),
    }.get(exchange.upper(), ())
    if calendar_names:
        try:
            import exchange_calendars as xcals

            for calendar_name in calendar_names:
                try:
                    sessions = xcals.get_calendar(calendar_name).sessions_in_range(
                        start_date.isoformat(), end_date.isoformat()
                    )
                    return {session.date() for session in sessions}
                except Exception:
                    continue
        except Exception as exc:
            logger.warning("读取期货仓单交易日历失败 [%s ~ %s]: %s", start_date, end_date, exc)
    l2_dates = _l2_trading_dates()
    if l2_dates is None:
        return None
    return {d for d in l2_dates if start_date <= d <= end_date}


def _requested_range_marker(
    start_date: date | None,
    end_date: date | None,
) -> tuple[tuple[str, str], ...]:
    if start_date is None or end_date is None or start_date > end_date:
        return ()
    return ((start_date.isoformat(), end_date.isoformat()),)


__all__ = [
    "CHEMICAL_FUTURES_SYMBOLS",
    "FUTURES_INVENTORY_RAW_SCHEMA",
    "FUTURES_INVENTORY_SCHEMA",
    "FuturesInventoryCollector",
    "_missing_date_ranges",
    "build_futures_inventory_curated_frame",
    "build_futures_inventory_raw_frame",
]
