"""个股诊断数据加载与辅助函数。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.pipelines.stock_diagnostics.types import (
    CapitalFlowSnapshot,
    ScreenSnapshot,
)
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog


def resolve_symbol_meta(catalog: DataCatalog, input_symbol: str) -> tuple[str, str, str, str, str]:
    """根据输入的代码解析标准 symbol 与股票基本信息。"""
    clean = input_symbol.strip().upper()
    try:
        basic_df = catalog.load_dataset("stock_basic")
    except Exception as exc:
        logger.warning(f"无法加载 stock_basic 表: {exc}")
        return clean, clean, "未知行业", "未知地区", "主板"

    if basic_df.is_empty() or "symbol" not in basic_df.columns:
        return clean, clean, "未知行业", "未知地区", "主板"

    matched = basic_df.filter(pl.col("symbol") == clean)
    if matched.is_empty():
        sym_code = clean.split(".")[0]
        matched = basic_df.filter(pl.col("symbol").str.starts_with(sym_code))

    if not matched.is_empty():
        row = matched.to_dicts()[0]
        return (
            str(row.get("symbol", clean)),
            str(row.get("name", clean)),
            str(row.get("industry") or "其他行业"),
            str(row.get("area") or "中国"),
            str(row.get("market") or "主板"),
        )
    return clean, clean, "未知行业", "未知地区", "主板"


def compute_percentile(series: pl.Series, current_value: float) -> float | None:
    """计算当前数值在序列中的历史百分位 (0-100)。"""
    valid = series.drop_nulls()
    if valid.is_empty():
        return None
    less_or_equal = (valid <= current_value).sum()
    return round(float(less_or_equal) / len(valid) * 100.0, 1)


def norm_to_billion(v: float | None) -> float | None:
    """统一将金额/市值规格化为亿元。"""
    if v is None:
        return None
    if v > 1e9 or v < -1e9:
        return round(v / 1e8, 2)
    if v > 1e4 or v < -1e4:
        return round(v / 1e4, 2)
    return round(v, 2)


def load_10y_treasury_yield(storage_dir: Path | str | None = None) -> float | None:
    """读取本地最新中债 10 年期国债收益率 (%)。"""
    try:
        catalog_lx = DataCatalog("lixinger", storage_dir=storage_dir)
        df = catalog_lx.load_dataset("national_debt")
        if not df.is_empty() and "tcm_y10" in df.columns:
            df = df.sort("trade_date")
            val = df["tcm_y10"].tail(1).to_list()[0]
            if val is not None:
                f_val = float(val)
                return round(f_val * 100.0 if f_val < 0.2 else f_val, 2)
    except Exception as exc:
        logger.warning(f"读取国债收益率失败: {exc}")
    return 1.68  # 稳健兜底默认基准利率


def load_capital_flow(
    catalog: DataCatalog, std_symbol: str, target_date: date | None = None
) -> CapitalFlowSnapshot:
    """加载近 20 日主力大单净流入与北向资金持股比例。"""
    main_net_20d: float | None = None
    hk_ratio: float | None = None

    try:
        mf = catalog.load_dataset("moneyflow", symbols=[std_symbol])
        if not mf.is_empty() and "trade_date" in mf.columns:
            mf = mf.sort("trade_date")
            if target_date is not None:
                mf = mf.filter(pl.col("trade_date") <= target_date)
            recent_mf = mf.tail(20)
            if not recent_mf.is_empty() and all(
                c in recent_mf.columns
                for c in [
                    "buy_elg_amount",
                    "buy_lg_amount",
                    "sell_elg_amount",
                    "sell_lg_amount",
                ]
            ):
                net_series = (
                    recent_mf["buy_elg_amount"]
                    + recent_mf["buy_lg_amount"]
                    - recent_mf["sell_elg_amount"]
                    - recent_mf["sell_lg_amount"]
                )
                raw_sum = float(net_series.sum())
                main_net_20d = norm_to_billion(raw_sum)
    except Exception as exc:
        logger.warning(f"加载主力资金流失败: {exc}")

    try:
        hk = catalog.load_dataset("hk_hold", symbols=[std_symbol])
        if not hk.is_empty() and "trade_date" in hk.columns:
            hk = hk.sort("trade_date")
            if target_date is not None:
                hk = hk.filter(pl.col("trade_date") <= target_date)
            if not hk.is_empty() and "ratio" in hk.columns:
                hk_val = hk["ratio"].tail(1).to_list()[0]
                if hk_val is not None:
                    hk_ratio = round(float(hk_val), 2)
    except Exception as exc:
        logger.warning(f"加载北向持仓失败: {exc}")

    return CapitalFlowSnapshot(
        main_net_inflow_20d_billion=main_net_20d,
        northbound_hold_ratio=hk_ratio,
    )


def load_latest_forecast(
    catalog: DataCatalog, std_symbol: str, target_date: date | None = None
) -> dict[str, Any] | None:
    """加载标的最新业绩预告前瞻。"""
    try:
        fc = catalog.load_dataset("forecast", symbols=[std_symbol])
        if not fc.is_empty() and "ann_date" in fc.columns:
            fc = fc.sort("ann_date")
            if target_date is not None:
                fc = fc.filter(pl.col("ann_date") <= target_date)
            if not fc.is_empty():
                row = fc.tail(1).to_dicts()[0]
                return {
                    "ann_date": str(row.get("ann_date", "")),
                    "end_date": str(row.get("end_date", "")),
                    "type": str(row.get("type", "业绩预告")),
                    "p_change_min": (
                        float(row["p_change_min"]) if row.get("p_change_min") is not None else None
                    ),
                    "p_change_max": (
                        float(row["p_change_max"]) if row.get("p_change_max") is not None else None
                    ),
                    "summary": str(row.get("summary") or ""),
                }
    except Exception as exc:
        logger.warning(f"加载业绩预告失败: {exc}")
    return None


def load_market_temperature_context() -> tuple[float | None, str | None, str]:
    """读取本地最新全市场温度与阶段。"""
    latest_score_path = Path("data/analytics/market_temperature/latest/scores.json")
    if latest_score_path.exists():
        try:
            with open(latest_score_path, encoding="utf-8") as f:
                data = json.load(f)
            composite = data.get("composite", {})
            temp_val = composite.get("temperature")
            as_of = data.get("as_of_date") or ""
            if temp_val is not None:
                temp_float = float(temp_val)
                if temp_float < 25.0:
                    band = "极度冰点 (逆向左侧筑底区)"
                elif temp_float < 45.0:
                    band = "冰点偏冷 (谨慎蓄势区)"
                elif temp_float < 55.0:
                    band = "中性平衡 (震荡分化区)"
                elif temp_float < 75.0:
                    band = "偏热活跃 (右侧顺势区)"
                else:
                    band = "极度过热 (防范冲高回落)"
                return temp_float, band, str(as_of)
        except Exception as exc:
            logger.warning(f"解析市场温度最新产物失败: {exc}")
    return None, None, ""


def load_industry_rank(industry_name: str) -> str | None:
    """读取申万行业结构最新排名。"""
    latest_ind_path = Path("data/analytics/industry_structure/latest/scores.json")
    if latest_ind_path.exists():
        try:
            with open(latest_ind_path, encoding="utf-8") as f:
                data = json.load(f)
            top_struct = data.get("top_structure", [])
            total_count = data.get("scored_industry_count") or len(top_struct)
            for idx, item in enumerate(top_struct, start=1):
                name = item.get("industry_name", "")
                if name and (name in industry_name or industry_name in name):
                    score = item.get("structure_score", 0.0)
                    tags = item.get("tags", "")
                    tag_str = f" [{tags}]" if tags else ""
                    return f"申万综合排名 {idx}/{total_count} (评分 {score:.1f}){tag_str}"
        except Exception as exc:
            logger.warning(f"解析行业结构排名失败: {exc}")
    return None


def load_screen_status(symbol: str) -> ScreenSnapshot:
    """从本地个股排雷最新快照中查询标的状态。"""
    screen_dir = Path("data/analytics/stock_screen/latest")
    clean_sym = symbol.split(".")[0]

    excluded_path = screen_dir / "excluded.csv"
    if excluded_path.exists():
        try:
            df = pl.read_csv(excluded_path)
            if "symbol" in df.columns:
                matched = df.filter(pl.col("symbol").str.contains(clean_sym))
                if not matched.is_empty():
                    reasons = matched["reasons"].to_list() if "reasons" in matched.columns else []
                    return ScreenSnapshot(status="excluded", reasons=[str(r) for r in reasons])
        except Exception:
            pass

    warned_path = screen_dir / "warned.csv"
    if warned_path.exists():
        try:
            df = pl.read_csv(warned_path)
            if "symbol" in df.columns:
                matched = df.filter(pl.col("symbol").str.contains(clean_sym))
                if not matched.is_empty():
                    reasons = matched["reasons"].to_list() if "reasons" in matched.columns else []
                    return ScreenSnapshot(status="warned", reasons=[str(r) for r in reasons])
        except Exception:
            pass

    passed_path = screen_dir / "passed.csv"
    if passed_path.exists():
        try:
            df = pl.read_csv(passed_path)
            if "symbol" in df.columns:
                matched = df.filter(pl.col("symbol").str.contains(clean_sym))
                if not matched.is_empty():
                    return ScreenSnapshot(status="passed", reasons=[])
        except Exception:
            pass

    return ScreenSnapshot(status="passed", reasons=[])
