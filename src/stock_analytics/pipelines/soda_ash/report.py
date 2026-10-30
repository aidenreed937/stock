"""纯碱全景研报 Markdown 渲染（数据驱动）。

报告中的公司面板、历史周期拐点、现货基差与产能事件全部来自管线数据，
不再内嵌硬编码的公司结论/年份；机制解读统一标注为推断。公司面板渲染见
:mod:`company`，共享格式工具见 :mod:`formatting`。
"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_analytics.pipelines.soda_ash.company import _render_company_section
from stock_analytics.pipelines.soda_ash.config import SodaAshConfig
from stock_analytics.pipelines.soda_ash.formatting import (
    FLOW_REGIME_CN,
    PROCESS_TYPE_CN,
    _flow_cn,
    _flow_comment,
    _fmt_pct,
    _fmt_val,
)
from stock_analytics.pipelines.soda_ash.panorama import latest_core_row

_EMPTY_REPORT = (
    "# 纯碱全景对账报告 (无数据)\n\n"
    "> 未找到 NBS 纯碱月度产量核心输入，管线未生成全景表。"
    "请先确认 `data/raw/industry/chemicals/nbs/nbs_soda_ash_monthly.csv` 存在且非空。\n"
)

_STATUS_TIME_LABEL: dict[str, str] = {
    "operating": "投产时间",
    "under_construction": "计划投产",
    "shutdown": "关停时间",
}


def render_markdown(
    panorama: pl.DataFrame,
    projects: list[dict[str, Any]],
    company_panel: pl.DataFrame | None,
    spot_benchmark: dict[str, Any] | None,
    episodes: list[dict[str, Any]],
    gate_evaluation: dict[str, Any] | None,
    config: SodaAshConfig,
) -> str:
    """渲染纯碱全景投研 Markdown 报告（数据驱动）。"""
    if panorama.is_empty():
        return _EMPTY_REPORT

    # 基准月取最近一个核心产量非空的月份：NBS 存在「月份已建行但值待发布」的尾行
    latest_row = latest_core_row(panorama) or panorama.tail(1).to_dicts()[0]
    recent_rows = panorama.tail(12).to_dicts()
    last_month = str(panorama["report_month"].max())
    pending_note = (
        f"\n> **数据待发布**: `{last_month}` 月度核心产量尚未发布，"
        f"报告基准月取最近完整月份 `{latest_row.get('report_month')}`。"
        if str(latest_row.get("report_month")) != last_month
        else ""
    )
    sections = [
        _render_header(latest_row, config, pending_note),
        _render_latest_status(latest_row, spot_benchmark or {}),
        _render_capacity_projects(projects, latest_row),
        _render_recent_table(recent_rows),
        _render_history_episodes(episodes),
        _render_company_section(company_panel),
        _render_gate_section(gate_evaluation),
    ]
    return "\n".join(sections)


def _render_header(row: dict[str, Any], config: SodaAshConfig, pending_note: str = "") -> str:
    return f"""# 纯碱 (Soda Ash / SA) 全景基本面对账研报

