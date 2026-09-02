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
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.common import now_utc_iso

logger = logging.getLogger(__name__)

HOLD_RANK_SCHEMA = {
    "trade_date": pl.Date,
    "symbol": pl.String,
    "name": pl.String,
    "contract": pl.String,
    "top20_long_vol": pl.Float64,
    "top20_short_vol": pl.Float64,
    "top20_net_long_vol": pl.Float64,
    "top5_long_share_pct": pl.Float64,
    "top5_short_share_pct": pl.Float64,
    "top1_long_member": pl.String,
    "top1_long_vol": pl.Float64,
    "top1_short_member": pl.String,
    "top1_short_vol": pl.Float64,
    "smart_money_bias": pl.String,
    "source": pl.String,
    "release_date": pl.Date,
    "collected_at": pl.String,
}

CHEMICAL_FUTURES_MAP = {
    "SA": {"name": "纯碱", "default_contract": "SA2409"},
    "SH": {"name": "烧碱", "default_contract": "SH2409"},
    "TA": {"name": "PTA", "default_contract": "TA2409"},
    "UR": {"name": "尿素", "default_contract": "UR2409"},
    "MA": {"name": "甲醇", "default_contract": "MA2409"},
    "PP": {"name": "聚丙烯", "default_contract": "PP2409"},
    "L": {"name": "塑料", "default_contract": "L2409"},
    "FG": {"name": "玻璃", "default_contract": "FG2409"},
}


class FuturesHoldRankCollector:
    """期货主力席位持仓龙虎榜采集器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.rank_dir = self.raw_dir / "chemicals" / "futures_hold_rank"
        self.rank_dir.mkdir(parents=True, exist_ok=True)

    def fetch_contract_rank(
        self,
        symbol: str = "SA",
        contract: str = "SA2409",
        query_date: str = "20240828",
    ) -> dict[str, Any] | None:
        """抓取指定合约当日多空前 20 席位并计算集中度。"""
        import akshare as ak

        meta = CHEMICAL_FUTURES_MAP.get(symbol, {"name": symbol, "default_contract": contract})
        now_iso = now_utc_iso()
        t_d = date(int(query_date[:4]), int(query_date[4:6]), int(query_date[6:]))

        try:
            df_long = ak.futures_hold_pos_sina(
                symbol="多单持仓", contract=contract, date=query_date
            )
            df_short = ak.futures_hold_pos_sina(
                symbol="空单持仓", contract=contract, date=query_date
            )

            if df_long is None or df_long.empty or df_short is None or df_short.empty:
                return None

            t20_l = float(df_long["多单持仓"].sum())
            t20_s = float(df_short["空单持仓"].sum())
            t5_l = float(df_long.head(5)["多单持仓"].sum())
            t5_s = float(df_short.head(5)["空单持仓"].sum())

            top5_l_pct = round((t5_l / t20_l) * 100.0, 2) if t20_l > 0 else 0.0
            top5_s_pct = round((t5_s / t20_s) * 100.0, 2) if t20_s > 0 else 0.0
            net_long = t20_l - t20_s

            bias = "neutral"
            if net_long > 5000:
                bias = "bullish"
            elif net_long < -5000:
                bias = "bearish"

            top1_l_row = df_long.iloc[0]
            top1_s_row = df_short.iloc[0]

            return {
                "trade_date": t_d,
                "symbol": symbol,
                "name": meta["name"],
                "contract": contract,
                "top20_long_vol": t20_l,
                "top20_short_vol": t20_s,
                "top20_net_long_vol": net_long,
                "top5_long_share_pct": top5_l_pct,
                "top5_short_share_pct": top5_s_pct,
                "top1_long_member": str(top1_l_row.get("会员简称", "")),
                "top1_long_vol": float(top1_l_row.get("多单持仓", 0.0)),
                "top1_short_member": str(top1_s_row.get("会员简称", "")),
                "top1_short_vol": float(top1_s_row.get("空单持仓", 0.0)),
                "smart_money_bias": bias,
                "source": "Sina_Exchange_Hold_Rank",
                "release_date": t_d,
                "collected_at": now_iso,
            }
        except Exception as e:
            logger.warning(f"抓取期货席位榜失败 [{symbol} {contract} {query_date}]: {e}")
            return None

    def collect(self, query_date: str = "20240828") -> pl.DataFrame:
        """批量采集 8 大核心化工品种席位榜并物化。"""
        records: list[dict[str, Any]] = []
        for sym, meta in CHEMICAL_FUTURES_MAP.items():
            rec = self.fetch_contract_rank(
                symbol=sym,
                contract=meta["default_contract"],
                query_date=query_date,
            )
            if rec:
                records.append(rec)

        if not records:
            return pl.DataFrame(schema=HOLD_RANK_SCHEMA)

        df = pl.DataFrame(records, schema=HOLD_RANK_SCHEMA).sort(["symbol", "trade_date"])
        return df
