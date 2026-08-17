"""行业结构研判辅助函数与分档逻辑。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import polars as pl


def get_fundamental_status_label(status: str) -> str:
    """基本面状态标签映射。"""
    labels = {
        "fresh_blended": "财报未滞后，且已有预告/快报/研报辅助",
        "stale_blended": "财报已滞后，但已有预告/快报/研报辅助",
        "official_only": "仅使用未滞后的正式财报",
        "official_stale": "仅有已滞后的正式财报，缺少快速确认",
        "provisional_fast_only": "仅有预告/快报/研报快速确认",
        "insufficient": "基本面数据不足",
    }
    return labels.get(status, status)


def get_fundamental_status_interpretation(value: object) -> str:
    """基本面状态分布语义解读。"""
    if not isinstance(value, dict) or not value:
        return ""
    stale_blended = int(value.get("stale_blended", 0) or 0)
    official_stale = int(value.get("official_stale", 0) or 0)
    provisional_fast_only = int(value.get("provisional_fast_only", 0) or 0)
    insufficient = int(value.get("insufficient", 0) or 0)
    if stale_blended or official_stale:
        return (
            "正式行业财报更新偏慢，当前基本面分主要是中期底座；"
            "有快速确认的行业会提高预告、快报和研报上修权重，"
            "没有快速确认的行业只能保守使用旧财报。"
        )
    if provisional_fast_only:
        return "部分行业缺少正式财报，只能临时参考预告、快报和研报变化。"
    if insufficient:
        return "部分行业基本面样本不足，相关分数只按可用子项重归一。"
    return "正式财报和快速确认数据匹配正常。"


def evaluate_breadth_comment(pos20: int, pos60: int, total: int) -> str:
    """行业上涨家数扩散状态评语。"""
    if total <= 0:
        return "扩散样本不足。"
    share20 = pos20 / total
    share60 = pos60 / total
    if share20 >= 0.6 and share60 < 0.35:
        return "短线扩散较强，但60日中期确认不足。"
    if share20 < 0.35 and share60 < 0.35:
        return "20日和60日扩散都不足，行业机会更偏局部强势而非全面修复。"
    if share20 >= 0.6 and share60 >= 0.5:
        return "20日和60日扩散同步改善，结构健康度更高。"
    return "扩散信号分化，需要结合主线拥挤度和60日趋势确认。"


def get_structure_health_level(scores: dict[str, Any]) -> str:
    """获取结构健康度等级。"""
    health = scores.get("structure_health", {})
    if not isinstance(health, dict) or not health:
        return "不可判定"
    return str(health.get("level") or "不可判定")


def has_weak_fundamental(row: dict[str, Any]) -> bool:
    """判断基本面是否偏弱或滞后。"""
    score = _as_float(row.get("fundamental_score"))
    return (score is not None and score < 40) or row.get("fundamental_status") in {
        "official_stale",
        "insufficient",
    }


def is_fund_flow_confirmed(row: dict[str, Any]) -> bool:
    """判断是否有资金流入确认。"""
    fund_flow = _as_float(row.get("fund_flow_score"))
    money_inflow = _as_float(row.get("money_net_inflow_share_20d"))
    return (
        fund_flow is not None and money_inflow is not None and fund_flow >= 70 and money_inflow > 0
    )


def has_fund_flow_pressure(row: dict[str, Any]) -> bool:
    """判断是否有明显资金流出压力。"""
    fund_flow = _as_float(row.get("fund_flow_score"))
    money_inflow = _as_float(row.get("money_net_inflow_share_20d"))
    return (
        fund_flow is not None and money_inflow is not None and fund_flow <= 30 and money_inflow < 0
    )


def is_high_dividend(row: dict[str, Any]) -> bool:
    """判断是否为高股息行业。"""
    dividend_yield = _as_float(row.get("dividend_yield"))
    if dividend_yield is None:
        return False
    threshold = 0.03 if abs(dividend_yield) <= 1 else 3
    return dividend_yield >= threshold


def _industry_name(row: dict[str, Any]) -> str:
    return str(row.get("industry_name") or row.get("industry_code") or "")


def _panel_rows(panel: pl.DataFrame) -> list[dict[str, Any]]:
    return [] if panel.is_empty() else panel.to_dicts()


def _top_rows(
    rows: list[dict[str, Any]], key: str, *, limit: int, descending: bool = True
) -> list[dict[str, Any]]:
    valid = [row for row in rows if _as_float(row.get(key)) is not None]
    return sorted(
        valid,
        key=lambda row: _as_float(row.get(key)) or 0.0,
        reverse=descending,
    )[:limit]


def _industry_list(
    rows: list[dict[str, Any]],
    metrics: tuple[tuple[str, str, str], ...],
    *,
    limit: int = 6,
) -> str:
    if not rows:
        return "无"
    parts = []
    for row in rows[:limit]:
        metric_parts = []
        for label, key, suffix in metrics:
            value = _metric_value_text(row, key, suffix)
            if value:
                metric_parts.append(f"{label}{value}{suffix}")
        metrics_text = f"({', '.join(metric_parts)})" if metric_parts else ""
        parts.append(f"{_industry_name(row)}{metrics_text}")
    return "、".join(parts)


def _metric_value_text(row: dict[str, Any], key: str, suffix: str) -> str:
    value = _as_float(row.get(key))
    if value is None:
        return _value_text(row.get(key))
    if key == "dividend_yield" and suffix == "%" and abs(value) <= 1:
        value *= 100
    return f"{value:.2f}"


def _value_text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, int | float | str):
        return str(value)
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _as_float(value: object) -> float | None:
    if value is None or not isinstance(value, int | float | str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
