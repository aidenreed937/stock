"""中观产业深度诊断与全景量化体检核心管线。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.industry_diagnostics.sources import (
    load_industry_constituents,
    load_value_chain_map,
    resolve_industry_meta,
)
from stock_analytics.pipelines.industry_diagnostics.types import (
    IndustryDiagnosticsResult,
    IndustryFinancialsSnapshot,
    IndustryTechnicalsSnapshot,
    IndustryValuationSnapshot,
)
from stock_analytics.pipelines.stock_diagnostics.sources import (
    compute_percentile,
    load_10y_treasury_yield,
)
from stock_analytics.primitives.indicators import (
    calculate_rsi,
    calculate_sma,
)
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog


def _build_industry_technicals(
    bars_df: pl.DataFrame,
) -> tuple[str, IndustryTechnicalsSnapshot]:
    bars_df = calculate_sma(bars_df, window=20, column="close")
    bars_df = calculate_sma(bars_df, window=60, column="close")
    bars_df = calculate_rsi(bars_df, window=14, column="close")

    latest_bar = bars_df.tail(1).to_dicts()[0]
    as_of_date_val = str(latest_bar.get("trade_date", date.today().isoformat()))
    close_price = float(latest_bar.get("close", 0.0))
    pct_chg = float(latest_bar["pct_change"]) if latest_bar.get("pct_change") is not None else None

    ma20 = float(latest_bar["sma_20"]) if latest_bar.get("sma_20") is not None else None
    ma60 = float(latest_bar["sma_60"]) if latest_bar.get("sma_60") is not None else None
    rsi14 = float(latest_bar["rsi_14"]) if latest_bar.get("rsi_14") is not None else None

    if ma20 is not None and ma60 is not None:
        if close_price >= ma20 >= ma60:
            trend_desc = "多头排列 (站上MA20/MA60，动量偏强)"
        elif close_price <= ma20 <= ma60:
            trend_desc = "空头排列 (受制于MA20/MA60，动量偏弱)"
        elif close_price >= ma20 and close_price < ma60:
            trend_desc = "超跌反弹 (站上MA20但受制于MA60)"
        else:
            trend_desc = "震荡整理 (跌破MA20但高于MA60)"
    else:
        trend_desc = "数据不足以判断均线形态"

    return as_of_date_val, IndustryTechnicalsSnapshot(
        close=close_price,
        pct_chg=pct_chg,
        ma20=ma20,
        ma60=ma60,
        rsi14=rsi14,
        trend_description=trend_desc,
    )


def _build_industry_valuation(
    bars_df: pl.DataFrame, storage_dir: Path | str | None = None
) -> IndustryValuationSnapshot:
    try:
        latest_bar = bars_df.tail(1).to_dicts()[0]
        pe_val = float(latest_bar["pe"]) if latest_bar.get("pe") is not None else None
        pb_val = float(latest_bar["pb"]) if latest_bar.get("pb") is not None else None

        pe_series = bars_df["pe"].drop_nulls()
        pb_series = bars_df["pb"].drop_nulls()

        pe_5y = (
            compute_percentile(pe_series.tail(1250), pe_val)
            if pe_val is not None and not pe_series.is_empty()
            else None
        )
        pe_10y = (
            compute_percentile(pe_series.tail(2500), pe_val)
            if pe_val is not None and not pe_series.is_empty()
            else None
        )
        pb_5y = (
            compute_percentile(pb_series.tail(1250), pb_val)
            if pb_val is not None and not pb_series.is_empty()
            else None
        )

        treasury_10y = load_10y_treasury_yield(storage_dir)

        if pe_5y is not None:
            if pe_5y <= 20.0:
                val_status = "低估区间 (安全边际显著)"
            elif pe_5y <= 40.0:
                val_status = "估值偏低 (具备较好性价比)"
            elif pe_5y <= 70.0:
                val_status = "估值中性 (处于合理震荡中枢)"
            else:
                val_status = "估值偏高 (处于历史较高分位)"
        else:
            val_status = "估值中性"

        return IndustryValuationSnapshot(
            pe_ttm=pe_val,
            pe_percentile_5y=pe_5y,
            pe_percentile_10y=pe_10y,
            pb=pb_val,
            pb_percentile_5y=pb_5y,
            dv_ttm=None,
            treasury_10y_yield=treasury_10y,
            dividend_spread_10y=None,
            valuation_status=val_status,
        )
    except Exception as exc:
        logger.warning(f"计算行业估值分位失败: {exc}")
        return IndustryValuationSnapshot()


def run_industry_diagnostics(
    industry: str,
    target_date: date | None = None,
    storage_dir: Path | str | None = None,
) -> IndustryDiagnosticsResult:
    """执行申万中观产业全景量化诊断。

    一站式计算行业行情均线、PE/PB 历史分位数、成份股龙头梯队与产业链图谱。
    """
    catalog_tu = DataCatalog("tushare", storage_dir=storage_dir)
    std_code, std_name, level, _raw_code = resolve_industry_meta(catalog_tu, industry)

    # 1. 加载行业行情
    sw_df = catalog_tu.load_dataset("sw_daily", symbols=[std_code])
    if not sw_df.is_empty() and "trade_date" in sw_df.columns:
        sw_df = sw_df.sort("trade_date")
        if target_date is not None:
            sw_df = sw_df.filter(pl.col("trade_date") <= target_date)

    if sw_df.is_empty():
        raise ValueError(f"未在本地 Curated 数据集中找到行业 {industry} ({std_code}) 的行情数据")

    as_of_date_val, tech_snapshot = _build_industry_technicals(sw_df)

    # 2. 行业估值分位与利差
    val_snapshot = _build_industry_valuation(sw_df, storage_dir=storage_dir)

    # 3. 行业基本面（预留与兜底）
    fin_snapshot = IndustryFinancialsSnapshot(
        report_date=as_of_date_val,
        roe_avg=None,
        revenue_yoy=None,
        netprofit_yoy=None,
        gross_margin=None,
        cycle_stage="存量博弈与结构分化期",
    )

    # 4. 行业成份股龙头梯队
    const_snapshot = load_industry_constituents(catalog_tu, std_code)

    # 5. 产业链上下游图谱
    chain_snapshot = load_value_chain_map(std_name)

    return IndustryDiagnosticsResult(
        industry_code=std_code,
        industry_name=std_name,
        level=level,
        as_of_date=as_of_date_val,
        technicals=tech_snapshot,
        valuation=val_snapshot,
        financials=fin_snapshot,
        constituents=const_snapshot,
        value_chain=chain_snapshot,
    )
