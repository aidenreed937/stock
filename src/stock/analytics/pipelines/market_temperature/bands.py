"""市场温度计分档与评语基础规则。"""

from __future__ import annotations

from typing import Any

_DIMENSION_LABELS: dict[str, str] = {
    "valuation": "估值",
    "fund_flow": "资金",
    "sentiment": "情绪",
    "technical": "技术",
    "fundamental": "基本面",
    "macro_liquidity": "宏观流动性",
}

_DIMENSION_FOCUS: dict[str, tuple[str, str]] = {
    "valuation": (
        "估值约束",
        "核心看安全边际；高估值压缩胜率，低估值提供赔率，但低估不代表马上上涨。",
    ),
    "fund_flow": (
        "资金推力",
        "核心看两融、北向与主力成交意愿；资金是行情启动与延续的直接燃料。",
    ),
    "sentiment": (
        "情绪温度",
        "核心看市场交易热度与极值；过热防拥挤踩踏，过冷等恐慌出清与拐点。",
    ),
    "technical": (
        "趋势广度",
        "核心看上涨家数与均线多头扩散；技术面代表中短期价格趋势的共识强弱。",
    ),
    "fundamental": (
        "盈利底座",
        "核心看行业营收与利润改善趋势；基本面决定行情的持续性与高度上限。",
    ),
    "macro_liquidity": (
        "宏观环境",
        "核心看无风险利率与货币流动性水位；充裕流动性提升全市场整体估值中枢。",
    ),
}

_METRIC_LABELS: dict[str, str] = {
    "pe_percentile_5y": "PE 5年分位",
    "pb_percentile_5y": "PB 5年分位",
    "dividend_yield": "股息率",
    "equity_risk_premium": "股权风险溢价 (ERP)",
    "margin_balance_growth_20d": "两融余额20日变动",
    "main_money_net_inflow_share": "主力净流入占比",
    "hsgt_net_inflow_20d": "北向资金20日累计净流入",
    "turnover_rate_20d": "20日日均换手率",
    "up_ratio_20d": "20日日均上涨家数占比",
    "limit_up_down_ratio": "涨跌停家数比",
    "investor_account_temperature": "新增投资者入场温度",
    "above_ma20_ratio": "站上20日均线个股占比",
    "above_ma60_ratio": "站上60日均线个股占比",
    "market_return_20d": "全市场20日中位涨跌幅",
    "industry_positive_return_ratio_20d": "20日正收益行业占比",
    "profit_growth_median": "行业净利润增速中位数",
    "revenue_growth_median": "行业营业收入增速中位数",
    "shibor_3m": "Shibor 3M 利率",
    "gov_bond_yield_10y": "10年期国债收益率",
    "macro_external_pressure_temperature": "总体外部压力",
    "macro_safe_haven_pressure_temperature": "避险压力",
    "macro_inflation_pressure_temperature": "通胀压力",
    "macro_demand_pressure_temperature": "需求压力",
    "macro_fred_t10y2y_temperature": "美国期限利差温度",
    "macro_cnh_20d_change_temperature": "人民币汇率20日变化温度",
    "macro_sp500_20d_return_temperature": "标普500 20日收益温度",
    "macro_nasdaq_20d_return_temperature": "纳斯达克 20日收益温度",
    "macro_bond_yield_10y_temperature": "10年期国债收益率温度",
    "macro_shibor_on_temperature": "隔夜Shibor温度",
    "macro_real_rate_temperature": "实际利率温度",
}

_DIMENSION_TIMELINESS: dict[str, tuple[str, str, str, str]] = {
    "technical": (
        "短线信号",
        "最快",
        "日频价格与均线宽度",
        "回答最近20个交易日趋势广度和赚钱效应",
    ),
    "sentiment": (
        "短线信号",
        "快",
        "日频成交、换手与情绪指标",
        "回答当日与近期的交易热度和拥挤状态",
    ),
    "fund_flow": (
        "确认信号",
        "较快",
        "日频/滞后两融、北向与主力资金",
        "回答价格修复是否有增量资金持续确认",
    ),
    "valuation": (
        "中期约束",
        "中慢",
        "日频价格与估值分位数",
        "回答中期安全边际与赔率，不代表单日方向",
    ),
    "fundamental": (
        "盈利底座",
        "偏慢",
        "季频行业财报底座与研报上修",
        "财报是低频底座，预告和研报才反映近20日预期变化",
    ),
    "macro_liquidity": (
        "宏观底座",
        "慢",
        "日频/月频利率与货币流动性",
        "回答大类资产环境与宏观分母，作背景不作短线买卖点",
    ),
}


