"""宏观极值水温下的申万二级行业机会与风险中观穿透模块。

当宏观双轨雷达触发狂热超标 (Overheat >= 62) 或恐慌超标 (Panic >= 70) 时，
下穿读取本地申万二级基本面黄金面板 (industry_l2_panel_daily.parquet)，
自动输出：
1. 狂热期：高危过热拥挤暴雷榜 vs 低位高低切安全承接榜
2. 恐慌期：超跌错杀真黄金坑榜 vs 产能过剩假黄金坑飞刀榜
常态平稳期不输出，保持宏观日报精炼。
"""

from __future__ import annotations

from datetime import date
from math import isnan
from pathlib import Path

import polars as pl

_L2_PANEL_PATH = Path("data/curated/mart/industry_l2_panel_daily.parquet")

# 中观下穿触发阈值：唯一信任源为 config/reporting/macro_risk_thresholds.yaml 的
# indices.{overheat,panic}.penetration_threshold；下列常量仅在调用方未传配置时兜底。
OVERHEAT_PENETRATION_THRESHOLD = 62.0  # 狂热下穿警戒线（低于双轨极值 threshold_critical 65）
PANIC_PENETRATION_THRESHOLD = 70.0  # 恐慌下穿警戒线（对齐双轨极值 70）


def _load_l2_panel_slice(target_date: date) -> pl.DataFrame | None:
    """加载目标日或最近一个可用交易日的申万二级面板切片。"""
    if not _L2_PANEL_PATH.is_file():
        return None

    try:
        # 扫描或直接读取
        df = pl.read_parquet(_L2_PANEL_PATH)
        if "trade_date" not in df.columns:
            return None

        avail_dates = df.filter(pl.col("trade_date") <= target_date)["trade_date"]
        if avail_dates.is_empty():
            return None

        eff_date = avail_dates.max()
        slice_df = df.filter(pl.col("trade_date") == eff_date)
        return slice_df if not slice_df.is_empty() else None
    except Exception:
        return None


def _format_pct(val: float | None) -> str:
    if val is None or isnan(val):
        return "-"
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.1f}%"


def _format_ratio_pct(val: float | None) -> str:
    """格式化小数比率（如 0.068 -> +6.8%）。"""
    if val is None or isnan(val):
        return "-"
    v_pct = val * 100.0
    sign = "+" if v_pct > 0 else ""
    return f"{sign}{v_pct:.1f}%"


def _format_num(val: float | None, digits: int = 1) -> str:
    if val is None or isnan(val):
        return "-"
    return f"{val:.{digits}f}"


