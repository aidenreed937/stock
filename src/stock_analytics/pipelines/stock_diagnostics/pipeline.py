"""个股深度诊断与全景量化体检核心管线。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.stock_diagnostics.sources import (
    compute_percentile,
    load_10y_treasury_yield,
    load_capital_flow,
    load_industry_rank,
    load_latest_forecast,
    load_market_temperature_context,
    load_screen_status,
    norm_to_billion,
    resolve_symbol_meta,
)
from stock_analytics.pipelines.stock_diagnostics.types import (
    FinancialsSnapshot,
    MarketContextSnapshot,
    StockDiagnosticsResult,
    TechnicalsSnapshot,
    ValuationSnapshot,
)
from stock_analytics.primitives.indicators import (
    calculate_rsi,
    calculate_sma,
)
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog


def _build_technicals(
    bars_df: pl.DataFrame,
) -> tuple[str, TechnicalsSnapshot]:
    bars_df = calculate_sma(bars_df, window=20, column="close")
    bars_df = calculate_sma(bars_df, window=60, column="close")
    bars_df = calculate_sma(bars_df, window=120, column="close")
    bars_df = calculate_rsi(bars_df, window=14, column="close")

    latest_bar = bars_df.tail(1).to_dicts()[0]
    as_of_date_val = str(latest_bar.get("trade_date", date.today().isoformat()))
    close_price = float(latest_bar.get("close", 0.0))
    pct_chg = float(latest_bar["pct_chg"]) if latest_bar.get("pct_chg") is not None else None
    pre_close = float(latest_bar["pre_close"]) if latest_bar.get("pre_close") is not None else None

    ma20 = float(latest_bar["sma_20"]) if latest_bar.get("sma_20") is not None else None
    ma60 = float(latest_bar["sma_60"]) if latest_bar.get("sma_60") is not None else None
    ma120 = float(latest_bar["sma_120"]) if latest_bar.get("sma_120") is not None else None
    rsi14 = float(latest_bar["rsi_14"]) if latest_bar.get("rsi_14") is not None else None

    if ma20 is not None and ma60 is not None:
        if close_price >= ma20 >= ma60:
            trend_desc = "多头排列 (站上MA20/MA60，趋势偏强)"
        elif close_price <= ma20 <= ma60:
            trend_desc = "空头排列 (位于MA20/MA60下方，趋势偏弱)"
        elif close_price >= ma20 and close_price < ma60:
            trend_desc = "中短期反弹 (站上MA20但受制于MA60)"
        else:
            trend_desc = "高位震荡 (跌破MA20但高于MA60)"
    else:
        trend_desc = "数据不足以判断长期均线形态"

    return as_of_date_val, TechnicalsSnapshot(
        close=close_price,
        pre_close=pre_close,
        pct_chg=pct_chg,
        ma20=ma20,
        ma60=ma60,
        ma120=ma120,
        rsi14=rsi14,
        trend_description=trend_desc,
    )


def _build_valuation(
    catalog: DataCatalog,
    std_symbol: str,
    target_date: date | None,
    treasury_yield: float | None,
    growth_deceleration: bool,
) -> ValuationSnapshot:
    try:
        basic_val_df = catalog.load_dataset("daily_basic", symbols=[std_symbol])
        if basic_val_df.is_empty() or "trade_date" not in basic_val_df.columns:
            return ValuationSnapshot()
        basic_val_df = basic_val_df.sort("trade_date")
        if target_date is not None:
            basic_val_df = basic_val_df.filter(pl.col("trade_date") <= target_date)
        if basic_val_df.is_empty():
            return ValuationSnapshot()

        latest_val = basic_val_df.tail(1).to_dicts()[0]
        pe_ttm_val = float(latest_val["pe_ttm"]) if latest_val.get("pe_ttm") is not None else None
        pb_val = float(latest_val["pb"]) if latest_val.get("pb") is not None else None
        ps_val = float(latest_val["ps_ttm"]) if latest_val.get("ps_ttm") is not None else None
        dv_val = float(latest_val["dv_ttm"]) if latest_val.get("dv_ttm") is not None else None
        turnover_val = (
            float(latest_val["turnover_rate"])
            if latest_val.get("turnover_rate") is not None
            else None
        )

        total_mv = norm_to_billion(
            float(latest_val["total_mv"]) if latest_val.get("total_mv") is not None else None
        )
        circ_mv = norm_to_billion(
            float(latest_val["circ_mv"]) if latest_val.get("circ_mv") is not None else None
        )

        pe_series = basic_val_df["pe_ttm"]
        pe_p3y = (
            compute_percentile(pe_series.tail(750), pe_ttm_val) if pe_ttm_val is not None else None
        )
        pe_p5y = (
            compute_percentile(pe_series.tail(1250), pe_ttm_val) if pe_ttm_val is not None else None
        )
        pe_p10y = (
            compute_percentile(pe_series.tail(2500), pe_ttm_val) if pe_ttm_val is not None else None
        )

        pb_series = basic_val_df["pb"]
        pb_p5y = compute_percentile(pb_series.tail(1250), pb_val) if pb_val is not None else None

        # 利差与价值陷阱预警
        dividend_spread: float | None = None
        if dv_val is not None and treasury_yield is not None:
            dividend_spread = round(dv_val - treasury_yield, 2)

        value_trap = bool(pe_p5y is not None and pe_p5y <= 25.0 and growth_deceleration)

        return ValuationSnapshot(
            pe_ttm=pe_ttm_val,
            pe_percentile_3y=pe_p3y,
            pe_percentile_5y=pe_p5y,
            pe_percentile_10y=pe_p10y,
            pb=pb_val,
            pb_percentile_5y=pb_p5y,
            ps_ttm=ps_val,
            dv_ttm=dv_val,
            treasury_10y_yield=treasury_yield,
            dividend_spread_10y=dividend_spread,
            total_mv_billion=total_mv,
            circ_mv_billion=circ_mv,
            turnover_rate=turnover_val,
            value_trap_warning=value_trap,
        )
    except Exception as exc:
        logger.warning(f"计算估值指标失败: {exc}")
        return ValuationSnapshot()


def _build_financials(
    catalog: DataCatalog, std_symbol: str, target_date: date | None
) -> FinancialsSnapshot:
    try:
        latest_fc = load_latest_forecast(catalog, std_symbol, target_date)
        fina_df = catalog.load_dataset("fina_indicator", symbols=[std_symbol])
        if fina_df.is_empty() or "end_date" not in fina_df.columns:
            return FinancialsSnapshot(latest_forecast=latest_fc)
        fina_df = fina_df.sort("end_date")
        if target_date is not None and "ann_date" in fina_df.columns:
            fina_df = fina_df.filter(pl.col("ann_date") <= target_date)
        if fina_df.is_empty():
            return FinancialsSnapshot(latest_forecast=latest_fc)

        latest_fin = fina_df.tail(1).to_dicts()[0]
        np_yoy = (
            float(latest_fin["netprofit_yoy"])
            if latest_fin.get("netprofit_yoy") is not None
            else None
        )

        growth_decel = bool(np_yoy is not None and np_yoy <= 0.0)
        # 如果预告净利润上限也 <= 0，确认失速
        if latest_fc and latest_fc.get("p_change_max") is not None:
            if float(latest_fc["p_change_max"]) <= 0.0:
                growth_decel = True

        return FinancialsSnapshot(
            report_date=str(latest_fin.get("end_date", "")),
            roe=(float(latest_fin["roe"]) if latest_fin.get("roe") is not None else None),
            netprofit_yoy=np_yoy,
            revenue_yoy=(
                float(latest_fin["tr_yoy"]) if latest_fin.get("tr_yoy") is not None else None
            ),
            gross_margin=(
                float(latest_fin["grossprofit_margin"])
                if latest_fin.get("grossprofit_margin") is not None
                else None
            ),
            debt_to_assets=(
                float(latest_fin["debt_to_assets"])
                if latest_fin.get("debt_to_assets") is not None
                else None
            ),
            growth_deceleration=growth_decel,
            latest_forecast=latest_fc,
        )
    except Exception as exc:
        logger.warning(f"加载财务指标失败: {exc}")
        return FinancialsSnapshot()


def run_stock_diagnostics(
    symbol: str,
    target_date: date | None = None,
    storage_dir: Path | str | None = None,
) -> StockDiagnosticsResult:
    """执行个股全景量化诊断聚合。

    一站式计算技术均线、估值分位、财务指标、排雷状态与大盘温度。
    """
    catalog = DataCatalog("tushare", storage_dir=storage_dir)
    std_symbol, name, industry, area, market = resolve_symbol_meta(catalog, symbol)

    # 1. 行情与技术面
    bars_df = catalog.load_dataset("stock_daily_bar", symbols=[std_symbol])
    if not bars_df.is_empty() and "trade_date" in bars_df.columns:
        bars_df = bars_df.sort("trade_date")
        if target_date is not None:
            bars_df = bars_df.filter(pl.col("trade_date") <= target_date)

    if bars_df.is_empty():
        raise ValueError(f"未在本地 Curated 数据集中找到标的 {symbol} 的行情数据")

    as_of_date_val, tech_snapshot = _build_technicals(bars_df)

    # 2. 宏观利率与财务指标
    treasury_10y = load_10y_treasury_yield(storage_dir)
    fin_snapshot = _build_financials(catalog, std_symbol, target_date)

    # 3. 估值指标 (联动利率计算股息安全垫与价值陷阱预警)
    val_snapshot = _build_valuation(
        catalog,
        std_symbol,
        target_date,
        treasury_10y,
        fin_snapshot.growth_deceleration,
    )

    # 4. 资金流向与微观动销代理
    cap_flow = load_capital_flow(catalog, std_symbol, target_date)

    # 5. 排雷状态
    screen_snapshot = load_screen_status(std_symbol)

    # 6. 市场与行业宏观背景
    temp_score, temp_band, temp_date = load_market_temperature_context()
    ind_rank_str = load_industry_rank(industry)
    market_ctx = MarketContextSnapshot(
        as_of_date=temp_date or as_of_date_val,
        temperature_score=temp_score,
        temperature_band=temp_band,
        industry_name=industry,
        industry_rank=ind_rank_str,
    )

    return StockDiagnosticsResult(
        symbol=std_symbol,
        name=name,
        as_of_date=as_of_date_val,
        industry=industry,
        area=area,
        market=market,
        technicals=tech_snapshot,
        valuation=val_snapshot,
        financials=fin_snapshot,
        capital_flow=cap_flow,
        screen=screen_snapshot,
        market_context=market_ctx,
    )
