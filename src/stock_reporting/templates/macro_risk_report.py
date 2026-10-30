"""宏观风控日报渲染：普通投资者版（默认）与专业投研版。"""

from __future__ import annotations

from datetime import date
from math import isnan
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

if TYPE_CHECKING:
    from stock_analytics.pipelines.macro_risk.fred import DFFSnapshot

from stock_core.constants import (
    MACRO_RISK_DEGRADED_MONITORS,
    MACRO_RISK_DEGRADED_ZERO_RUN_DAYS,
)
from stock_reporting.engine.renderer import ReportRenderer
from stock_reporting.interpretation.macro_risk.config import index_threshold, load_reporting_config
from stock_reporting.interpretation.macro_risk.global_macro_hint import (
    build_global_macro_hint,
)
from stock_reporting.interpretation.macro_risk.logic import evaluate_macro_risk
from stock_reporting.interpretation.macro_risk.meso_penetration import (
    build_meso_penetration_section,
)
from stock_reporting.interpretation.macro_risk.rate_cycle_hint import rate_cycle_hint
from stock_reporting.interpretation.macro_risk.style_rotation import build_style_rotation_section

# 普通投资者版：关键指标的一句话「人话」解释
_PLAIN_DESC = {
    "两融杠杆": "借钱买股票的热度，越高越容易踩踏",
    "换手拥挤": "交易拥挤程度，越高短线越危险",
    "资金与筹码": "资金流向和筹码分歧的综合状态",
    "期权情绪": "市场恐慌情绪，越高越接近底部",
    "市场广度": "涨跌数量和新高扩散情况",
    "大盘估值": "股票整体贵不贵",
    "产业资本": "增持、减持和解禁压力的综合状态",
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


def _load_ffr_chg_6m(target_date: date | None) -> float | None:
    """加载 DFF 6 个月累计变化（pp，asof 到目标日，无前视）。

    保留该函数作为报告模板入口；底层统一由 DFF 序列加载器处理独立表与聚合表。
    """
    if target_date is None:
        return None
    return _load_fred_rate_snapshot(target_date).change_6m


def _load_fred_rate_snapshot(target_date: date | None) -> DFFSnapshot:
    """加载报告目标日可见的 FRED DFF 快照。"""
    from stock_analytics.pipelines.macro_risk.fred import load_dff_snapshot

    return load_dff_snapshot(target_date)


def _signal_badge(level: str) -> str:
    """红绿灯信号徽标。"""
    return {
        "danger": "🔴 红灯",
        "opportunity": "🟢 绿灯",
        "warning": "🟡 黄灯",
        "safe": "⚪ 平稳",
    }.get(level, "⚪ 平稳")


def _trailing_zero_run(df: pl.DataFrame, column: str) -> int:
    """统计目标列截至末行的连续 0 值天数（空值即中断）。"""
    if column not in df.columns:
        return 0
    run = 0
    for value in reversed(df[column].to_list()):
        if value is None:
            break
        try:
            if float(value) != 0.0:
                break
        except (TypeError, ValueError):
            break
        run += 1
    return run


def _detect_degraded_dimensions(
    df: pl.DataFrame,
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """检出「非双轨成分但研报必须披露」的退化维度。

    这类维度不进 overheat/panic，也不会让 ``data_completeness`` 失败，因此必须在
    研报层单独披露。退化有两种形态：当期值缺失（null，上游字段未落地）与连续恒为 0
    （被打成 0.0 的假读数），两者都需显式标注，避免被当成真实读数引用。
    """
    names = {
        item.get("column"): item.get("name", item.get("column"))
        for item in (cfg.get("auxiliary_dimensions") or [])
        if isinstance(item, dict)
    }
    degraded: list[dict[str, Any]] = []
    if df.is_empty():
        return degraded
    latest = df.tail(1).to_dicts()[0]
    for dim_field, column in MACRO_RISK_DEGRADED_MONITORS.items():
        if column not in df.columns:
            continue
        value = latest.get(column)
        zero_run = _trailing_zero_run(df, column)
        is_missing = value is None or (isinstance(value, float) and isnan(value))
        if not is_missing and zero_run < MACRO_RISK_DEGRADED_ZERO_RUN_DAYS:
            continue
        reason = (
            f"`{column}` 当前为 null（上游字段未落地，属数据缺口而非「零发行」），本期不可用"
            if is_missing
            else (
                f"`{column}` 连续 {zero_run} 个交易日恒为 0，"
                "属上游缺数被打成 0.0（非真实读数），本期不可用"
            )
        )
        degraded.append(
            {
                "field": dim_field,
                "column": column,
                "name": names.get(column, dim_field),
                "zero_run": zero_run,
                "reason": reason,
            }
        )
    return degraded


def _build_auxiliary_rows(
    row: dict[str, Any],
    cfg: dict[str, Any],
    degraded: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """附加维度（不进双轨指数）展示行，退化维度标注数据缺口。"""
    degraded_cols = {d["column"] for d in degraded}
    rows: list[dict[str, Any]] = []
    for item in cfg.get("auxiliary_dimensions") or []:
        if not isinstance(item, dict):
            continue
        column = item.get("column")
        if not column:
            continue
        value = row.get(column)
        if column in degraded_cols:
            state = "数据缺口"
        elif isinstance(value, int | float):
            state = "正常"
        else:
            state = "数据缺失"
        rows.append(
            {
                "name": item.get("name", column),
                "value": f"{float(value):.1f}" if isinstance(value, int | float) else "N/A",
                "state": state,
                "note": item.get("note", ""),
            }
        )
    return rows


def _build_trend_note(ma20_status: dict[str, float | bool] | None) -> str:
    """生命线跌破提示：宏观「平稳」不等于趋势安全。"""
    if not ma20_status or not ma20_status.get("broken"):
        return ""
    close = float(ma20_status["close"])
    ma20 = float(ma20_status["ma20"])
    gap = (close / ma20 - 1.0) * 100.0 if ma20 else 0.0
    return (
        f"\n\n**趋势纪律**：收盘 `{close:.0f}` 已跌破生命线 MA20 `{ma20:.0f}`（{gap:+.1f}%）。"
        "双轨读数平稳只说明系统性估值/杠杆未到极值，不代表趋势安全："
        "进攻端仍按 MA20 规则退出，防守端可持有。"
    )


def _build_action_guide(
    level: str,
    ma20_status: dict[str, float | bool] | None,
    panic_value: float,
    scenario: str = "safe",
    panic_caveat_threshold: float = 75.0,
) -> str:
    """面向普通投资者的三选一操作指引（持有/空仓/风险）。

    ``panic_caveat_threshold``：机会分支「假冰点」提示阈值，默认 75 对齐策略
    ``panic_threshold``，实际值由调用方从研报配置（``indices.panic.action_guide_caveat``）传入。
    """
    ma20 = float(ma20_status["ma20"]) if ma20_status else None
    broken = bool(ma20_status and ma20_status["broken"])

    if level == "danger":
        if broken:
            hold = f"生命线已跌破（{ma20:.0f}），**坚决卖出进攻端（创业板 ETF）**，退守红利/国债。"
        elif ma20 is None:
            hold = "不追高，收紧止盈；以生命线（20日均线）跌破为右侧退出开关，跌破坚决卖出进攻端。"
        else:
            hold = f"不追高，收紧止盈；生命线跌破（< {ma20:.0f}）再卖出进攻端。"
        return (
            f"1. **已持有**：{hold}\n"
            "2. **空仓**：现在不是买入时机，等回调。\n"
            "3. **风险**：市场过热，未来一季度下跌概率偏高，勿加杠杆。"
        )
    if scenario == "panic_false_gold_pit":
        return (
            "1. **已持有**：不加仓，按生命线和既定仓位纪律防守。\n"
            "2. **空仓**：不要左侧抄底，等待重新站上生命线或产业压力缓和。\n"
            "3. **风险**：当前是假黄金坑分支，单日反弹可能只是流动性中继。"
        )
    if level == "opportunity":
        if scenario == "panic_buyback_only":
            return (
                "1. **已持有**：无需恐慌割肉，但不把仓位一次性打满。\n"
                "2. **空仓**：仅小步分批观察宽基/红利，等待内部人减持、解禁压力和聪明钱同步改善。\n"
                "3. **风险**：当前只有回购单项支撑，产业资本综合压力仍高，不能视为产业底确认。"
            )
        if scenario == "panic_partial_support":
            return (
                "1. **已持有**：无需恐慌割肉，但不把仓位一次性打满。\n"
                "2. **空仓**：仅小步分批观察宽基/红利，等待回购或聪明钱继续确认。\n"
                "3. **风险**：产业资本只是低压力，不能等同于强回购托底。"
            )
        pos_hint = (
            "（注意：若市场位置偏高可能是假冰点，抄底分批勿满仓）"
            if panic_value > panic_caveat_threshold
            else ""
        )
        return (
            f"1. **已持有**：无需恐慌割肉。\n"
            f"2. **空仓**：恐慌区可左侧分批低吸宽基/红利{pos_hint}。\n"
            "3. **风险**：反弹前可能还有余震，分批优于一次性满仓。"
        )
    if level == "warning":
        if broken:
            return (
                f"1. **已持有**：不加仓；趋势已破生命线（{ma20:.0f}），进攻端按 MA20 规则减仓。\n"
                "2. **空仓**：等收盘重新站上生命线且信号明确再动。\n"
                "3. **风险**：情绪分歧加大叠加趋势破位，注意控制仓位。"
            )
        return (
            "1. **已持有**：不加仓，观望为主。\n"
            "2. **空仓**：等待信号明确再动。\n"
            "3. **风险**：情绪分歧加大，注意控制仓位。"
        )
    if broken:
        # 宏观双轨「平稳」不等于趋势安全：趋势破位时不得输出「可正常配置」
        return (
            f"1. **已持有**：防守端（红利/国债）可持有；进攻端按生命线纪律退出（收盘已低于 MA20 {ma20:.0f}）。\n"
            f"2. **空仓**：不追高，等收盘重新站上生命线（{ma20:.0f}）再恢复常规配置。\n"
            "3. **风险**：宏观读数不极端 ≠ 趋势安全，破位期回撤由杠杆与拥挤驱动，未必触发恐慌指数。"
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
    # 利率周期风险提示（加息/降息档位 + 实证文案；原始 pp 缺失时降级用分位）
    effective_target_date = target_date or row_dict["trade_date"]
    rate_snapshot = _load_fred_rate_snapshot(effective_target_date)
    eval_result["rate_cycle_hint"] = rate_cycle_hint(
        rate_snapshot.change_6m,
        row_dict.get("ffr_chg_6m_score"),
        observation_date=rate_snapshot.observation_date,
    )
    eval_result["global_macro_hint"] = build_global_macro_hint(
        effective_target_date,
        row_dict,
    )

    renderer = ReportRenderer()
    template_name = "macro_risk_simple.md.j2" if template == "simple" else "macro_risk.md.j2"
    template_path = Path(__file__).parent / template_name
    if not template_path.exists():
        return f"模板文件未找到: {template_path}"

    template_content = template_path.read_text(encoding="utf-8")
    trade_date_str = str(row_dict["trade_date"])[:10]

    # 操作指引「假冰点」提示阈值从研报配置读取（对齐策略 panic_threshold=75，见配置注释）
    report_cfg = load_reporting_config()
    panic_caveat = index_threshold(report_cfg, "panic", "action_guide_caveat", 75.0)

    # 退化维度与附加维度：非双轨成分，缺失或恒 0 时不阻断，但必须披露
    degraded = _detect_degraded_dimensions(df, report_cfg)

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
            eval_result["level"],
            ma20_status,
            eval_result["panic_value"],
            eval_result.get("scenario", "safe"),
            panic_caveat_threshold=panic_caveat,
        ),
        "trend_note": _build_trend_note(ma20_status),
        "degraded_dimensions": degraded,
        "auxiliary_rows": _build_auxiliary_rows(row_dict, report_cfg, degraded),
    }

    rendered = renderer.render_string(template_content, context)
    effective_date = target_date or row_dict["trade_date"]

    # 宏观极值水温中观下穿（狂热超标排雷 / 恐慌超标真假黄金坑验真；常态平稳期自动省略）
    # 阈值统一取自研报配置 indices.{overheat,panic}.penetration_threshold，避免与
    # 双轨极值 threshold_critical 出现两套不可追溯的硬编码警戒线。
    meso_section = build_meso_penetration_section(
        effective_date,
        eval_result.get("overheat_value"),
        eval_result.get("panic_value"),
        overheat_threshold=index_threshold(report_cfg, "overheat", "penetration_threshold", 62.0),
        panic_threshold=index_threshold(report_cfg, "panic", "penetration_threshold", 70.0),
    )
    if meso_section:
        rendered = f"{rendered}\n\n{meso_section}"

    # 风格轮动观察附录（独立参考，非 v5 信号；数据缺失时自动省略）
    style_section = build_style_rotation_section(effective_date)
    if style_section:
        rendered = f"{rendered}\n\n{style_section}"
    return rendered


__all__ = ["render_macro_risk_report"]
