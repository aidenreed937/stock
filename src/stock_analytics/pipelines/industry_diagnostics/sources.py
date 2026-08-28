"""中观产业与行业诊断数据加载与辅助函数。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl
import yaml

from stock_analytics.pipelines.industry_diagnostics.types import (
    IndustryConstituentsSnapshot,
    IndustryTechnicalsSnapshot,
    IndustryValuationSnapshot,
    IndustryValueChainSnapshot,
)
from stock_analytics.primitives.indicators import (
    calculate_rsi,
    calculate_sma,
)
from stock_analytics.primitives.units import yuan_to_yi
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog
from stock_reporting.interpretation.industry_diagnostics.logic import (
    evaluate_industry_technicals,
    evaluate_industry_valuation,
)

if TYPE_CHECKING:
    from stock_analytics.pipelines.industry_diagnostics.config import (
        TechnicalsConfig,
        ValuationConfig,
    )


@dataclass
class IndustryFetchContext:
    """行业诊断数据提取上下文。"""

    cat_tu: DataCatalog
    cat_lx: DataCatalog


def compute_percentile(series: pl.Series, current_value: float) -> float | None:
    """计算当前数值在序列中的历史百分位 (0-100)。"""
    valid = series.drop_nulls()
    if valid.is_empty():
        return None
    less_or_equal = (valid <= current_value).sum()
    return round(float(less_or_equal) / len(valid) * 100.0, 1)


def load_10y_treasury_yield(catalog_lx: DataCatalog) -> float | None:
    """读取本地最新中债 10 年期国债收益率 (%)。"""
    try:
        df = catalog_lx.load_dataset("national_debt")
        if not df.is_empty() and "tcm_y10" in df.columns:
            df = df.sort("trade_date")
            val = df["tcm_y10"].tail(1).to_list()[0]
            if val is not None:
                f_val = float(val)
                return round(f_val * 100.0 if f_val < 0.2 else f_val, 2)
    except Exception as exc:
        logger.warning(f"读取国债收益率失败: {exc}")
    return None


def resolve_industry_meta(catalog_tu: DataCatalog, input_str: str) -> tuple[str, str, str, str]:
    """解析行业代码、标准名称、层级 (L1/L2) 与行业编码。"""
    clean = input_str.strip()
    try:
        ic_df = catalog_tu.load_dataset("index_classify")
        if not ic_df.is_empty() and "industry_name" in ic_df.columns:
            matched = ic_df.filter(pl.col("index_code") == clean)
            if matched.is_empty():
                matched = ic_df.filter(pl.col("industry_name") == clean)
            if matched.is_empty():
                matched = ic_df.filter(pl.col("industry_name").str.contains(clean))

            if not matched.is_empty():
                row = matched.to_dicts()[0]
                lvl = "申万一级" if str(row.get("level")) == "L1" else "申万二级"
                return (
                    str(row.get("index_code", clean)),
                    str(row.get("industry_name", clean)),
                    lvl,
                    str(row.get("industry_code", "")),
                )
    except Exception as exc:
        logger.warning(f"解析行业分类失败: {exc}")

    return clean, clean, "申万行业", ""


def load_industry_constituents(
    catalog_tu: DataCatalog, industry_code: str, target_date: date | None = None
) -> IndustryConstituentsSnapshot:
    """查询行业成份股清单并提取市值前 5 龙头梯队。"""
    try:
        mem_df = catalog_tu.load_dataset("index_member")
        if mem_df.is_empty() or "index_code" not in mem_df.columns:
            return IndustryConstituentsSnapshot()

        matched_members = mem_df.filter(pl.col("index_code") == industry_code)
        if matched_members.is_empty():
            return IndustryConstituentsSnapshot()

        if "out_date" in matched_members.columns:
            matched_members = matched_members.filter(
                pl.col("out_date").is_null() | (pl.col("out_date") >= date(2026, 1, 1))
            )

        symbols = matched_members["con_code"].unique().to_list()
        total_count = len(symbols)
        if not symbols:
            return IndustryConstituentsSnapshot(total_count=0)

        # 关联 stock_basic 获取股票名称
        stock_basic = catalog_tu.load_dataset("stock_basic")
        name_map: dict[str, str] = {}
        if not stock_basic.is_empty():
            for row in stock_basic.select(["symbol", "name"]).to_dicts():
                name_map[str(row["symbol"])] = str(row["name"])

        # 关联 daily_basic 获取最新有效交易日市值与 PE
        db_df = catalog_tu.load_dataset("daily_basic", symbols=symbols[:120])
        leader_items: list[dict[str, Any]] = []
        if not db_df.is_empty() and "trade_date" in db_df.columns:
            db_df = db_df.sort("trade_date")
            if target_date is not None:
                db_df = db_df.filter(pl.col("trade_date") <= target_date)
            latest_month_df = db_df.filter(pl.col("trade_date") >= date(2026, 7, 1))
            if not latest_month_df.is_empty():
                latest_db = latest_month_df.group_by("symbol").last()
                for row in latest_db.to_dicts():
                    sym = str(row.get("symbol", ""))
                    total_mv = row.get("total_mv")
                    mv_billion = (
                        yuan_to_yi(float(total_mv), precision=1)
                        if total_mv and float(total_mv) > 1e7
                        else 0.0
                    )
                    leader_items.append(
                        {
                            "symbol": sym,
                            "name": name_map.get(sym, sym),
                            "total_mv_billion": mv_billion,
                            "pe_ttm": (
                                round(float(row["pe_ttm"]), 1)
                                if row.get("pe_ttm") is not None
                                else None
                            ),
                            "roe": None,
                        }
                    )

        leader_items.sort(key=lambda x: x["total_mv_billion"], reverse=True)
        top_5_mv = leader_items[:5]

        return IndustryConstituentsSnapshot(
            total_count=total_count,
            top_market_cap_leaders=top_5_mv,
            top_roe_leaders=[],
        )
    except Exception as exc:
        logger.warning(f"加载行业成份股失败: {exc}")
        return IndustryConstituentsSnapshot()


def load_value_chain_map(
    industry_name: str, config_path: Path | str = "config/industry/value_chain_map.yaml"
) -> IndustryValueChainSnapshot:
    """从本地 YAML 配置中读取该行业的上下游传导图谱与高频监测指标。"""
    cfg_path = Path(config_path)
    if not cfg_path.exists():
        return IndustryValueChainSnapshot()

    try:
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        ind_dict = data.get("industries", {})
        for name_key, details in ind_dict.items():
            if name_key in industry_name or industry_name in name_key:
                return IndustryValueChainSnapshot(
                    upstream=details.get("upstream", []),
                    downstream=details.get("downstream", []),
                    cost_sensitivity=details.get("cost_sensitivity", ""),
                    high_frequency_indicators=details.get("high_frequency_indicators", []),
                )
    except Exception as exc:
        logger.warning(f"读取产业链图谱失败: {exc}")

    return IndustryValueChainSnapshot()


def build_industry_technicals(
    bars_df: pl.DataFrame,
    cfg: TechnicalsConfig,
) -> tuple[str, IndustryTechnicalsSnapshot]:
    """计算行业技术形态快照。"""
    bars_df = calculate_sma(bars_df, window=cfg.ma_short_window, column="close")
    bars_df = calculate_sma(bars_df, window=cfg.ma_medium_window, column="close")
    bars_df = calculate_rsi(bars_df, window=cfg.rsi_window, column="close")

    latest_bar = bars_df.tail(1).to_dicts()[0]
    as_of_date_val = str(latest_bar.get("trade_date", date.today().isoformat()))
    close_price = float(latest_bar.get("close", 0.0))
    pct_chg = float(latest_bar["pct_change"]) if latest_bar.get("pct_change") is not None else None

    ma_short_col = f"sma_{cfg.ma_short_window}"
    ma_med_col = f"sma_{cfg.ma_medium_window}"
    rsi_col = f"rsi_{cfg.rsi_window}"

    ma20 = float(latest_bar[ma_short_col]) if latest_bar.get(ma_short_col) is not None else None
    ma60 = float(latest_bar[ma_med_col]) if latest_bar.get(ma_med_col) is not None else None
    rsi14 = float(latest_bar[rsi_col]) if latest_bar.get(rsi_col) is not None else None

    eval_tech = evaluate_industry_technicals(close_price, ma20, ma60, rsi14)

    return as_of_date_val, IndustryTechnicalsSnapshot(
        close=close_price,
        pct_chg=pct_chg,
        ma20=ma20,
        ma60=ma60,
        rsi14=rsi14,
        trend_description=eval_tech["trend_description"],
    )


def build_industry_valuation(
    bars_df: pl.DataFrame,
    cfg: ValuationConfig,
    catalog_lx: DataCatalog,
) -> IndustryValuationSnapshot:
    """计算行业估值分位数快照。"""
    try:
        latest_bar = bars_df.tail(1).to_dicts()[0]
        pe_val = float(latest_bar["pe"]) if latest_bar.get("pe") is not None else None
        pb_val = float(latest_bar["pb"]) if latest_bar.get("pb") is not None else None

        pe_series = bars_df["pe"].drop_nulls()
        pb_series = bars_df["pb"].drop_nulls()

        pe_5y = (
            compute_percentile(pe_series.tail(cfg.percentile_5y_window), pe_val)
            if pe_val is not None and not pe_series.is_empty()
            else None
        )
        pe_10y = (
            compute_percentile(pe_series.tail(cfg.percentile_10y_window), pe_val)
            if pe_val is not None and not pe_series.is_empty()
            else None
        )
        pb_5y = (
            compute_percentile(pb_series.tail(cfg.percentile_5y_window), pb_val)
            if pb_val is not None and not pb_series.is_empty()
            else None
        )

        treasury_10y = load_10y_treasury_yield(catalog_lx)
        eval_val = evaluate_industry_valuation(
            pe_5y,
            pb_5y,
            threshold_low=cfg.threshold_low,
            threshold_fair=cfg.threshold_fair,
            threshold_neutral=cfg.threshold_neutral,
        )

        return IndustryValuationSnapshot(
            pe_ttm=pe_val,
            pe_percentile_5y=pe_5y,
            pe_percentile_10y=pe_10y,
            pb=pb_val,
            pb_percentile_5y=pb_5y,
            dv_ttm=None,
            treasury_10y_yield=treasury_10y,
            dividend_spread_10y=None,
            valuation_status=eval_val["valuation_status"],
        )
    except Exception as exc:
        logger.warning(f"计算行业估值分位失败: {exc}")
        return IndustryValuationSnapshot()
