"""基础化工期货主力合约日度行情采集器 (FuturesPriceCollector)。

职责:
1. 规范采集场内期货交易所 (CZCE/DCE) 标准化衍生品合约日度行情 (开高低收、结算价、持仓量、成交量);
2. 与现货出厂价 (Spot Price) 严格分离，支撑下游基差 (Basis = Spot - Futures) 与升贴水计算;
3. 遵循 2-Tier 规范与离线优先原则，默认不发起外部网络请求；``enable_network=True``
   时按请求窗口调用郑商所/大商所官方静态文件回填 RAW CSV（缓存优先），
   再由 pipeline runner 统一物化 Curated。
"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.chemicals.collectors.official import (
    backfill_futures_daily_raw,
)
from stock_data.fetcher.industry.chemicals.models import ChemicalFuturesDailyRecord
from stock_data.fetcher.industry.chemicals.schemas import (
    CHEMICAL_FUTURES_DAILY_RAW_SCHEMA,
    CHEMICAL_FUTURES_DAILY_SCHEMA,
)
from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.contracts import IndustryFrameResult

logger = logging.getLogger(__name__)

CHEMICAL_FUTURES_CONTRACTS: dict[str, dict[str, str]] = {
    "SA": {"name": "纯碱", "main_contract": "SA0", "exchange": "CZCE"},
    "SH": {"name": "烧碱", "main_contract": "SH0", "exchange": "CZCE"},
    "TA": {"name": "PTA", "main_contract": "TA0", "exchange": "CZCE"},
    "UR": {"name": "尿素", "main_contract": "UR0", "exchange": "CZCE"},
    "MA": {"name": "甲醇", "main_contract": "MA0", "exchange": "CZCE"},
    "V": {"name": "PVC", "main_contract": "V0", "exchange": "DCE"},
    "PP": {"name": "聚丙烯", "main_contract": "PP0", "exchange": "DCE"},
    "L": {"name": "塑料", "main_contract": "L0", "exchange": "DCE"},
    "EB": {"name": "苯乙烯", "main_contract": "EB0", "exchange": "DCE"},
    "EG": {"name": "乙二醇", "main_contract": "EG0", "exchange": "DCE"},
}


class FuturesPriceCollector:
    """基础化工期货日线行情采集器。"""

    def __init__(
        self,
        raw_dir: Path | str,
        enable_network: bool = False,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.daily_dir = self.raw_dir / "chemicals" / "futures_daily"
        self.parquet_path = self.raw_dir / "chemicals" / "futures_daily.parquet"
        self.enable_network = enable_network
        self.collection_errors: list[str] = []

    def collect_symbol(self, symbol: str) -> list[ChemicalFuturesDailyRecord]:
        """读取指定品种的期货日度行情记录。"""
        records_dict = self._read_symbol_raw_csv(symbol)
        records = [
            ChemicalFuturesDailyRecord(**data)
            for data in sorted(records_dict.values(), key=lambda r: r["trade_date"])
        ]
        return records

    def build_raw_frame(self, symbols: list[str] | None = None) -> pl.DataFrame:
        """构建统一的期货日度行情 RAW 事实表。"""
        target_symbols = symbols or list(CHEMICAL_FUTURES_CONTRACTS.keys())
        all_rows: list[dict[str, Any]] = []
        for sym in target_symbols:
            rec_dict = self._read_symbol_raw_csv(sym)
            for r in rec_dict.values():
                all_rows.append(
                    {
                        "symbol": r["symbol"],
                        "contract": r["contract"],
                        "trade_date": r["trade_date"],
                        "open_raw": _to_str(r.get("open")),
                        "high_raw": _to_str(r.get("high")),
                        "low_raw": _to_str(r.get("low")),
                        "close_raw": _to_str(r.get("close")),
                        "settle_raw": _to_str(r.get("settle")),
                        "volume_raw": _to_str(r.get("volume")),
                        "open_interest_raw": _to_str(r.get("open_interest")),
                        "unit": r.get("unit", "元/吨"),
                        "exchange": r.get("exchange", ""),
                        "source": r.get("source", "exchange_daily"),
                        "source_url": r.get("source_url", ""),
                        "release_date": r.get("release_date"),
                        "data_status": r.get("data_status", "actual"),
                        "collected_at": r.get("collected_at", ""),
                        "raw_content_sha256": r.get("raw_content_sha256", ""),
                        "raw_snapshot_path": r.get("raw_snapshot_path", ""),
                    }
                )

        if not all_rows:
            return pl.DataFrame(schema=CHEMICAL_FUTURES_DAILY_RAW_SCHEMA)
        return (
            pl.DataFrame(all_rows, schema=CHEMICAL_FUTURES_DAILY_RAW_SCHEMA)
            .unique(subset=["symbol", "contract", "trade_date"], keep="last")
            .sort(["symbol", "trade_date"])
        )

    def build_curated_frame(self, symbols: list[str] | None = None) -> pl.DataFrame:
        """构建强类型 Curated 事实表。"""
        raw_df = self.build_raw_frame(symbols=symbols)
        if raw_df.is_empty():
            return pl.DataFrame(schema=CHEMICAL_FUTURES_DAILY_SCHEMA)

        return (
            raw_df.select(
                pl.col("symbol").cast(pl.String),
                pl.col("contract").cast(pl.String),
                pl.col("trade_date").cast(pl.Date),
                pl.col("open_raw").cast(pl.Float64).alias("open"),
                pl.col("high_raw").cast(pl.Float64).alias("high"),
                pl.col("low_raw").cast(pl.Float64).alias("low"),
                pl.col("close_raw").cast(pl.Float64).alias("close"),
                pl.col("settle_raw").cast(pl.Float64).alias("settle"),
                pl.col("volume_raw").cast(pl.Float64).alias("volume"),
                pl.col("open_interest_raw").cast(pl.Float64).alias("open_interest"),
                pl.col("unit").cast(pl.String),
                pl.col("exchange").cast(pl.String),
                pl.col("source").cast(pl.String),
                pl.col("source_url").cast(pl.String),
                pl.col("release_date").cast(pl.Date),
                pl.col("data_status").cast(pl.String),
                pl.col("collected_at").cast(pl.String),
            )
            .unique(subset=["symbol", "contract", "trade_date"], keep="last")
            .sort(["symbol", "trade_date"])
        )

    def collect_result(
        self,
        symbols: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> IndustryFrameResult:
        """采集期货日行情并返回标准化治理状态对象。

        ``enable_network=True`` 且窗口非空时，先按窗口回填缺失的官方 RAW CSV
        （郑商所/大商所日行情，缓存优先），再构建统一事实帧。
        """
        fetched: set[str] = set()
        if self.enable_network and (start_date is not None or end_date is not None):
            _, fetched = backfill_futures_daily_raw(
                self.daily_dir,
                CHEMICAL_FUTURES_CONTRACTS,
                start_date=start_date,
                end_date=end_date,
            )
        curated_df = self.build_curated_frame(symbols=symbols)
        if start_date is not None:
            curated_df = curated_df.filter(pl.col("trade_date") >= start_date)
        if end_date is not None:
            curated_df = curated_df.filter(pl.col("trade_date") <= end_date)

        cached: set[str] = set()
        for row in curated_df.select(["symbol", "trade_date"]).to_dicts():
            d_str = row["trade_date"].isoformat()
            cached.add(f"{row['symbol']}:{d_str}")

        return IndustryFrameResult(
            frame=curated_df,
            status="SUCCESS",
            fetched_periods=tuple(sorted(fetched)),
            cached_periods=tuple(sorted(cached)),
            missing_periods=(),
            errors=tuple(self.collection_errors),
            updated=bool(fetched),
        )

    def backfill_raw(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        *,
        full: bool = False,
    ) -> tuple[dict[str, int], set[str]]:
        """仅回填官方 RAW CSV（不物化 Curated），返回 (summary, fetched_labels)。"""
        return backfill_futures_daily_raw(
            self.daily_dir,
            CHEMICAL_FUTURES_CONTRACTS,
            start_date=start_date,
            end_date=end_date,
            full=full,
        )

    def _read_symbol_raw_csv(self, symbol: str) -> dict[str, dict[str, Any]]:
        csv_path = self.daily_dir / f"{symbol}.csv"
        if not csv_path.exists():
            return {}

        meta = CHEMICAL_FUTURES_CONTRACTS.get(symbol, {})
        contract = meta.get("main_contract", f"{symbol}0")
        exchange = meta.get("exchange", "CZCE")
        records: dict[str, dict[str, Any]] = {}
        now_iso = now_utc_iso()

        with csv_path.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                d_text = (row.get("trade_date") or "").strip()
                if not d_text:
                    continue
                t_date = date.fromisoformat(d_text)
                records[d_text] = {
                    "symbol": symbol,
                    "contract": row.get("contract") or contract,
                    "trade_date": t_date,
                    "open": _safe_float(row.get("open")),
                    "high": _safe_float(row.get("high")),
                    "low": _safe_float(row.get("low")),
                    "close": _safe_float(row.get("close")),
                    "settle": _safe_float(row.get("settle")),
                    "volume": _safe_float(row.get("volume")),
                    "open_interest": _safe_float(row.get("open_interest")),
                    "unit": row.get("unit") or "元/吨",
                    "exchange": row.get("exchange") or exchange,
                    "source": row.get("source") or f"exchange_{exchange.lower()}",
                    "source_url": row.get("source_url") or "",
                    "release_date": (
                        date.fromisoformat(row["release_date"].strip())
                        if row.get("release_date")
                        else t_date
                    ),
                    "data_status": row.get("data_status") or "actual",
                    "collected_at": row.get("collected_at") or now_iso,
                    "raw_content_sha256": row.get("raw_content_sha256") or "",
                    "raw_snapshot_path": row.get("raw_snapshot_path") or "",
                }
        return records


def _safe_float(val: object) -> float | None:
    if val is None:
        return None
    text = str(val).strip()
    if not text:
        return None
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def _to_str(val: object) -> str | None:
    if val is None:
        return None
    text = str(val).strip()
    return text if text else None


__all__ = [
    "CHEMICAL_FUTURES_CONTRACTS",
    "FuturesPriceCollector",
]
