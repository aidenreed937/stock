"""个股深度诊断与全景体检领域模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TechnicalsSnapshot:
    """行情与技术面指标快照。"""

    close: float
    pre_close: float | None = None
    pct_chg: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    ma120: float | None = None
    rsi14: float | None = None
    trend_description: str = "震荡整理"


@dataclass(frozen=True, slots=True)
class ValuationSnapshot:
    """估值、历史分位数与利差快照。"""

    pe_ttm: float | None = None
    pe_percentile_3y: float | None = None
    pe_percentile_5y: float | None = None
    pe_percentile_10y: float | None = None
    pb: float | None = None
    pb_percentile_5y: float | None = None
    ps_ttm: float | None = None
    dv_ttm: float | None = None
    treasury_10y_yield: float | None = None
    dividend_spread_10y: float | None = None
    total_mv_billion: float | None = None
    circ_mv_billion: float | None = None
    turnover_rate: float | None = None
    value_trap_warning: bool = False


@dataclass(frozen=True, slots=True)
class FinancialsSnapshot:
    """财务盈利质量、成长性与业绩预告前瞻快照。"""

    report_date: str | None = None
    roe: float | None = None
    netprofit_yoy: float | None = None
    revenue_yoy: float | None = None
    gross_margin: float | None = None
    debt_to_assets: float | None = None
    growth_deceleration: bool = False
    latest_forecast: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CapitalFlowSnapshot:
    """资金流向与微观动销前瞻代理快照。"""

    main_net_inflow_20d_billion: float | None = None
    northbound_hold_ratio: float | None = None


@dataclass(frozen=True, slots=True)
class ScreenSnapshot:
    """排雷规则体检状态。"""

    status: str = "passed"  # passed / warned / excluded / unscreened
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MarketContextSnapshot:
    """宏观与市场温度上下文快照。"""

    as_of_date: str = ""
    temperature_score: float | None = None
    temperature_band: str | None = None
    industry_name: str | None = None
    industry_rank: str | None = None


@dataclass(frozen=True, slots=True)
class StockDiagnosticsResult:
    """个股全景量化诊断聚合结果。"""

    symbol: str
    name: str
    as_of_date: str
    industry: str
    area: str
    market: str
    technicals: TechnicalsSnapshot
    valuation: ValuationSnapshot
    financials: FinancialsSnapshot
    capital_flow: CapitalFlowSnapshot
    screen: ScreenSnapshot
    market_context: MarketContextSnapshot

    def to_dict(self) -> dict[str, Any]:
        """序列化为紧凑字典。"""
        return asdict(self)

    def to_markdown(self) -> str:
        """渲染为人类友好的结构化 Markdown 报告。"""
        tech = self.technicals
        val = self.valuation
        fin = self.financials
        flow = self.capital_flow
        ctx = self.market_context

        pe_str = f"{val.pe_ttm:.2f}" if val.pe_ttm is not None else "--"
        pe_5y_str = f"{val.pe_percentile_5y:.1f}%" if val.pe_percentile_5y is not None else "--"
        pb_str = f"{val.pb:.2f}" if val.pb is not None else "--"
        dv_str = f"{val.dv_ttm:.2f}%" if val.dv_ttm is not None else "--"

        spread_str = (
            f"{val.dividend_spread_10y:+.2f}% (10Y国债 {val.treasury_10y_yield:.2f}%)"
            if val.dividend_spread_10y is not None and val.treasury_10y_yield is not None
            else "--"
        )

        roe_str = f"{fin.roe:.2f}%" if fin.roe is not None else "--"
        np_yoy_str = f"{fin.netprofit_yoy:.2f}%" if fin.netprofit_yoy is not None else "--"
        rev_yoy_str = f"{fin.revenue_yoy:.2f}%" if fin.revenue_yoy is not None else "--"
        margin_str = f"{fin.gross_margin:.2f}%" if fin.gross_margin is not None else "--"
        debt_str = f"{fin.debt_to_assets:.2f}%" if fin.debt_to_assets is not None else "--"

        ma20_str = f"{tech.ma20:.2f}" if tech.ma20 is not None else "--"
        ma60_str = f"{tech.ma60:.2f}" if tech.ma60 is not None else "--"
        rsi_str = f"{tech.rsi14:.1f}" if tech.rsi14 is not None else "--"
        pct_str = f"{tech.pct_chg:+.2f}%" if tech.pct_chg is not None else "--"

        total_mv_str = (
            f"{val.total_mv_billion:.1f} 亿" if val.total_mv_billion is not None else "--"
        )
        circ_mv_str = f"{val.circ_mv_billion:.1f} 亿" if val.circ_mv_billion is not None else "--"
        temp_score_str = (
            f"{ctx.temperature_score:.1f}" if ctx.temperature_score is not None else "--"
        )

        flow_main_str = (
            f"{flow.main_net_inflow_20d_billion:+.2f} 亿"
            if flow.main_net_inflow_20d_billion is not None
            else "--"
        )
        flow_hk_str = (
            f"{flow.northbound_hold_ratio:.2f}%" if flow.northbound_hold_ratio is not None else "--"
        )

        screen_badge = {
            "passed": "PASSED (正常通过)",
            "warned": "WARNED (存在警示)",
            "excluded": "EXCLUDED (触发排除)",
        }.get(self.screen.status, self.screen.status)

        trap_warning_str = (
            " ⚠️ **[价值陷阱预警]** 净利润增速转负/失速，静态低PE可能被动抬升，切勿单凭低分位抄底！"
            if val.value_trap_warning
            else ""
        )

        lines = [
            f"# 个股量化全景体检报告: {self.name} ({self.symbol})",
            "",
            f"- **基准日期**: {self.as_of_date}",
            f"- **所属行业/地区**: {self.industry} / {self.area} ({self.market})",
            f"- **排雷体检状态**: {screen_badge}",
        ]
        if trap_warning_str:
            lines.append(f"- **风控安全提示**:{trap_warning_str}")
        if self.screen.reasons:
            lines.append(f"  - 风险警示项: {', '.join(self.screen.reasons)}")

        lines.extend(
            [
                "",
                "## 1. 行情与技术面 (Technicals)",
                f"- **最新收盘价**: {tech.close:.2f} (日涨跌幅: {pct_str})",
                f"- **均线系统**: MA20 = {ma20_str} | MA60 = {ma60_str}",
                f"- **强弱动量**: RSI(14) = {rsi_str} | 状态: {tech.trend_description}",
                f"- **资金微观代理**: 近20日主力大单累计 = {flow_main_str} | 北向持股占比 = {flow_hk_str}",
                "",
                "## 2. 估值与利差安全垫 (Valuation)",
                f"- **PE (TTM)**: {pe_str} (近5年历史分位: {pe_5y_str})",
                f"- **PB**: {pb_str} | **股息率 (TTM)**: {dv_str}",
                f"- **股息利差安全垫**: {spread_str}",
                f"- **总市值 / 流通市值**: {total_mv_str} / {circ_mv_str}",
                "",
                "## 3. 财务质量与前瞻预告 (Financials)",
                f"- **最新正式财报期**: {fin.report_date or '--'}",
                f"- **净资产收益率 (ROE)**: {roe_str}",
                f"- **营收同比 / 净利同比**: {rev_yoy_str} / {np_yoy_str}",
                f"- **毛利率 / 资产负债率**: {margin_str} / {debt_str}",
            ]
        )

        if fin.latest_forecast:
            fc = fin.latest_forecast
            fc_type = fc.get("type", "业绩预告")
            fc_p_min = fc.get("p_change_min")
            fc_p_max = fc.get("p_change_max")
            p_range_str = (
                f"{fc_p_min:+.1f}% ~ {fc_p_max:+.1f}%"
                if fc_p_min is not None and fc_p_max is not None
                else "未披露具体区间"
            )
            lines.append(
                f"- **前瞻业绩预告**: 【{fc_type}】 (公告日: {fc.get('ann_date', '--')}, 净利变动: {p_range_str})"
            )

        lines.extend(
            [
                "",
                "## 4. 市场与行业宏观背景 (Market Context)",
                f"- **全市场六维温度**: {temp_score_str} 分 ({ctx.temperature_band or '--'})",
                f"- **行业轮动位置**: {ctx.industry_name or self.industry} ({ctx.industry_rank or '无排序数据'})",
                "",
            ]
        )
        return "\n".join(lines)
