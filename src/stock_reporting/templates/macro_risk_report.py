"""宏观风控日报渲染：普通投资者版（默认）与专业投研版。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock_reporting.engine.renderer import ReportRenderer
from stock_reporting.interpretation.macro_risk.logic import evaluate_macro_risk

# 普通投资者版：关键指标的一句话「人话」解释
_PLAIN_DESC = {
    "两融杠杆": "借钱买股票的热度，越高越容易踩踏",
    "换手拥挤": "交易拥挤程度，越高短线越危险",
    "主力资金": "大资金在买还是在卖",
    "期权情绪": "市场恐慌情绪，越高越接近底部",
    "市场广度": "涨跌股票的数量对比",
    "大盘估值": "股票整体贵不贵",
    "产业资本": "上市公司自己买不买自家股票",
    "跨资产宏观": "股债商综合信号",
}

# 普通投资者版：最需要看的 3 个关键指标
_KEY_CODES = {"dim_leverage", "dim_crowding", "dim_fear"}


def _load_benchmark_closes(target_date: date | None) -> list[float]:
    """加载基准（中证全指）截至目标日的收盘序列。"""
    if target_date is None:
        return []
    try:
        from stock_data.catalog import DataCatalog

        cat = DataCatalog(data_source="lixinger")
        bars = cat.load_bars(
            symbol="000985.CSI",
            dataset="index_daily_bar",
            columns=["trade_date", "close"],
        )
        hist = bars.filter(pl.col("trade_date") <= target_date).sort("trade_date").select("close")
        return [float(v) for v in hist["close"].to_list()]
    except Exception:
        return []


def _compute_dd_from_high(closes: list[float]) -> float | None:
    """距前 120 交易日高点回撤（不含当日高点），用于识别「假冰点」。"""
    if len(closes) >= 121:
        hi120 = max(closes[-121:-1])
        if hi120 > 0:
            return float(closes[-1]) / float(hi120) - 1.0
    return None


def _compute_ma20_status(closes: list[float]) -> dict[str, float | bool] | None:
    """MA20 生命线状态：当前收盘 vs 20 日均线是否跌破。"""
    if len(closes) < 20:
        return None
    ma20 = sum(closes[-20:]) / 20.0
    close = closes[-1]
    return {"close": close, "ma20": ma20, "broken": close < ma20}


def _compute_market_position(closes: list[float]) -> dict[str, float] | None:
    """市场位置：当前点位 + 近 20/60 日涨跌（普通投资者版锚点）。"""
    if not closes:
        return None
    pos: dict[str, float] = {"close": closes[-1]}
    for label, days in (("ret20", 20), ("ret60", 60)):
        if len(closes) > days:
            base = closes[-days - 1]
            if base > 0:
                pos[label] = closes[-1] / base - 1.0
    return pos


def _signal_badge(level: str) -> str:
    """红绿灯信号徽标。"""
    return {
        "danger": "🔴 红灯",
        "opportunity": "🟢 绿灯",
        "warning": "🟡 黄灯",
        "safe": "⚪ 平稳",
    }.get(level, "⚪ 平稳")


def _build_action_guide(
    level: str,
    ma20_status: dict[str, float | bool] | None,
    panic_value: float,
) -> str:
    """面向普通投资者的三选一操作指引（持有/空仓/风险）。"""
    broken = bool(ma20_status and ma20_status["broken"])
    ma20 = float(ma20_status["ma20"]) if ma20_status else 0.0

    if level == "danger":
        if broken:
            hold = f"生命线已跌破（{ma20:.0f}），**坚决卖出进攻端（创业板 ETF）**，退守红利/国债。"
        else:
            hold = f"不追高，收紧止盈；生命线跌破（< {ma20:.0f}）再卖出进攻端。"
        return (
            f"1. **已持有**：{hold}\n"
            "2. **空仓**：现在不是买入时机，等回调。\n"
            "3. **风险**：市场过热，未来一季度下跌概率偏高，勿加杠杆。"
        )
    if level == "opportunity":
        pos_hint = (
            "（注意：若市场位置偏高可能是假冰点，抄底分批勿满仓）" if panic_value > 75 else ""
        )
        return (
            f"1. **已持有**：无需恐慌割肉。\n"
            f"2. **空仓**：恐慌区可左侧分批低吸宽基/红利{pos_hint}。\n"
            "3. **风险**：反弹前可能还有余震，分批优于一次性满仓。"
        )
    if level == "warning":
        return (
            "1. **已持有**：不加仓，观望为主。\n"
            "2. **空仓**：等待信号明确再动。\n"
            "3. **风险**：情绪分歧加大，注意控制仓位。"
        )
    return (
        "1. **已持有**：按自己的节奏持有。\n"
        "2. **空仓**：无明显系统性风险，可正常配置。\n"
        "3. **风险**：无重大宏观风险提示。"
    )


def render_macro_risk_report(
    df: pl.DataFrame,
    target_date: date | None = None,
    template: str = "simple",
) -> str:
    """生成宏观风控日报 Markdown。

    Args:
        df: 宏观因子面板。
        target_date: 目标交易日，None 时取最新。
        template: 模板版本——"simple" 普通投资者版（默认）/ "pro" 专业投研版。
    """
    row_df = df.filter(pl.col("trade_date") == target_date) if target_date else df.tail(1)

    if row_df.is_empty():
        return f"未找到日期 {target_date} 的风险数据。"

    row_dict = row_df.to_dicts()[0]
    closes = _load_benchmark_closes(target_date)
    eval_result = evaluate_macro_risk(row_dict, dd_from_high=_compute_dd_from_high(closes))
    ma20_status = _compute_ma20_status(closes)
    if ma20_status is not None:
        eval_result["ma20_status"] = ma20_status
    eval_result["market_position"] = _compute_market_position(closes)

    renderer = ReportRenderer()
    template_name = "macro_risk_simple.md.j2" if template == "simple" else "macro_risk.md.j2"
    template_path = Path(__file__).parent / template_name
    if not template_path.exists():
        return f"模板文件未找到: {template_path}"

    template_content = template_path.read_text(encoding="utf-8")
    trade_date_str = str(row_dict["trade_date"])[:10]

    key_metrics = []
    for tier in eval_result.get("risk_tiers", []):
        for item in tier.get("metrics", []):
            if item.get("code") in _KEY_CODES:
                key_metrics.append(
                    {**item, "plain": _PLAIN_DESC.get(item.get("name", ""), item.get("desc", ""))}
                )

    context = {
        "trade_date": trade_date_str,
        "eval_result": eval_result,
        "signal_badge": _signal_badge(eval_result["level"]),
        "key_metrics": key_metrics,
        "action_guide": _build_action_guide(
            eval_result["level"], ma20_status, eval_result["panic_value"]
        ),
    }

    return renderer.render_string(template_content, context)


__all__ = ["render_macro_risk_report"]