def build_meso_penetration_section(
    target_date: date,
    overheat_val: float | None,
    panic_val: float | None,
    force_preview: bool = False,
    *,
    overheat_threshold: float | None = None,
    panic_threshold: float | None = None,
) -> str:
    """构建宏观极值水温下的二级行业机会与风险穿透卡片。

    参数:
        target_date: 目标交易日
        overheat_val: 狂热双轨指数分位
        panic_val: 恐慌双轨指数分位
        force_preview: 是否强制输出（用于测试或独立巡检预览）
        overheat_threshold: 狂热下穿阈值（来自研报配置，缺省回退 62.0）
        panic_threshold: 恐慌下穿阈值（来自研报配置，缺省回退 70.0）
    """
    ov = float(overheat_val) if overheat_val is not None else 50.0
    pv = float(panic_val) if panic_val is not None else 50.0

    ov_th = (
        float(overheat_threshold)
        if overheat_threshold is not None
        else OVERHEAT_PENETRATION_THRESHOLD
    )
    pv_th = float(panic_threshold) if panic_threshold is not None else PANIC_PENETRATION_THRESHOLD

    is_overheat = ov >= ov_th
    is_panic = pv >= pv_th

    # 若非极值且未开启强制预览，则返回空串，不干扰日常宏观精简研报
    if not is_overheat and not is_panic and not force_preview:
        return ""

    df = _load_l2_panel_slice(target_date)
    if df is None or df.is_empty():
        return ""

    actual_date = df["trade_date"][0]
    lines: list[str] = [
        "## 宏观极值下穿：申万二级行业机会与风险清单",
        f"> **下穿基准日**: `{actual_date}` | **宏观状态**: "
        f"Overheat `{_format_num(ov)}` {'[超标]' if is_overheat else ''} | "
        f"Panic `{_format_num(pv)}` {'[超标]' if is_panic else ''}",
        "",
    ]

    # 1. 狂热超标场景 (或强制预览)
    if is_overheat or (force_preview and not is_panic):
        lines.append("### 狂热极值排雷：高位抱团过热名单 (严防踩踏 / 坚决止盈)")
        lines.append(
            "> 筛选逻辑：时序拥挤度 `crowding >= 80%`（筹码极度拥挤）且 5Y估值分位 `pe5y >= 75%`（估值严重透支），增量资金枯竭，随时面临踩踏式瓦解。"
        )

        crowd_risks = (
            df.filter(
                (pl.col("crowding_score") >= 80.0) & (pl.col("pe_ttm_ew_percentile_5y") >= 75.0)
            )
            .sort(["crowding_score", "pe_ttm_ew_percentile_5y"], descending=[True, True])
            .head(6)
        )

        if not crowd_risks.is_empty():
            lines.append(
                "| 二级行业 | 拥挤度分位 | PE5Y分位 | 近20日动量 | 近60日动量 | 风险诊断 |"
            )
            lines.append("| :--- | :---: | :---: | :---: | :---: | :--- |")
            for r in crowd_risks.to_dicts():
                name = r.get("industry_name", r.get("industry_code", "-"))
                c_score = _format_num(r.get("crowding_score"))
                pe_score = _format_num(r.get("pe_ttm_ew_percentile_5y"))
                r20 = _format_pct(r.get("return_20d"))
                r60 = _format_pct(r.get("return_60d"))
                lines.append(
                    f"| **{name}** | `{c_score}%` | `{pe_score}%` | {r20} | {r60} | [高危] 极度拥挤+估值透支，严禁追高 |"
                )
        else:
            lines.append("*(当前暂无同时满足拥挤度>=80%且估值>=75%的极端暴雷行业)*")

        lines.append("")
        lines.append("### 狂热高低切机会：低位安全承接名单 (资金外溢 / 安全岛)")
        lines.append(
            "> 筛选逻辑：时序拥挤度 `crowding <= 30%`（极度冷门无人问津）且 5Y估值分位 `pe5y <= 30%`（历史底部），承接高位泡沫破裂后的避险资金。"
        )

        low_val_safeties = (
            df.filter(
                (pl.col("crowding_score") <= 30.0) & (pl.col("pe_ttm_ew_percentile_5y") <= 30.0)
            )
            .sort(["pe_ttm_ew_percentile_5y", "crowding_score"], descending=[False, False])
            .head(6)
        )

        if not low_val_safeties.is_empty():
            lines.append(
                "| 二级行业 | 拥挤度分位 | PE5Y分位 | 近20日动量 | 近60日动量 | 安全边际属性 |"
            )
            lines.append("| :--- | :---: | :---: | :---: | :---: | :--- |")
            for r in low_val_safeties.to_dicts():
                name = r.get("industry_name", r.get("industry_code", "-"))
                c_score = _format_num(r.get("crowding_score"))
                pe_score = _format_num(r.get("pe_ttm_ew_percentile_5y"))
                r20 = _format_pct(r.get("return_20d"))
                r60 = _format_pct(r.get("return_60d"))
                lines.append(
                    f"| **{name}** | `{c_score}%` | `{pe_score}%` | {r20} | {r60} | [承接] 低估值冷门安全岛，高低切承接 |"
                )
        else:
            lines.append("*(当前暂无满足低拥挤且低估值的安全岛标的)*")
        lines.append("")

    # 2. 恐慌超标场景 (或强制预览)
    if is_panic or (force_preview and is_panic):
        lines.append("### 恐慌验真：超跌错杀「真黄金坑」名单 (优先反弹核心)")
        lines.append(
            "> 筛选逻辑：近期跟随大盘泥沙俱下深跌，但财报营收/净利双正 (QLQ 量价齐升)，且无在建工程失控 (在建/固资比 < 35%)，属纯情绪错杀珍珠。"
        )

        # 筛选超跌但基本面坚挺
        real_gold = (
            df.filter(
                (pl.col("return_20d") < 0.0)
                & (pl.col("revenue_growth_ttm") > 0.0)
                & (pl.col("profit_growth_ttm") > 0.0)
                & (pl.col("cip_to_fa_ratio") < 0.35)
            )
            .sort("profit_growth_ttm", descending=True)
            .head(6)
        )

        if not real_gold.is_empty():
            lines.append(
                "| 二级行业 | 近20日跌幅 | 营收TTM YoY | 净利TTM YoY | PE5Y分位 | 错杀验真结论 |"
            )
            lines.append("| :--- | :---: | :---: | :---: | :---: | :--- |")
            for r in real_gold.to_dicts():
                name = r.get("industry_name", r.get("industry_code", "-"))
                r20 = _format_pct(r.get("return_20d"))
                rev = _format_ratio_pct(r.get("revenue_growth_ttm"))
                prof = _format_ratio_pct(r.get("profit_growth_ttm"))
                pe_score = _format_num(r.get("pe_ttm_ew_percentile_5y"))
                lines.append(
                    f"| **{name}** | {r20} | {rev} | {prof} | `{pe_score}%` | [真坑] 量价齐升无过剩，情绪错杀真坑 |"
                )
        else:
            lines.append("*(当前暂无满足量价齐升且超跌的错杀行业)*")

        lines.append("")
        lines.append("### 恐慌右侧避险：逆势走强「避险主线」名单 (抱团防空洞)")
        lines.append(
            "> 筛选逻辑：大盘暴跌时逆势走强 (`return_20d > 0`)，且财报营收/净利高增 (QLQ)，属全市场主力抱团避险的核心资产。"
        )

        safe_haven = (
            df.filter(
                (pl.col("return_20d") > 0.0)
                & (pl.col("revenue_growth_ttm") > 0.0)
                & (pl.col("profit_growth_ttm") > 0.0)
                & (pl.col("cip_to_fa_ratio") < 0.35)
            )
            .sort(["return_20d", "profit_growth_ttm"], descending=[True, True])
            .head(6)
        )

        if not safe_haven.is_empty():
            lines.append(
                "| 二级行业 | 近20日涨幅 | 营收TTM YoY | 净利TTM YoY | 拥挤度分位 | 避险主线属性 |"
            )
            lines.append("| :--- | :---: | :---: | :---: | :---: | :--- |")
            for r in safe_haven.to_dicts():
                name = r.get("industry_name", r.get("industry_code", "-"))
                r20 = _format_pct(r.get("return_20d"))
                rev = _format_ratio_pct(r.get("revenue_growth_ttm"))
                prof = _format_ratio_pct(r.get("profit_growth_ttm"))
                c_score = _format_num(r.get("crowding_score"))
                lines.append(
                    f"| **{name}** | **{r20}** | {rev} | {prof} | `{c_score}%` | [避险] 逆势走强业绩高增，主力避风港 |"
                )
        else:
            lines.append("*(当前暂无逆势上涨且量价齐升的避险主线)*")

        lines.append("")
        lines.append("### 恐慌排雷：看似超跌「假黄金坑/飞刀」名单 (坚决回避抄底)")
        lines.append(
            "> 筛选逻辑：跌幅看似巨大，但产业正在遭遇在建工程激增投产 (cip_yoy > 25% 或 cip/fa > 35%)，或利润大幅失速，看似便宜实为周期反噬。"
        )

        fake_gold = (
            df.filter(
                (pl.col("return_20d") < 0.0)
                & (
                    (pl.col("cip_yoy") > 25.0)
                    | (pl.col("cip_to_fa_ratio") > 0.35)
                    | (pl.col("profit_growth_ttm") < -0.15)
                )
            )
            .sort("return_20d", descending=False)
            .head(6)
        )

        if not fake_gold.is_empty():
            lines.append(
                "| 二级行业 | 近20日跌幅 | 在建工程同比 | 在建/固资比 | 净利TTM YoY | 假坑排雷结论 |"
            )
            lines.append("| :--- | :---: | :---: | :---: | :---: | :--- |")
            for r in fake_gold.to_dicts():
                name = r.get("industry_name", r.get("industry_code", "-"))
                r20 = _format_pct(r.get("return_20d"))
                cip = _format_pct(r.get("cip_yoy"))
                ratio = _format_num(r.get("cip_to_fa_ratio"), 2)
                prof = _format_ratio_pct(r.get("profit_growth_ttm"))
                lines.append(
                    f"| **{name}** | {r20} | {cip} | `{ratio}` | {prof} | [假坑] 产能过剩/盈利失速，接飞刀陷阱 |"
                )
        else:
            lines.append("*(当前暂无显著产能过剩的假坑行业)*")
        lines.append("")

    return "\n".join(lines)


__all__ = ["build_meso_penetration_section"]
