"""化工与大宗工业品期货交易所注册仓单库存采集器 (FuturesInventoryCollector)。

数据属性与 2-Tier ETL 架构:
1. 真实来源: 东方财富 / 郑商所 / 大商所官方期货注册仓单库存 (ak.futures_inventory_em);
2. 覆盖品种: 纯碱 (SA)、烧碱 (SH)、PTA (TA)、尿素 (UR)、甲醇 (MA)、聚丙烯 (PP)、塑料 (L)、玻璃 (FG);
3. 2-Tier 存储: 历史底表与增量保存在 data/raw/industry/chemicals/futures_inventory/{symbol}.csv;
4. 增量机制: 本地已有历史 + 在线拉取最新日度快照 + 按 trade_date 自动 Upsert 追加合并;
5. 消除前视偏差: release_date 为交易所收盘结算当日 (T 日收盘生效)。
"""

from __future__ import annotations

import csv
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

import akshare as ak
import polars as pl

from stock_data.fetcher.industry.common import now_utc_iso

logger = logging.getLogger(__name__)

# 核心化工与大宗工业品映射表
CHEMICAL_FUTURES_SYMBOLS = {
    "SA": {"name": "纯碱", "industry_code": "220200", "unit": "contracts"},
    "SH": {"name": "烧碱", "industry_code": "220200", "unit": "contracts"},
    "TA": {"name": "PTA", "industry_code": "220400", "unit": "contracts"},
    "UR": {"name": "尿素", "industry_code": "220800", "unit": "contracts"},
    "MA": {"name": "甲醇", "industry_code": "220300", "unit": "contracts"},
    "PP": {"name": "聚丙烯", "industry_code": "220500", "unit": "contracts"},
    "L": {"name": "塑料", "industry_code": "220500", "unit": "contracts"},
    "FG": {"name": "玻璃", "industry_code": "220200", "unit": "contracts"},
}

FUTURES_INVENTORY_SCHEMA = {
    "symbol": pl.String,
    "name": pl.String,
    "industry_code": pl.String,
    "trade_date": pl.Date,
    "inventory": pl.Float64,
    "change": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "collected_at": pl.String,
}


class FuturesInventoryCollector:
    """化工商品期货注册仓单库存采集器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.inv_dir = self.raw_dir / "chemicals" / "futures_inventory"
        self.inv_dir.mkdir(parents=True, exist_ok=True)

    def _load_symbol_raw_csv(self, symbol: str) -> dict[str, dict[str, Any]]:
        csv_path = self.inv_dir / f"{symbol}.csv"
        if not csv_path.exists():
            return {}

        def _flt(k: str, r: dict[str, str]) -> float | None:
            v = r.get(k)
            return float(v) if v and v.strip() else None

        records: dict[str, dict[str, Any]] = {}
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                d_str = row["trade_date"].strip()
                records[d_str] = {
                    "symbol": symbol,
                    "name": row.get("name")
                    or CHEMICAL_FUTURES_SYMBOLS.get(symbol, {}).get("name", symbol),
                    "industry_code": row.get("industry_code")
                    or CHEMICAL_FUTURES_SYMBOLS.get(symbol, {}).get("industry_code", ""),
                    "trade_date": date.fromisoformat(d_str),
                    "inventory": _flt("inventory", row),
                    "change": _flt("change", row),
                    "unit": row.get("unit") or "contracts",
                    "source": row.get("source") or "Eastmoney/CZCE/DCE",
                    "source_url": row.get("source_url")
                    or "https://data.eastmoney.com/ifdata/kcsj.html",
                    "release_date": date.fromisoformat(row["release_date"].strip())
                    if row.get("release_date")
                    else date.fromisoformat(d_str),
                    "collected_at": row.get("collected_at") or now_utc_iso(),
                }
        return records

    def _save_symbol_raw_csv(self, symbol: str, records: dict[str, dict[str, Any]]) -> None:
        csv_path = self.inv_dir / f"{symbol}.csv"
        rows = sorted(records.values(), key=lambda r: r["trade_date"])
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
        ]
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow(
                    {
                        "trade_date": r["trade_date"].isoformat(),
                        "symbol": r["symbol"],
                        "name": r["name"],
                        "industry_code": r["industry_code"],
                        "inventory": r["inventory"] if r["inventory"] is not None else "",
                        "change": r["change"] if r["change"] is not None else "",
                        "unit": r["unit"],
                        "source": r["source"],
                        "source_url": r["source_url"],
                        "release_date": r["release_date"].isoformat(),
                        "collected_at": r["collected_at"],
                    }
                )

    def collect(self, symbols: list[str] | None = None, force: bool = False) -> pl.DataFrame:
        """执行全品种期货仓单库存拉取与 2-Tier Upsert。"""
        target_symbols = symbols or list(CHEMICAL_FUTURES_SYMBOLS.keys())
        all_records: list[dict[str, Any]] = []
        now_iso = now_utc_iso()

        for sym in target_symbols:
            meta = CHEMICAL_FUTURES_SYMBOLS.get(
                sym, {"name": sym, "industry_code": "", "unit": "contracts"}
            )
            rec_dict = self._load_symbol_raw_csv(sym)

            try:
                # 调用 ak.futures_inventory_em(symbol=中文名或代码)
                df_online = ak.futures_inventory_em(symbol=meta["name"])
                if df_online is not None and not df_online.empty:
                    for _, row in df_online.iterrows():
                        t_d = row["日期"]
                        if isinstance(t_d, str):
                            t_d = date.fromisoformat(t_d)
                        elif isinstance(t_d, datetime):
                            t_d = t_d.date()
                        d_str = t_d.isoformat()
                        inv_val = float(row["库存"]) if pd_not_na(row["库存"]) else None
                        chg_val = float(row["增减"]) if pd_not_na(row["增减"]) else None

                        rec_dict[d_str] = {
                            "symbol": sym,
                            "name": meta["name"],
                            "industry_code": meta["industry_code"],
                            "trade_date": t_d,
                            "inventory": inv_val,
                            "change": chg_val,
                            "unit": meta["unit"],
                            "source": "Eastmoney/CZCE/DCE",
                            "source_url": "https://data.eastmoney.com/ifdata/kcsj.html",
                            "release_date": t_d,
                            "collected_at": now_iso,
                        }
            except Exception as e:
                logger.warning(f"在线抓取期货仓单库存失败 [{sym}]: {e}")

            if rec_dict:
                self._save_symbol_raw_csv(sym, rec_dict)
                all_records.extend(rec_dict.values())

        if not all_records:
            return pl.DataFrame(schema=FUTURES_INVENTORY_SCHEMA)

        df = (
            pl.DataFrame(all_records, schema=FUTURES_INVENTORY_SCHEMA)
            .unique(subset=["symbol", "trade_date"], keep="last")
            .sort(["symbol", "trade_date"])
        )
        return df


def pd_not_na(val: Any) -> bool:
    import pandas as pd

    return bool(pd.notna(val))
