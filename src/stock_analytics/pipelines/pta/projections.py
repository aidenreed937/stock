"""PTA 与聚酯化纤双雄未来营收与利润分部 (SOTP) 预测引擎。

支持恒力石化 (600346.SH) 与桐昆股份 (601233.SH) 的：
1. 业务分部预测 (SOTP Bottom-Up)：炼化裂解产品、PTA、聚酯长丝、浙石化 20% 投资收益；
2. 费用桥梁与财务去杠杆：重资产有息负债在周期不同阶段的偿债与利息收缩测算；
3. 三情景估值推演：周期底部磨底 (trough)、中性中枢复苏 (mid_cycle)、景气高峰繁荣 (peak) 的业绩与目标市值；
4. 二维敏感性分析：产品价格 vs 原料 PX 价格的归母净利敏感性矩阵。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from stock_data.catalog import DataCatalog

logger = logging.getLogger(__name__)

DEFAULT_PROJECTION_CONFIG_PATH = Path("config/industry/chemicals/pta/company_projections.yaml")


@dataclass(frozen=True, slots=True)
class SegmentResult:
    """单个业务分部的预测结果。"""

    segment_key: str
    segment_name: str
    sales_volume_w_tons: float
    unit_price_cny: float
    unit_cost_cny: float
    unit_gross_margin_cny: float
    revenue_cny: float
    gross_profit_cny: float
    gross_margin_ratio: float


@dataclass(frozen=True, slots=True)
class CompanyFinancialContext:
    """企业真实财报动态装配上下文。"""

    symbol: str
    report_date: str | None
    ann_date: str | None
    total_shares: float
    net_assets_cny: float
    bps: float
    annualized_finance_expense: float | None
    interest_bearing_debt_cny: float | None = None
    money_cap_cny: float | None = None
    historical_pb_percentiles: dict[str, float] | None = None
    latest_market_pb: float | None = None
    source_mode: str = "static_config"


@dataclass(frozen=True, slots=True)
class PtaProjectionResult:
    """企业全业务分部合并与情景测算结果。"""

    symbol: str
    company_name: str
    scenario_key: str
    scenario_name: str
    segments: list[SegmentResult]
    total_revenue_cny: float
    total_gross_profit_cny: float
    base_operating_expense_cny: float
    finance_expense_cny: float
    equity_investment_income_cny: float
    total_profit_before_tax_cny: float
    income_tax_cny: float
    net_profit_cny: float
    eps_cny: float
    fair_market_value_cny: float
    fair_price_cny: float
    target_pe: float | None
    implied_pb: float
    valuation_method: str = "pe_earnings"
    target_pb: float | None = None
    implied_roe: float = 0.0


def build_financial_context(
    symbol: str,
    catalog: DataCatalog | None = None,
) -> CompanyFinancialContext:
    """从本地 Curated 数据层动态提取公司总股本、每股净资产、财务费用与 PB 历史分位。"""
    cat = catalog or DataCatalog("tushare")

    try:
        bs = cat.load_dataset("balancesheet", symbols=[symbol])
        inc = cat.load_dataset("income", symbols=[symbol])
        daily = cat.load_dataset("daily_basic", symbols=[symbol])

        if bs.is_empty() or inc.is_empty():
            return _fallback_context(symbol)

        # 最新资产负债表
        latest_bs = bs.sort("end_date", descending=True).head(1).to_dicts()[0]
        end_date = str(latest_bs.get("end_date"))
        ann_date = str(latest_bs.get("ann_date"))

        # 总股本与净资产
        total_share = float(latest_bs.get("total_share") or 1.0)
        net_assets = float(latest_bs.get("total_hldr_eqy_exc_min_int") or 1.0)
        bps = net_assets / total_share if total_share > 0 else 1.0

        # 有息负债
        st_borr = float(latest_bs.get("st_borr") or 0.0)
        non_cur_due = float(latest_bs.get("non_cur_liab_due_1y") or 0.0)
        lt_borr = float(latest_bs.get("lt_borr") or 0.0)
        bonds = float(latest_bs.get("bond_payable") or 0.0)
        total_debt = st_borr + non_cur_due + lt_borr + bonds
        money_cap = float(latest_bs.get("money_cap") or 0.0)

        # 财务费用年化
        annual_fin_exp = _annualize_finance_expense(inc, symbol)

        # 估值历史分位数
        pb_pcts, latest_pb = _calc_historical_pb(daily)

        return CompanyFinancialContext(
            symbol=symbol,
            report_date=end_date,
            ann_date=ann_date,
            total_shares=total_share,
            net_assets_cny=net_assets,
            bps=bps,
            annualized_finance_expense=annual_fin_exp,
            interest_bearing_debt_cny=total_debt,
            money_cap_cny=money_cap,
            historical_pb_percentiles=pb_pcts,
            latest_market_pb=latest_pb,
            source_mode="dynamic_catalog",
        )
    except Exception as exc:
        logger.warning(f"动态构建 {symbol} 财务上下文失败，使用回退配置: {exc}")
        return _fallback_context(symbol)


def _annualize_finance_expense(inc: pl.DataFrame, symbol: str) -> float:
    """根据最新定期报告年化财务费用。"""
    sorted_inc = inc.sort("end_date", descending=True)
    if sorted_inc.is_empty():
        return 4.5e9 if symbol.startswith("600346") else 1.0e9

    latest = sorted_inc.head(1).to_dicts()[0]
    ed = str(latest.get("end_date"))
    raw_exp = float(latest.get("fin_exp") or 0.0)
    month = int(ed[5:7]) if len(ed) >= 7 else 12

    factor = 12.0 / max(1, month)
    return raw_exp * factor


def _calc_historical_pb(daily: pl.DataFrame) -> tuple[dict[str, float], float | None]:
    """计算滚动 10 年 PB 分位数 (P05/P50/P85) 与最新 PB。"""
    if daily.is_empty() or "pb" not in daily.columns:
        return {"P05": 1.0, "P50": 1.6, "P85": 2.5}, 1.5

    valid_pbs = daily.filter(pl.col("pb").is_not_null() & (pl.col("pb") > 0)).sort("trade_date")
    if valid_pbs.is_empty():
        return {"P05": 1.0, "P50": 1.6, "P85": 2.5}, 1.5

    latest_pb = float(valid_pbs.tail(1).get_column("pb")[0])
    pb_col = valid_pbs.get_column("pb")
    q05 = pb_col.quantile(0.05)
    q50 = pb_col.quantile(0.50)
    q85 = pb_col.quantile(0.85)
    p05 = float(q05) if q05 is not None else 1.0
    p50 = float(q50) if q50 is not None else 1.6
    p85 = float(q85) if q85 is not None else 2.5

    return {"P05": round(p05, 2), "P50": round(p50, 2), "P85": round(p85, 2)}, round(latest_pb, 2)


def _fallback_context(symbol: str) -> CompanyFinancialContext:
    """硬编码安全兜底参数。"""
    if symbol == "600346.SH":
        # 恒力石化
        return CompanyFinancialContext(
            symbol=symbol,
            report_date="2025-12-31",
            ann_date="2026-04-15",
            total_shares=7.039e9,
            net_assets_cny=6.677e10,
            bps=9.48,
            annualized_finance_expense=4.38e9,
            interest_bearing_debt_cny=1.515e11,
            money_cap_cny=2.5e10,
            historical_pb_percentiles={"P05": 1.15, "P50": 1.78, "P85": 2.92},
            latest_market_pb=1.45,
            source_mode="static_fallback",
        )
    # 桐昆股份 601233.SH
    return CompanyFinancialContext(
        symbol=symbol,
        report_date="2025-12-31",
        ann_date="2026-04-20",
        total_shares=2.411e9,
        net_assets_cny=3.832e10,
        bps=15.89,
        annualized_finance_expense=9.7e8,
        interest_bearing_debt_cny=5.588e10,
        money_cap_cny=1.2e10,
        historical_pb_percentiles={"P05": 0.85, "P50": 1.35, "P85": 2.10},
        latest_market_pb=0.98,
        source_mode="static_fallback",
    )


class PtaCompanyProjectionEngine:
    """PTA 双雄 (恒力石化 vs 桐昆股份) 业务分部测算与情景推演引擎。"""

    def __init__(self, config_path: Path | str | None = None) -> None:
        self.config_path = Path(config_path) if config_path else DEFAULT_PROJECTION_CONFIG_PATH
        self.config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            logger.warning(f"PTA 分部预测配置不存在: {self.config_path}")
            return {}
        return yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}

    def project_company(
        self,
        symbol: str,
        scenario_key: str,
        context: CompanyFinancialContext | None = None,
        custom_prices: dict[str, float] | None = None,
    ) -> PtaProjectionResult:
        """针对指定公司与宏观情景执行自底向上 SOTP 测算。"""
        cfg_companies = self.config.get("companies", {})
        if symbol not in cfg_companies:
            raise ValueError(f"未在配置中找到公司: {symbol}")

        comp_cfg = cfg_companies[symbol]
        scenarios = self.config.get("scenarios", {})
        if scenario_key not in scenarios:
            raise ValueError(f"未知情景: {scenario_key}")

        sc_cfg = scenarios[scenario_key]
        ctx = context or build_financial_context(symbol)

        tax_rate = float(comp_cfg.get("tax_rate", 0.15))
        base_exp_ratio = float(comp_cfg.get("base_expense_ratio", 0.035))
        fin_scale = float(
            comp_cfg.get("finance_expense_scale_by_scenario", {}).get(scenario_key, 1.0)
        )

        # 测算分部
        segment_results: list[SegmentResult] = []
        tot_rev = 0.0
        tot_gp = 0.0
        equity_inv_income = 0.0

        segments_cfg = comp_cfg.get("segments", {})
        for seg_key, s_data in segments_cfg.items():
            # 权益投资特殊处理 (如桐昆浙石化投资收益)
            if s_data.get("type") == "equity_investment":
                inv_by_sc = s_data.get("annual_investment_income_by_scenario", {})
                equity_inv_income += float(inv_by_sc.get(scenario_key, 0.0))
                continue

            # 贸易及其他
            if s_data.get("source_mode") == "dynamic_mainbz":
                rev_fix = float(s_data.get("revenue_fixed_cny", 5.0e9))
                gm_rate = float(s_data.get("gross_margin_rate", 0.05))
                gp_fix = rev_fix * gm_rate
                tot_rev += rev_fix
                tot_gp += gp_fix
                segment_results.append(
                    SegmentResult(
                        segment_key=seg_key,
                        segment_name=s_data.get("name", seg_key),
                        sales_volume_w_tons=0.0,
                        unit_price_cny=0.0,
                        unit_cost_cny=0.0,
                        unit_gross_margin_cny=0.0,
                        revenue_cny=rev_fix,
                        gross_profit_cny=gp_fix,
                        gross_margin_ratio=gm_rate,
                    )
                )
                continue

            # 工业产品分部
            sales_w_tons = float(s_data.get("sales_w_tons", 0.0))
            sales_tons = sales_w_tons * 10000.0

            # 吨毛利与价格推导
            gm_by_sc = s_data.get("unit_gross_margin_by_scenario", {})
            unit_gm = float(gm_by_sc.get(scenario_key, 300.0))

            # 基准单价估算
            if "refining" in seg_key:
                unit_price = (
                    6800.0
                    if scenario_key == "mid_cycle"
                    else (5800.0 if scenario_key == "trough" else 8000.0)
                )
            elif "pta" in seg_key:
                unit_price = float(sc_cfg.get("pta_spot_price_cny", 5400.0))
                # 若提供 custom_prices，动态覆盖
                if custom_prices and "pta_price" in custom_prices:
                    unit_price = custom_prices["pta_price"]
                    px_p = custom_prices.get(
                        "px_price", float(sc_cfg.get("px_cfr_price_cny", 7500.0))
                    )
                    fixed_c = float(s_data.get("fixed_cost", 360.0))
                    unit_gm = unit_price - 0.655 * px_p - fixed_c
            elif "polyester_filament" in seg_key or "polyester_products" in seg_key:
                unit_price = float(sc_cfg.get("filament_poy_price_cny", 7800.0))
                if custom_prices and "filament_price" in custom_prices:
                    unit_price = custom_prices["filament_price"]
                    # 动态价差推导
                    unit_gm = unit_price * 0.10
            else:
                unit_price = 7000.0

            unit_cost = unit_price - unit_gm
            seg_rev = sales_tons * unit_price
            seg_gp = sales_tons * unit_gm
            gm_ratio = seg_gp / seg_rev if seg_rev > 0 else 0.0

            tot_rev += seg_rev
            tot_gp += seg_gp

            segment_results.append(
                SegmentResult(
                    segment_key=seg_key,
                    segment_name=s_data.get("name", seg_key),
                    sales_volume_w_tons=sales_w_tons,
                    unit_price_cny=unit_price,
                    unit_cost_cny=unit_cost,
                    unit_gross_margin_cny=unit_gm,
                    revenue_cny=seg_rev,
                    gross_profit_cny=seg_gp,
                    gross_margin_ratio=gm_ratio,
                )
            )

        # 费用桥梁
        base_opex = tot_rev * base_exp_ratio
        fin_exp_base = (
            ctx.annualized_finance_expense
            if ctx.annualized_finance_expense is not None
            else (4.5e9 if symbol.startswith("600346") else 1.0e9)
        )
        fin_exp = fin_exp_base * fin_scale

        # 利润与税
        ebit = tot_gp - base_opex
        pbt = ebit - fin_exp + equity_inv_income
        tax = max(0.0, pbt * tax_rate)
        net_profit = pbt - tax

        shares = ctx.total_shares if ctx.total_shares > 0 else 1.0
        eps = net_profit / shares

        # 周期双轨双锚估值：资产重置底线 (PB Floor) vs 稳态盈利对账 (PE / ROE)
        raw_pe = sc_cfg.get("pe_multiple")
        target_pe = float(raw_pe) if raw_pe is not None else None
        target_pb_map = sc_cfg.get("target_pb_by_symbol", {})
        default_target_pb = 1.05 if symbol.startswith("600346") else 0.85
        target_pb = float(target_pb_map.get(symbol, default_target_pb))

        net_assets = ctx.net_assets_cny if ctx.net_assets_cny > 0 else 1.0
        implied_roe = (net_profit / net_assets) * 100.0 if net_assets > 0 else 0.0

        valuation_mode = str(sc_cfg.get("valuation_mode", "pe_earnings"))
        if valuation_mode == "pb_asset_floor" or target_pe is None or net_profit <= 0:
            valuation_method = "pb_asset_floor"
            fair_mv = net_assets * target_pb
            fair_price = fair_mv / shares if shares > 0 else 0.0
            implied_pb = target_pb
        else:
            valuation_method = "pe_earnings"
            fair_mv = max(0.0, net_profit * target_pe)
            fair_price = fair_mv / shares if shares > 0 else 0.0
            implied_pb = fair_mv / net_assets

        return PtaProjectionResult(
            symbol=symbol,
            company_name=comp_cfg.get("name", symbol),
            scenario_key=scenario_key,
            scenario_name=sc_cfg.get("name", scenario_key),
            segments=segment_results,
            total_revenue_cny=tot_rev,
            total_gross_profit_cny=tot_gp,
            base_operating_expense_cny=base_opex,
            finance_expense_cny=fin_exp,
            equity_investment_income_cny=equity_inv_income,
            total_profit_before_tax_cny=pbt,
            income_tax_cny=tax,
            net_profit_cny=net_profit,
            eps_cny=eps,
            fair_market_value_cny=fair_mv,
            fair_price_cny=fair_price,
            target_pe=target_pe,
            implied_pb=implied_pb,
            valuation_method=valuation_method,
            target_pb=target_pb,
            implied_roe=implied_roe,
        )

    def project_all_scenarios(
        self,
        symbol: str,
        context: CompanyFinancialContext | None = None,
    ) -> list[PtaProjectionResult]:
        """对目标企业依次输出 trough / mid_cycle / peak 三大情景的预测结果。"""
        ctx = context or build_financial_context(symbol)
        scenarios = ["trough", "mid_cycle", "peak"]
        results: list[PtaProjectionResult] = []
        for sc in scenarios:
            results.append(self.project_company(symbol=symbol, scenario_key=sc, context=ctx))
        return results

    def generate_sensitivity_matrix(
        self,
        symbol: str,
        x_name: str,
        x_values: list[float],
        y_name: str,
        y_values: list[float],
        base_scenario: str = "mid_cycle",
        context: CompanyFinancialContext | None = None,
    ) -> pl.DataFrame:
        """生成产品售价 (X) vs 原料 PX 成本 (Y) 的二维归母净利润 (亿元) 敏感性矩阵。"""
        ctx = context or build_financial_context(symbol)
        rows: list[dict[str, Any]] = []

        for y in y_values:
            row_dict: dict[str, Any] = {f"{y_name}_cny": y}
            for x in x_values:
                custom_p = {
                    "pta_price" if "pta" in x_name else "filament_price": x,
                    "px_price": y,
                }
                res = self.project_company(
                    symbol=symbol,
                    scenario_key=base_scenario,
                    context=ctx,
                    custom_prices=custom_p,
                )
                net_profit_yi = round(res.net_profit_cny / 1.0e8, 2)
                row_dict[f"{x:.0f}"] = net_profit_yi
            rows.append(row_dict)

        return pl.DataFrame(rows)
