"""投资假设跨周期验证与归因分析管线。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import yaml

from stock_analytics.pipelines.stock_diagnostics.pipeline import run_stock_diagnostics
from stock_analytics.pipelines.thesis_review.types import (
    InvestmentThesis,
    ThesisReviewAttribution,
    ThesisReviewResult,
)
from stock_core.utils.logger import logger


def load_or_create_thesis(
    symbol: str,
    thesis_date: date | None = None,
    theses_dir: Path | str | None = None,
    storage_dir: Path | str | None = None,
) -> InvestmentThesis:
    """加载已有的投资假设文件；若不存在，则基于历史真实数据自动初始化基准假设。"""
    t_dir = Path(theses_dir or "reports/theses")
    t_dir.mkdir(parents=True, exist_ok=True)

    # 1. 尝试查找已保存的 yaml 假设
    pattern = f"{symbol}*.yaml"
    found_files = list(t_dir.glob(pattern))
    if found_files:
        try:
            with open(found_files[0], encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            inv = raw.get("investment_thesis", {})
            risk = raw.get("risk_controls", {})
            return InvestmentThesis(
                thesis_id=str(raw.get("thesis_id", f"{symbol}_thesis")),
                symbol=str(raw.get("symbol", symbol)),
                name=str(raw.get("name", symbol)),
                created_date=str(raw.get("created_date", "2026-05-20")),
                base_price=float(raw.get("base_price", 100.0)),
                initial_pe_ttm=float(raw["initial_pe_ttm"]) if raw.get("initial_pe_ttm") else None,
                initial_dividend_yield=float(raw["initial_dividend_yield"])
                if raw.get("initial_dividend_yield")
                else None,
                expected_growth=float(inv["expected_net_profit_growth"])
                if inv.get("expected_net_profit_growth")
                else None,
                expected_pe_anchor=float(inv["expected_pe_anchor"])
                if inv.get("expected_pe_anchor")
                else None,
                stop_loss_pct=float(risk.get("max_drawdown_stop_loss", -15.0)),
                catalysts=inv.get("catalysts", []),
                invalidation_conditions=risk.get("invalidation_conditions", []),
            )
        except Exception as exc:
            logger.warning(f"解析已有假设文件失败: {exc}")

    # 2. 自动生成历史基线假设 (默认 90 天前)
    base_dt = thesis_date or (date.today() - timedelta(days=90))
    hist_diag = run_stock_diagnostics(symbol=symbol, target_date=base_dt, storage_dir=storage_dir)

    return InvestmentThesis(
        thesis_id=f"{symbol}_{base_dt.isoformat()}",
        symbol=symbol,
        name=hist_diag.name,
        created_date=base_dt.isoformat(),
        base_price=hist_diag.technicals.close,
        initial_pe_ttm=hist_diag.valuation.pe_ttm,
        initial_dividend_yield=hist_diag.valuation.dv_ttm,
        expected_growth=10.0,
        expected_pe_anchor=hist_diag.valuation.pe_ttm,
        stop_loss_pct=-15.0,
        catalysts=["核心产品动销稳健", "行业龙头市场份额提升"],
        invalidation_conditions=["单季净利增速转负或失速", "股价回撤达到 -15% 严格止损线"],
    )


def run_thesis_review(
    symbol: str,
    thesis_date: date | None = None,
    target_date: date | None = None,
    storage_dir: Path | str | None = None,
    theses_dir: Path | str | None = None,
) -> ThesisReviewResult:
    """执行跨周期投资假设验证与归因分析流水线。"""
    # 1. 获取初始假设
    thesis = load_or_create_thesis(
        symbol=symbol,
        thesis_date=thesis_date,
        theses_dir=theses_dir,
        storage_dir=storage_dir,
    )

    # 2. 获取当前诊断事实
    curr_diag = run_stock_diagnostics(
        symbol=symbol,
        target_date=target_date,
        storage_dir=storage_dir,
    )

    # 3. 计算跨周期变化与收益归因
    curr_price = curr_diag.technicals.close
    price_chg_pct = round(((curr_price - thesis.base_price) / thesis.base_price) * 100, 2)

    pe_chg_pct: float | None = None
    if thesis.initial_pe_ttm and curr_diag.valuation.pe_ttm:
        pe_chg_pct = round(
            ((curr_diag.valuation.pe_ttm - thesis.initial_pe_ttm) / thesis.initial_pe_ttm) * 100,
            2,
        )

    act_growth = curr_diag.financials.netprofit_yoy
    growth_gap: float | None = None
    if act_growth is not None and thesis.expected_growth is not None:
        growth_gap = round(act_growth - thesis.expected_growth, 2)

    # 4. 风控与假设证伪判定
    is_stop_loss = price_chg_pct <= thesis.stop_loss_pct
    is_trap = curr_diag.valuation.value_trap_warning

    reflection_notes: list[str] = []
    action_guidance: list[str] = []

    if pe_chg_pct is not None and pe_chg_pct < -10.0:
        reflection_notes.append(
            f"估值端收缩 {abs(pe_chg_pct)}%，反映市场对远期中枢预期下移或风险偏好降低"
        )
    if growth_gap is not None and growth_gap < 0:
        reflection_notes.append(
            f"业绩端实际增速 ({act_growth}%) 低于预期 ({thesis.expected_growth}%)，存在盈利预期偏差"
        )

    if is_stop_loss:
        verdict = "🚨 触及严格止损线 (建议执行风控纪律)"
        action_guidance.append(
            "组合触及 -15% 最大回撤容忍红线，坚决执行风控纪律，严禁左侧盲目补仓摊低成本"
        )
    elif is_trap:
        verdict = "⚠️ 触发价值陷阱预警 (防御观望)"
        action_guidance.append(
            "当前标的处于低估值但净利失速状态，必须等待连续两季财报净利拐点或放量站上 MA60 确认"
        )
    elif price_chg_pct > 0 and (growth_gap is None or growth_gap >= 0):
        verdict = "🟢 投资假设有效兑现 (顺势持有)"
        action_guidance.append("业绩与估值表现符合预期，维持底仓配置，结合均线多头形态持有")
    else:
        verdict = "🟡 假设处于震荡磨底期 (耐心跟踪)"
        action_guidance.append("股价与估值处于合理区间波动，密切跟踪高频产业动销与下一季财报预告")

    d_t0 = date.fromisoformat(thesis.created_date)
    d_t1 = date.fromisoformat(curr_diag.as_of_date)
    days_elapsed = (d_t1 - d_t0).days

    attribution = ThesisReviewAttribution(
        current_price=curr_price,
        price_change_pct=price_chg_pct,
        actual_growth=act_growth,
        growth_gap=growth_gap,
        current_pe_ttm=curr_diag.valuation.pe_ttm,
        pe_change_pct=pe_chg_pct,
        is_stop_loss_triggered=is_stop_loss,
        is_value_trap=is_trap,
        verdict=verdict,
        reflection_notes=reflection_notes,
        action_guidance=action_guidance,
    )

    return ThesisReviewResult(
        thesis=thesis,
        as_of_date=curr_diag.as_of_date,
        days_elapsed=days_elapsed,
        attribution=attribution,
    )