def get_temperature_band(value: object) -> str:
    """根据温度数值获取状态分档。"""
    temperature = _as_float(value)
    if temperature is None:
        return "不可判定"
    if temperature < 20:
        return "低温机会区"
    if temperature < 40:
        return "偏冷修复观察区"
    if temperature < 60:
        return "中性轮动区"
    if temperature < 80:
        return "偏热修复区"
    return "高温拥挤区"


def get_pressure_band(value: object) -> str:
    """根据外部宏观压力数值获取状态分档。"""
    pressure = _as_float(value)
    if pressure is None:
        return "不可判定"
    if pressure >= 80:
        return "高压力"
    if pressure >= 60:
        return "中等偏高"
    if pressure >= 40:
        return "中性"
    return "压力不明显"


def get_pressure_comment(metric_id: str, value: object) -> str:
    """获取外部宏观压力项的针对性说明。"""
    pressure = _as_float(value)
    if pressure is None:
        return "样本不足，不能解读。"
    if metric_id == "macro_external_pressure_temperature":
        base = "取避险、通胀、需求三类压力的最大值，用于提示外盘风险来源。"
    elif metric_id == "macro_safe_haven_pressure_temperature":
        base = "观察黄金、VIX 和美股是否共同指向避险交易。"
    elif metric_id == "macro_inflation_pressure_temperature":
        base = "观察原油、美债收益率和美国CPI是否共同形成估值分母压力。"
    elif metric_id == "macro_demand_pressure_temperature":
        base = "观察铜、原油和美股是否共同指向全球需求走弱。"
    else:
        base = "仅作外部背景观察。"
    if pressure >= 80:
        return f"压力高，{base}"
    if pressure >= 60:
        return f"压力偏高，{base}"
    if pressure >= 40:
        return f"压力中性，{base}"
    return f"压力不明显，{base}"


def get_dimension_comment(dimension_id: str, temperature: object) -> str:
    """单维度温度研判解读。"""
    focus, base = _DIMENSION_FOCUS.get(dimension_id, ("维度状态", "按当前温度分档解读。"))
    band = get_temperature_band(temperature)
    value = _as_float(temperature)
    if value is None:
        return f"{focus}暂不可判定；{base}"
    if value >= 80:
        prefix = f"{focus}高温"
    elif value >= 60:
        prefix = f"{focus}偏热"
    elif value >= 40:
        prefix = f"{focus}中性"
    elif value >= 20:
        prefix = f"{focus}偏冷"
    else:
        prefix = f"{focus}低温"
    return f"{prefix}（{band}）；{base}"


def get_cross_period_comment(name: str, delta: float | None, fallback: str) -> str:
    """跨期变动评语。"""
    if delta is None:
        return fallback
    absolute = abs(delta)
    if name == "综合温度" and absolute < 3:
        return "总分接近，重点看内部驱动是否换挡。"
    if absolute < 5:
        return "变化不大。"
    direction = "升温" if delta > 0 else "降温"
    strength = "明显" if absolute >= 20 else ""
    return f"{strength}{direction}，{fallback}"


def get_systemic_risk_level(scores: dict[str, Any]) -> str:
    """获取系统性风险等级。"""
    risk = scores.get("systemic_risk", {})
    if not isinstance(risk, dict) or not risk:
        return "不可判定"
    return str(risk.get("level") or "不可判定")


def _temperature_text(value: object) -> str:
    numeric = _as_float(value)
    return "不可判定" if numeric is None else f"{numeric:.2f}"


def _as_float(value: object) -> float | None:
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None