> **报告基准**: 最新完整月份 `{row.get("report_month")}` | 行业: **申万二级 220200 化学原料**
> **数据底座**: NBS 官方产量 + GACC 海关出口 + 郑商所仓单/龙虎榜 + 隆众厂库 + 100ppi现货基准 + 成本配置模型
> **产物管线**: {config.title}（`stock_analytics.pipelines.soda_ash`，ArtifactStore + manifest）{pending_note}"""


def _render_latest_status(
    row: dict[str, Any],
    spot: dict[str, Any],
) -> str:
    lines = [
        "## 一、 核心基本面诊断与最新状态",
        "",
        f"- **最新月度产量**: {_fmt_val(row.get('soda_output_w_tons'), 1)} 万吨"
        f" ({_fmt_pct(row.get('soda_output_yoy'))} YoY)",
        f"- **下游平板玻璃**: {_fmt_val(row.get('glass_output_w_cases'), 1)} 万重量箱"
        f" ({_fmt_pct(row.get('glass_output_yoy'))} YoY)",
        f"- **供需剪刀差 (玻璃增速 - 纯碱增速)**: **{_fmt_pct(row.get('scissors_spread_yoy'))}**",
        "- **库存双轨与产销状态**:",
        f"  - 郑商所注册仓单月末值: `{_fmt_val(row.get('warehouse_receipt_month_end'), 0)}` 张",
        f"  - 样本企业厂库月末值: `{_fmt_val(row.get('factory_inv_month_end_w_tons'), 1)}` 万吨",
        f"  - 周度出货率 (产销率): 最新周 `{_fmt_pct(row.get('latest_shipment_rate_pct'))}`"
        f" (月均 `{_fmt_pct(row.get('survey_shipment_rate_pct'))}`)",
        f"  - 中游蓄水池状态机诊断: **`{_flow_cn(row.get('inventory_flow_regime'))}`**"
        f"{_flow_comment(row.get('inventory_flow_regime'))}",
        f"- **联碱双吨理论利润**: `{_fmt_val(row.get('double_ton_margin_cny'), 1)}` 元/吨"
        f" (状态: `{row.get('margin_regime') or '--'}`)",
        f"- **期货资金博弈**: 前20净多单 `{_fmt_val(row.get('top20_net_long_vol'), 0)}` 手"
        f" (聪明钱偏向: `{row.get('smart_money_bias') or '--'}`){_render_spot_lines(spot)}",
    ]
    return "\n".join(lines)


def _render_spot_lines(spot: dict[str, Any]) -> str:
    sa_heavy = spot.get("sa_heavy_price")
    sa_light = spot.get("sa_light_price")
    sa_fut = spot.get("futures_sa0_settle")
    basis = spot.get("basis_cny")
    basis_rate = spot.get("basis_rate_pct")
    if sa_heavy is None and sa_light is None:
        return ""

    out = [
        "",
        "- **现货出厂基准与基差 (Basis) 监控 (生意社 100ppi vs 郑商所)**:",
    ]
    if sa_heavy is not None and sa_fut is not None:
        out.append(
            f"  - 100ppi 重质纯碱出厂基准: `{sa_heavy:.2f}` 元/吨 | 郑商所 SA0 结算价: `{sa_fut:.2f}` 元/吨"
        )
        out.append(
            f"  - 现货-期货基差 (Basis): **`{basis:+.2f}` 元/吨** (基差率: `{basis_rate:+.2f}%`)"
        )
    if sa_light is not None:
        out.append(f"  - 100ppi 轻质纯碱出厂基准: `{sa_light:.2f}` 元/吨")

    chain: list[str] = []
    for label, key in (
        ("尿素", "ur_price"),
        ("动力煤 Q5500", "zc_price"),
        ("浮法玻璃", "fg_price"),
        ("烧碱 32%", "sh_price"),
    ):
        value = spot.get(key)
        if value is not None:
            chain.append(
                f"{label} `{float(value):.1f}` 元/吨"
                if key != "fg_price"
                else f"{label} `{float(value):.2f}` 元/㎡"
            )
    if chain:
        out.append(f"  - 产业链关联品现货: {' | '.join(chain)}")
    return "\n".join(out)


def _render_capacity_projects(
    projects: list[dict[str, Any]],
    latest_row: dict[str, Any],
) -> str:
    cum_raw = latest_row.get("cum_cap_expansion_w_tons")
    cum_exp = "--"
    if cum_raw is not None:
        try:
            cum_exp = f"{float(cum_raw):+.1f}"
        except (TypeError, ValueError):
            cum_exp = "--"
    proj_lines = [
        "## 二、 纯碱重大产能事件种子库跟踪 (Ground Truth)",
        "",
        f"累计跟踪**已投达产**有效产能变动: **{cum_exp} 万吨/年**",
        "",
        "> 口径: 仅累计 `actual_start` 已发生的投产/关停事件；`under_construction` 项目"
        "的计划投产时间不计入累计，避免把规划产能当作既成事实（防前视）。",
        "",
    ]
    if not projects:
        proj_lines.append("- 当前无结构化产能事件记录")
    for p in projects:
        status = str(p.get("status"))
        date_str = p.get("actual_start") or p.get("expected_start") or "待定"
        time_label = _STATUS_TIME_LABEL.get(status, "时间节点")
        proj_lines.append(
            f"- **{p.get('company')} ({p.get('plant_name')})**: {p.get('capacity_w_tons')} 万吨/年 | "
            f"工艺: {p.get('technology')} | 状态: {status} | {time_label}: `{date_str}` ({p.get('source')})"
        )
    return "\n".join(proj_lines)


def _render_recent_table(rows: list[dict[str, Any]]) -> str:
    table_rows = [_recent_table_row(r) for r in rows]
    return "\n".join(
        [
            "## 三、 近 12 个月供需平衡、库存分层与利润对账表",
            "",
            "| 月份 | 纯碱产量 (万吨) | 玻璃需求 (万箱) | 供需剪刀差 | 交易所仓单 (张) | 样本厂库 (万吨) | 周出货率 | 蓄水池状态 | 双吨利润 (元/吨) |",
            "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
            *table_rows,
        ]
    )


def _recent_table_row(r: dict[str, Any]) -> str:
    m = r.get("report_month")
    s_out = _fmt_val(r.get("soda_output_w_tons"), 1)
    s_yoy = _fmt_pct(r.get("soda_output_yoy"))
    g_out = _fmt_val(r.get("glass_output_w_cases"), 1)
    g_yoy = _fmt_pct(r.get("glass_output_yoy"))
    scis = _fmt_pct(r.get("scissors_spread_yoy"))
    receipt = _fmt_val(r.get("warehouse_receipt_month_end"), 0)
    f_inv = _fmt_val(r.get("factory_inv_month_end_w_tons"), 1)
    ship_val = _fmt_pct(r.get("latest_shipment_rate_pct") or r.get("survey_shipment_rate_pct"))
    f_regime = _flow_cn(r.get("inventory_flow_regime"))
    margin = _fmt_val(r.get("double_ton_margin_cny"), 1)
    regime = r.get("margin_regime") or "--"
    return (
        f"| `{m}` | {s_out} ({s_yoy}) | {g_out} ({g_yoy}) | **{scis}** | {receipt} | "
        f"{f_inv} | {ship_val} | {f_regime} | {margin} ({regime}) |"
    )


def _render_history_episodes(episodes: list[dict[str, Any]]) -> str:
    lines = [
        "## 四、 历史利润状态期与量化实证（数据实证 + 机制推断）",
        "",
        "> 以下状态期由本地 Curated 数据按利润状态机（margin_regime）自动识别，"
        "数值为实际数据；机制解读为推断，非投资建议。当前窗口未出现 `deep_loss` "
        "时仅列出已出现状态。",
        "",
    ]
    if not episodes:
        lines.append("- 当前数据窗口内未识别到连续的高利润/深度亏损状态期（或价差数据缺失）。")
        return "\n".join(lines)

    for ep in episodes:
        spot_range = (
            f"现货价格 {ep['spot_min']}~{ep['spot_max']} 元/吨"
            if ep.get("spot_min") is not None
            else "现货价格缺数据"
        )
        scissors = "、".join(
            f"{v:.1f}" for v in (ep.get("scissors_first"), ep.get("scissors_last")) if v is not None
        )
        scissors_txt = f"供需剪刀差 {scissors}%" if scissors else "供需剪刀差缺数据"
        transition = f"；{ep['transition_note']}" if ep.get("transition_note") else ""
        lines.append(
            f"- **{ep['start']} ~ {ep['end']}（{ep['label']}）**: 持续 {ep['months_count']} 个月，"
            f"双吨理论利润均值 `{ep['margin_mean']:.0f}` 元/吨（区间 {ep['margin_min']:.0f} ~ {ep['margin_max']:.0f}），"
            f"{spot_range}；{scissors_txt}{transition}"
        )
    return "\n".join(lines)


def _render_gate_section(gate_evaluation: dict[str, Any] | None) -> str:
    """渲染周期股分阶段量化交易门禁诊断（第 6 节，状态来自门禁评估）。"""
    if not gate_evaluation:
        return ""

    left_s = gate_evaluation.get("left_side_odds", {})
    right_s = gate_evaluation.get("right_side_confirmation", {})
    top_s = gate_evaluation.get("top_escape", {})

    left_tag = "**触发 (满足)**" if left_s.get("triggered") else "未满足"
    right_tag = "**触发加码**" if right_s.get("triggered") else "未满足 (观望)"
    match_txt = (
        f" [{top_s.get('match_count')}/{top_s.get('trigger_match_count_min')} 因子]"
        if top_s.get("match_count") is not None
        else ""
    )
    top_tag = (
        f"⚠️ **清仓**{match_txt}"
        if top_s.get("triggered")
        else (f"⚠️ **减半预警**{match_txt}" if top_s.get("warning") else f"安全 (未触发){match_txt}")
    )

    return "\n".join(
        [
            "---",
            "",
            "## 六、 周期股分阶段量化交易门禁诊断 (基于 soda_ash/trading_gates.yaml)",
            "",
            "### 1. 三大阶段门禁状态速览",
            "| 门禁类型 | 当前状态 | 核心量化条件对账 | 建议动作与仓位约束 |",
            "| :--- | :---: | :--- | :--- |",
            f"| **1. 左侧赔率建仓门禁** | {left_tag} | - {left_s.get('cond_margin_desc')}<br>"
            f"- {left_s.get('cond_pb_desc')}<br>- {left_s.get('cond_role_pb_desc')}"
            f"{('<br>- ' + left_s.get('cond_seasonal_desc')) if left_s.get('cond_seasonal_desc') else ''} | "
            f"**{left_s.get('suggestion')}** |",
            f"| **2. 右侧胜率确认门禁** | {right_tag} | - {right_s.get('cond_op_desc')}<br>"
            f"- {right_s.get('cond_destock_desc')}<br>- {right_s.get('cond_basis_desc')}<br>"
            f"- {right_s.get('cond_demand_desc')}<br>- {right_s.get('cond_ma_desc')}"
            f"{('<br>- ' + right_s.get('cond_seasonal_desc')) if right_s.get('cond_seasonal_desc') else ''} | "
            f"**{right_s.get('suggestion')}** |",
            f"| **3. 逃顶多因子清仓门禁** | {top_tag} | - {top_s.get('cond_op_desc')}<br>"
            f"- {top_s.get('cond_margin_desc')}<br>- {top_s.get('cond_flow_desc')}<br>"
            f"- {top_s.get('cond_pe_desc')}<br>- {top_s.get('cond_divergence_desc')} | "
            f"**{top_s.get('suggestion')}** |",
            "",
            "### 2. 标的角色分工与实操配置指引（机制推断，非投资建议）",
            "- **成本阿尔法龙头 (`000683.SZ` 远兴能源)**: 对应左侧底仓核心配置角色。"
            "天然碱法为行业最低成本路线（单耗与加工费口径见 `soda_ash/cost_models.yaml`），"
            "在行业边际失血期具备长期存活与抗亏阿尔法；",
            "- **极低破净高弹性贝塔 (`600328.SH` 中盐化工、`000707.SZ` 双环科技)**: "
            "破净深、PB 处于 10 年极值分位，列入右侧胜率加码观察池。"
            "**在右侧确认门禁（开工率、连续去库期数、基差、需求共振、均线）未全部满足前，"
            "严禁重仓追高抢反弹**；",
            "- **边际出清风向标 (`000822.SZ` 山东海化)**: 纯氨碱高成本标的，"
            "其减产检修与单季大额计提存货跌价损失是全行业出清底部的先行前瞻指标。",
        ]
    )


__all__ = ["FLOW_REGIME_CN", "PROCESS_TYPE_CN", "render_markdown"]
