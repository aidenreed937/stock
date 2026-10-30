"""期货主力席位持仓龙虎榜采集器 (FuturesHoldRankCollector)。

量化博弈指标与 2-Tier ETL 架构:
1. 真实来源: 期货交易所 (郑商所/大商所/上期所) 每日收盘持仓龙虎榜 (ak.futures_hold_pos_sina);
2. 覆盖 8 大化工核心品种:
   - 纯碱 (SA)、烧碱 (SH)、PTA (TA)、尿素 (UR)、甲醇 (MA)、聚丙烯 (PP)、塑料 (L)、玻璃 (FG);
3. 计算核心衍生指标:
   - top20_long_vol: 前 20 席位多头总持仓 (手);
   - top20_short_vol: 前 20 席位空头总持仓 (手);
   - top20_net_long_vol: 前 20 席位净多头持仓 (多头 - 空头);
   - top5_long_share_pct: 前 5 多头集中度 (%);
   - top5_short_share_pct: 前 5 空头集中度 (%);
   - smart_money_bias: 聪明钱多空偏向 (bullish / neutral / bearish);
4. 2-Tier 存储:
   - RAW: data/raw/industry/chemicals/futures_hold_rank/{symbol}.csv;
   - Curated: data/curated/industry/futures_hold_rank.parquet;
5. 消除前视偏差: release_date 为收盘当日。
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.chemicals.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.chemicals.schemas import HOLD_RANK_RAW_SCHEMA, HOLD_RANK_SCHEMA
from stock_data.fetcher.industry.chemicals.transforms.hold_rank import (
    build_hold_rank_curated_frame,
    build_hold_rank_raw_frame,
)
from stock_data.fetcher.industry.common import now_utc_iso
from stock_data.fetcher.industry.contracts import IndustryFrameResult

logger = logging.getLogger(__name__)

CHEMICAL_FUTURES_MAP = {
    "SA": {"name": "纯碱", "realtime_symbol": "纯碱"},
    "SH": {"name": "烧碱", "realtime_symbol": "烧碱"},
    "TA": {"name": "PTA", "realtime_symbol": "PTA"},
    "UR": {"name": "尿素", "realtime_symbol": "尿素"},
    "MA": {"name": "甲醇", "realtime_symbol": "郑醇"},
    "PP": {"name": "聚丙烯", "realtime_symbol": "PP"},
    "L": {"name": "塑料", "realtime_symbol": "塑料"},
    "FG": {"name": "玻璃", "realtime_symbol": "玻璃"},
}


def _required_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _query_date_to_date(query_date: str) -> date:
    return date(int(query_date[:4]), int(query_date[4:6]), int(query_date[6:]))


def _save_raw_tables(
    raw_dir: Path,
    rank_dir: Path,
    symbol: str,
    contract: str,
    query_date: str,
    df_long: Any,
    df_short: Any,
) -> pl.DataFrame:
    meta = CHEMICAL_FUTURES_MAP.get(symbol, {"name": symbol})
    trade_date = date(int(query_date[:4]), int(query_date[4:6]), int(query_date[6:]))
    rows: list[dict[str, object]] = []
    for side, frame, volume_column in (
        ("long", df_long, "多单持仓"),
        ("short", df_short, "空单持仓"),
    ):
        for _, row in frame.iterrows():
            rows.append(
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "name": meta["name"],
                    "contract": contract,
                    "side": side,
                    "member_name_raw": str(row.get("会员简称") or ""),
                    "position_volume_raw": str(row.get(volume_column) or ""),
                    "source": "Sina_Exchange_Hold_Rank",
                    "release_date": trade_date,
                    "collected_at": now_utc_iso(),
                    "raw_content_sha256": "",
                    "raw_snapshot_path": "",
                }
            )
    raw_df = pl.DataFrame(rows, schema=HOLD_RANK_RAW_SCHEMA)
    snapshot_path = rank_dir / f"{symbol}_{query_date}.csv"
    payload = raw_df.drop(["raw_content_sha256", "raw_snapshot_path"]).write_csv().encode()
    content_hash = raw_content_sha256(payload)
    snapshot_ref = raw_snapshot_path_value(snapshot_path, raw_dir)
    final_df = raw_df.with_columns(
        pl.lit(content_hash).alias("raw_content_sha256"),
        pl.lit(snapshot_ref).alias("raw_snapshot_path"),
    )
    final_df.write_csv(snapshot_path)
    return final_df


def _build_record(
    symbol: str,
    contract: str,
    query_date: str,
    df_long: Any,
    df_short: Any,
    *,
    raw_df: pl.DataFrame | None = None,
) -> dict[str, Any] | None:
    meta = CHEMICAL_FUTURES_MAP.get(symbol, {"name": symbol})
    trade_date = date(int(query_date[:4]), int(query_date[4:6]), int(query_date[6:]))
    total_long = float(df_long["多单持仓"].sum())
    total_short = float(df_short["空单持仓"].sum())
    if total_long <= 0 or total_short <= 0:
        return None
    top5_long = float(df_long.head(5)["多单持仓"].sum())
    top5_short = float(df_short.head(5)["空单持仓"].sum())
    top1_long = df_long.iloc[0]
    top1_short = df_short.iloc[0]
    top1_long_vol = _required_float(top1_long.get("多单持仓"))
    top1_short_vol = _required_float(top1_short.get("空单持仓"))
    if top1_long_vol is None or top1_short_vol is None:
        return None
    net_long = total_long - total_short
    raw_row = raw_df.row(0, named=True) if raw_df is not None and raw_df.height else {}
    return {
        "trade_date": trade_date,
        "symbol": symbol,
        "name": meta["name"],
        "contract": contract,
        "top20_long_vol": total_long,
        "top20_short_vol": total_short,
        "top20_net_long_vol": net_long,
        "top5_long_share_pct": round(top5_long / total_long * 100.0, 2),
        "top5_short_share_pct": round(top5_short / total_short * 100.0, 2),
        "top1_long_member": str(top1_long.get("会员简称", "")),
        "top1_long_vol": top1_long_vol,
        "top1_short_member": str(top1_short.get("会员简称", "")),
        "top1_short_vol": top1_short_vol,
        "smart_money_bias": "bullish"
        if net_long > 5000
        else "bearish"
        if net_long < -5000
        else "neutral",
        "source": "Sina_Exchange_Hold_Rank",
        "release_date": trade_date,
        "collected_at": now_utc_iso(),
        "raw_content_sha256": str(raw_row.get("raw_content_sha256") or ""),
        "raw_snapshot_path": str(raw_row.get("raw_snapshot_path") or ""),
    }


def _load_raw_snapshots(
    rank_dir: Path,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    for path in sorted(rank_dir.glob("*.csv")):
        frame = _read_raw_snapshot(path)
        if frame.is_empty():
            continue
        if start_date is not None:
            frame = frame.filter(pl.col("trade_date") >= pl.lit(start_date))
        if end_date is not None:
            frame = frame.filter(pl.col("trade_date") <= pl.lit(end_date))
        if not frame.is_empty():
            frames.append(frame)
    if not frames:
        return pl.DataFrame(schema=HOLD_RANK_RAW_SCHEMA)
    return pl.concat(frames, how="vertical_relaxed").unique(
        subset=["trade_date", "symbol", "side", "member_name_raw"],
        keep="last",
    )


def _read_raw_snapshot(path: Path) -> pl.DataFrame:
    """读取单个龙虎榜 RAW 快照，异常文件按不可用处理。"""
    try:
        frame = pl.read_csv(path, try_parse_dates=True)
        for column in ("raw_content_sha256", "raw_snapshot_path"):
            if column not in frame.columns:
                frame = frame.with_columns(pl.lit("").alias(column))
        return frame.select(list(HOLD_RANK_RAW_SCHEMA)).cast(pl.Schema(HOLD_RANK_RAW_SCHEMA))
    except Exception as exc:
        logger.warning("读取龙虎榜 RAW 快照失败 [%s]: %s", path, exc)
        return pl.DataFrame(schema=HOLD_RANK_RAW_SCHEMA)


def _normalize_czce_contract_to_sina(symbol: str, raw_code: str, trade_date: date) -> str:
    """将郑商所 3 位合约 (如 SA501) 转换为新浪标准 4 位代码 (如 SA2501)。"""
    m = re.match(r"^([A-Za-z]+)(\d)(\d{2})$", raw_code)
    if not m:
        return raw_code.upper()
    sym, y_digit, mm = m.groups()
    decade = (trade_date.year // 10) * 10
    cy = decade + int(y_digit)
    if cy < trade_date.year:
        cy += 10
    return f"{sym.upper()}{cy % 100:02d}{mm}"


class FuturesHoldRankCollector:
    """期货主力席位持仓龙虎榜采集器。"""

    def __init__(self, raw_dir: Path | str) -> None:
        self.raw_dir = Path(raw_dir)
        self.rank_dir = self.raw_dir / "chemicals" / "futures_hold_rank"
        self.rank_dir.mkdir(parents=True, exist_ok=True)
        self.missing_periods: set[str] = set()
        self.collection_errors: list[str] = []
        self.fetched_periods: set[str] = set()
        self.cached_periods: set[str] = set()

    def _fetch_tables(
        self,
        symbol: str,
        contract: str,
        query_date: str,
    ) -> tuple[Any, Any] | None:
        import akshare as ak

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                df_long = ak.futures_hold_pos_sina(
                    symbol="多单持仓", contract=contract, date=query_date
                )
                df_short = ak.futures_hold_pos_sina(
                    symbol="空单持仓", contract=contract, date=query_date
                )
                if (
                    df_long is not None
                    and not df_long.empty
                    and df_short is not None
                    and not df_short.empty
                ):
                    return df_long, df_short
                last_error = RuntimeError("空响应")
            except Exception as exc:
                last_error = exc
            if attempt < 2:
                time.sleep(0.25 * (2**attempt))
        logger.warning(
            "抓取期货席位榜失败 [%s %s %s]: %s", symbol, contract, query_date, last_error
        )
        return None

    def _resolve_historical_contract_from_official(
        self, symbol: str, query_date: str
    ) -> str | None:
        """从郑商所/大商所官方日行情缓存中解析指定交易日持仓量最大的主力合约。"""
        try:
            trade_date = _query_date_to_date(query_date)
        except Exception:
            return None

        czce_symbols = {"SA", "SH", "TA", "UR", "MA", "FG"}
        dce_symbols = {"PP", "L", "V", "EB", "EG"}

        try:
            if symbol in czce_symbols:
                from stock_data.fetcher.industry.chemicals.collectors.official import (
                    download_czce_daily_text,
                    parse_czce_daily_text,
                    pick_main_contract,
                )

                czce_cache = self.raw_dir / "chemicals" / "futures_daily" / "czce_daily_cache"
                text = download_czce_daily_text(trade_date, czce_cache)
                if not text:
                    return None
                daily = parse_czce_daily_text(text, (symbol,))
                main = pick_main_contract(daily.get(symbol, []))
                if not main or not main.get("contract"):
                    return None
                raw_code = str(main["contract"]).strip()
                return _normalize_czce_contract_to_sina(symbol, raw_code, trade_date)

            if symbol in dce_symbols:
                from stock_data.fetcher.industry.chemicals.collectors.official import (
                    download_dce_daily_text,
                    parse_dce_daily_text,
                    pick_main_contract,
                )

                dce_cache = self.raw_dir / "chemicals" / "futures_daily" / "dce_daily_cache"
                text = download_dce_daily_text(trade_date, dce_cache)
                if not text:
                    return None
                daily = parse_dce_daily_text(text, (symbol,))
                main = pick_main_contract(daily.get(symbol, []))
                if not main or not main.get("contract"):
                    return None
                return str(main["contract"]).strip().upper()
        except Exception as exc:
            logger.debug("从官方日行情解析合约异常 [%s %s]: %s", symbol, query_date, exc)
            return None

        return None

    def _resolve_contract(self, symbol: str, query_date: str | None = None) -> str | None:
        """从 AkShare 当前可交易合约或官方日行情中选择持仓量最高的合约。"""
        if query_date is not None and query_date != date.today().strftime("%Y%m%d"):
            cached_contract = self._load_cached_contract(symbol, query_date)
            if cached_contract:
                return cached_contract
            official_contract = self._resolve_historical_contract_from_official(symbol, query_date)
            if official_contract:
                return official_contract
            logger.warning(
                "历史席位榜不会用当前合约回放 [%s %s]，且未找到官方主力合约，请显式提供 contract_overrides",
                symbol,
                query_date,
            )
            return None
        import akshare as ak

        meta = CHEMICAL_FUTURES_MAP.get(symbol)
        if meta is None:
            return None
        try:
            frame = ak.futures_zh_realtime(symbol=str(meta["realtime_symbol"]))
        except Exception as exc:
            logger.warning("解析当前期货合约失败 [%s]: %s", symbol, exc)
            return None
        if frame is None or frame.empty or "symbol" not in frame.columns:
            return None

        prefix = re.escape(symbol)
        candidates: list[tuple[float, str]] = []
        for _, row in frame.iterrows():
            contract = str(row.get("symbol") or "").upper()
            if not re.fullmatch(rf"{prefix}\d{{3,4}}", contract):
                continue
            position = _required_float(row.get("position")) or 0.0
            candidates.append((position, contract))
        if not candidates:
            logger.warning("当前期货合约列表没有可用合约 [%s]", symbol)
            return None
        return max(candidates, key=lambda item: (item[0], item[1]))[1]

    def _load_cached_contract(self, symbol: str, query_date: str) -> str | None:
        """从同日已有 RAW 快照读取历史合约，不将当前合约 retro-fit 到历史。"""
        path = self.rank_dir / f"{symbol}_{query_date}.csv"
        if not path.exists():
            return None
        try:
            frame = pl.read_csv(path, columns=["contract"])
            contracts = [str(value).strip() for value in frame["contract"].drop_nulls().unique()]
            return contracts[0] if len(contracts) == 1 and contracts[0] else None
        except Exception as exc:
            logger.warning("读取历史席位榜合约失败 [%s %s]: %s", symbol, query_date, exc)
            return None

    def _load_cached_snapshot(self, symbol: str, query_date: str) -> pl.DataFrame:
        path = self.rank_dir / f"{symbol}_{query_date}.csv"
        if not path.exists():
            return pl.DataFrame(schema=HOLD_RANK_RAW_SCHEMA)
        frame = _read_raw_snapshot(path)
        if frame.is_empty():
            return frame
        return frame.filter(
            (pl.col("symbol") == symbol)
            & (pl.col("trade_date") == pl.lit(_query_date_to_date(query_date)))
        )

    def fetch_contract_rank(
        self,
        symbol: str = "SA",
        contract: str | None = None,
        query_date: str | None = None,
    ) -> dict[str, Any] | None:
        """抓取指定合约当日多空前 20 席位并计算集中度。"""
        contract = contract or self._resolve_contract(symbol, query_date)
        if not contract:
            return None
        query_date = query_date or date.today().strftime("%Y%m%d")
        tables = self._fetch_tables(symbol, contract, query_date)
        if tables is None:
            return None
        df_long, df_short = tables
        raw_df = _save_raw_tables(
            self.raw_dir, self.rank_dir, symbol, contract, query_date, df_long, df_short
        )
        return _build_record(
            symbol,
            contract,
            query_date,
            df_long,
            df_short,
            raw_df=raw_df,
        )

    def collect_raw(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
        query_date: str | None = None,
        contract_overrides: Mapping[str, str] | None = None,
    ) -> pl.DataFrame:
        """按运行窗口采集席位原始行，不计算集中度。"""
        self.missing_periods = set()
        self.collection_errors = []
        self.fetched_periods = set()
        self.cached_periods = set()
        if query_date is not None:
            query_dates = [query_date]
        else:
            first = start_date or end_date or date.today()
            last = end_date or first
            query_dates = []
            cursor = first
            while cursor <= last:
                if cursor.weekday() < 5:
                    query_dates.append(cursor.strftime("%Y%m%d"))
                cursor += timedelta(days=1)

        frames: list[pl.DataFrame] = []
        for query in query_dates:
            for symbol, _meta in CHEMICAL_FUTURES_MAP.items():
                override = (contract_overrides or {}).get(f"{symbol}:{query}") or (
                    contract_overrides or {}
                ).get(symbol)
                cached = self._load_cached_snapshot(symbol, query)
                historical_without_override = (
                    query != date.today().strftime("%Y%m%d") and override is None
                )
                if cached.height and (not force or historical_without_override):
                    frames.append(cached)
                    self.cached_periods.add(f"{symbol}:{query}")
                    continue

                contract = override or self._resolve_contract(symbol, query)
                if not contract:
                    logger.warning("无法确定当前期货合约，跳过席位榜 [%s %s]", symbol, query)
                    self.missing_periods.add(f"{symbol}:{query}")
                    self.collection_errors.append(f"{symbol}:{query}: 无法确定历史合约")
                    continue
                tables = self._fetch_tables(symbol, contract, query)
                if tables is None:
                    self.missing_periods.add(f"{symbol}:{query}")
                    self.collection_errors.append(f"{symbol}:{query}: 上游未返回多空席位榜")
                    continue
                frames.append(
                    _save_raw_tables(
                        self.raw_dir,
                        self.rank_dir,
                        symbol,
                        contract,
                        query,
                        tables[0],
                        tables[1],
                    )
                )
                self.fetched_periods.add(f"{symbol}:{query}")
        if not frames:
            return pl.DataFrame(schema=HOLD_RANK_RAW_SCHEMA)
        return pl.concat(frames, how="vertical_relaxed").sort(["symbol", "trade_date", "side"])

    def collect_raw_result(
        self,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
        query_date: str | None = None,
        contract_overrides: Mapping[str, str] | None = None,
    ) -> IndustryFrameResult:
        """采集 RAW 并保留缓存命中、缺口和错误状态。"""
        frame = self.collect_raw(
            force=force,
            start_date=start_date,
            end_date=end_date,
            query_date=query_date,
            contract_overrides=contract_overrides,
        )
        missing = tuple(sorted(self.missing_periods))
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

    def collect(
        self,
        query_date: str | None = None,
        force: bool = False,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        """兼容旧接口：采集 RAW 后构建 Curated 集中度指标。"""
        raw = self.collect_raw(
            force=force,
            start_date=start_date,
            end_date=end_date,
            query_date=query_date,
        )
        return build_hold_rank_curated_frame(raw)

    def load_raw_snapshots(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pl.DataFrame:
        """离线读取席位榜 CSV RAW 快照，不触发上游请求。"""
        return _load_raw_snapshots(
            self.rank_dir,
            start_date=start_date,
            end_date=end_date,
        )


__all__ = [
    "CHEMICAL_FUTURES_MAP",
    "HOLD_RANK_RAW_SCHEMA",
    "HOLD_RANK_SCHEMA",
    "FuturesHoldRankCollector",
    "build_hold_rank_curated_frame",
    "build_hold_rank_raw_frame",
]
