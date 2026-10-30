"""玻璃核心上市公司画像、估值反向时钟与财报对账面板构建。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import polars as pl
import yaml

logger = logging.getLogger(__name__)

CORE_GLASS_COMPANIES = [
    {
        "symbol": "601636.SH",
        "name": "旗滨集团",
        "process_type": "float_and_pv",
        "role": "float_alpha_leader",
    },
    {
        "symbol": "601865.SH",
        "name": "福莱特",
        "process_type": "pv_glass",
        "role": "pv_alpha_leader",
    },
    {
        "symbol": "000012.SZ",
        "name": "南玻A",
        "process_type": "float_and_pv",
        "role": "beta_elastic",
    },
    {
        "symbol": "600586.SH",
        "name": "金晶科技",
        "process_type": "float_and_soda",
        "role": "beta_elastic",
    },
]


def load_glass_company_configs(yaml_path: Path | str) -> list[dict[str, Any]]:
    target = Path(yaml_path)
    if not target.exists():
        return CORE_GLASS_COMPANIES
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        companies = data.get("companies", [])
        return companies if isinstance(companies, list) and companies else CORE_GLASS_COMPANIES
    except Exception:
        return CORE_GLASS_COMPANIES


def build_glass_company_panel(
    storage_root: Path | str = "data",
    company_configs: list[dict[str, Any]] | None = None,
) -> pl.DataFrame:
    """构建玻璃上市公司日频最新行情与 10 年 PB 分位反向时钟面板。"""
    root = Path(storage_root)
    basic_dir = root / "curated" / "tushare" / "market=CN" / "daily_basic"
    companies = company_configs or CORE_GLASS_COMPANIES
    symbols = [c["symbol"] for c in companies]

    if not basic_dir.exists():
        # 无数据时生成最小结构表
        return pl.DataFrame()

    try:
        # 扫描历史 daily_basic 计算 10Y PB 分位数与最新截面
        ldf = pl.scan_parquet(str(basic_dir / "*/*/*.parquet"), extra_columns="ignore")
        sub_df = (
            ldf.filter(pl.col("symbol").is_in(symbols))
            .select(["symbol", "trade_date", "close", "pb", "pe_ttm", "total_mv"])
            .collect()
        )
    except Exception as exc:
        logger.debug("扫描 daily_basic 构建公司面板失败: %s", exc)
        return pl.DataFrame()

    if sub_df.is_empty():
        return pl.DataFrame()

    meta_map = {c["symbol"]: c for c in companies}
    rows: list[dict[str, Any]] = []

    for sym in symbols:
        comp_df = sub_df.filter(pl.col("symbol") == sym).sort("trade_date")
        meta = meta_map.get(sym, {})
        if comp_df.is_empty():
            rows.append(
                {
                    "symbol": sym,
                    "name": meta.get("name", sym),
                    "process_type": meta.get("process_type", "pv_glass"),
                    "role": meta.get("target_role", meta.get("role", "global_alpha_leader")),
                    "trade_date": "港股/战略配置画像",
                    "close": 0.0,
                    "pb": 0.0,
                    "pb_percentile_10y": 0.0,
                    "pe_ttm": None,
                    "total_mv_billion": float(meta.get("estimated_mv_billion", 0.0)),
                    "ma20_broken": False,
                    "clock_status": meta.get("cost_tier", "global_duopoly_leader"),
                }
            )
            continue

        pbs = comp_df["pb"].drop_nulls()
        latest = comp_df.tail(1).to_dicts()[0]
        latest_pb = float(latest["pb"]) if latest.get("pb") is not None else 1.0

        # 计算 10 年 PB 分位
        pct = (
            float((pbs < latest_pb).sum() or 0) / max(1, len(pbs)) * 100.0 if len(pbs) > 0 else 50.0
        )

        # 反向时钟定性
        if pct <= 15.0 or latest_pb <= 1.1:
            clock_status = "deep_value_trough"  # 极值深价值大底
        elif pct >= 65.0:
            clock_status = "high_expansion_risk"  # 高位景气钝化风险
        else:
            clock_status = "neutral"

        # MA20 突破检测
        closes = comp_df["close"].drop_nulls().to_list()
        latest_close = float(latest["close"]) if latest.get("close") is not None else 0.0
        ma20 = sum(closes[-20:]) / min(len(closes), 20) if len(closes) >= 5 else latest_close
        ma_broken = latest_close >= ma20

        rows.append(
            {
                "symbol": sym,
                "name": meta.get("name", sym),
                "process_type": meta.get("process_type", "float"),
                "role": meta.get("target_role", meta.get("role", "alpha_leader")),
                "trade_date": str(latest["trade_date"]),
                "close": latest_close,
                "pb": round(latest_pb, 2),
                "pb_percentile_10y": round(pct, 1),
                "pe_ttm": round(float(latest["pe_ttm"]), 2)
                if latest.get("pe_ttm") is not None
                else None,
                "total_mv_billion": round(float(latest.get("total_mv", 0) or 0) / 100000000.0, 1),
                "ma20_broken": ma_broken,
                "clock_status": clock_status,
            }
        )

    return pl.DataFrame(rows)


__all__ = [
    "CORE_GLASS_COMPANIES",
    "build_glass_company_panel",
    "load_glass_company_configs",
]
