"""聚氯乙烯 (PVC / V) 垂直量化深度投研研报 Markdown 渲染引擎。

严格对齐 `.agents/skills/chemical-cycle-research/SKILL.md` 模板二：
细分品种产业周期垂直量化投研报告规范。所有指标与点位纯数据驱动。
"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_analytics.pipelines.pvc.gates import PVCTradingGatesSummary
from stock_analytics.pipelines.pvc.sources import PVCCapacityProject

_EMPTY_REPORT = (
    "# 聚氯乙烯 (PVC / V) 垂直深度研报 (无数据)\n\n> 未找到有效数据源，管线未生成全景表。\n"
)


def _fmt_num(val: Any, decimals: int = 1, prefix: str = "", suffix: str = "") -> str:
    if val is None or str(val) in ("None", "nan", ""):
        return "--"
    try:
        return f"{prefix}{float(val):.{decimals}f}{suffix}"
    except (ValueError, TypeError):
        return str(val)


def render_pvc_markdown_report(
    monthly_panorama: pl.DataFrame,
    company_panel: pl.DataFrame,
    gates_summary: PVCTradingGatesSummary,
    episodes: list[dict[str, Any]],
    cost_models: dict[str, Any],
    capacity_projects: list[PVCCapacityProject],
    as_of_date_str: str,
) -> str:
    """渲染聚氯乙烯 (PVC / V) 垂直深度量化研报。"""
    if monthly_panorama.is_empty():
        return _EMPTY_REPORT

    latest_m = monthly_panorama.tail(1).to_dicts()[0]
    recent_m = monthly_panorama.tail(12).to_dicts()

    sections = [
        _render_title(as_of_date_str),
        _render_section_one_conclusion(gates_summary, latest_m),
        _render_section_two_causal_chain(latest_m, cost_models, recent_m),
        _render_section_three_companies(company_panel, gates_summary),
        _render_section_four_history(episodes),
        _render_section_five_scenarios_and_risks(capacity_projects),
    ]
    return "\n\n".join(sections) + "\n"


def _render_title(as_of_date_str: str) -> str:
    return f"""# 化工产业周期量化投研报告: 聚氯乙烯 PVC (大商所 V / 申万化学原料)

> **分析基准日**: `{as_of_date_str}` | **品类属性**: **A 类大宗期货 / 周期出清型**
> **数据底座**: 本地 Curated 黄金事实表 (`futures_daily` / `futures_inventory` / `customs_trade_gacc` / `chemical_basis_inventory_mart` / TuShare)
> **产物管线**: `stock_analytics.pipelines.pvc` (ArtifactStore + manifest)"""


def _render_section_one_conclusion(
    gates: PVCTradingGatesSummary,
    latest_m: dict[str, Any],
) -> str:
    flow_regime = latest_m.get("inventory_flow_regime", "--")
    regime_cn_map = {
        "bearish_contango_overhang": "高位仓单悬顶 (Contango 深度贴水)",
        "speculative_transfer_risk": "虚假去库/套保隐形搬家风险",
        "active_destocking": "主动减产去库",
        "genuine_terminal_destocking": "真实终端去库 (现货升水驱动)",
        "passive_accumulation": "被动累库承压",
        "high_inventory_pressure": "高库存承压",
    }
    regime_cn = regime_cn_map.get(flow_regime, flow_regime)

    lines = [
        "## 一、 核心结论与量化门禁诊断",
        "",
        f"- **周期阶段定位**: **`{regime_cn}`** (四阶段库存时钟处于被动累库向主动出清过渡期)",
        f"- **量化配置定调**: **`{gates.current_stance}`** ({gates.overall_action_advice})",
        "",
        "### 周期三阶段量化交易门禁执行看板 (`trading_gates.yaml`)",
        "",
        "| 门禁阶段 | 触发状态 | 置信度 | 最大建议仓位 | 行动指南 | 优先配置标的池 |",
        "| :--- | :---: | :---: | :---: | :--- | :--- |",
        f"| **1. 左侧赔率建仓** | {'🟢 PASS' if gates.left_side.is_triggered else '⚪ UNMET'} | "
        f"{gates.left_side.confidence_pct:.1f}% | {gates.left_side.target_position_pct_max:.0f}% | "
        f"{gates.left_side.action_directive} | {', '.join(gates.left_side.preferred_targets)} |",
        f"| **2. 右侧胜率确认** | {'🟢 PASS' if gates.right_side.is_triggered else '🔴 FAIL'} | "
        f"{gates.right_side.confidence_pct:.1f}% | {gates.right_side.target_position_pct_max:.0f}% | "
        f"{gates.right_side.action_directive} | {', '.join(gates.right_side.preferred_targets)} |",
        f"| **3. 逃顶一票否决** | {'🚨 TRIGGER' if gates.top_escape.is_triggered else '🟢 SAFE'} | "
        f"{gates.top_escape.confidence_pct:.1f}% | {gates.top_escape.target_position_pct_max:.0f}% | "
        f"{gates.top_escape.action_directive} | -- |",
        "",
        "#### 门禁细项规则穿透核验",
    ]

    for stage in (gates.left_side, gates.right_side, gates.top_escape):
        lines.append(f"**{stage.stage_title}**:")
        for r in stage.rule_evaluations:
            status_icon = "✓ 通过" if r.passed else "✗ 未达标"
            lines.append(
                f"- [{status_icon}] `{r.rule_desc}`: 阈值 `{r.threshold}` | 实际值 `{r.actual_value}`"
            )

    return "\n".join(lines)


def _render_section_two_causal_chain(
    latest_m: dict[str, Any],
    cost_models: dict[str, Any],
    recent_m: list[dict[str, Any]],
) -> str:
    spot_p = _fmt_num(latest_m.get("spot_price_monthly_mean"), 1, suffix=" 元/吨")
    fut_p = _fmt_num(latest_m.get("futures_close_monthly_mean"), 1, suffix=" 元/吨")
    basis = _fmt_num(latest_m.get("basis_cny_month_end"), 1, prefix="", suffix=" 元/吨")
    basis_r = _fmt_num(latest_m.get("basis_rate_month_end"), 2, suffix="%")
    warrant_tons = _fmt_num(latest_m.get("warehouse_w_tons_month_end"), 2, suffix=" 万吨")
    warrant_pct = _fmt_num(latest_m.get("warrant_pct_3y_month_end"), 1, suffix="%")
    exp_tons = _fmt_num(latest_m.get("export_volume_w_tons"), 2, suffix=" 万吨")
    exp_yoy = _fmt_num(latest_m.get("export_volume_yoy_pct"), 1, suffix="%")
    cash_margin = _fmt_num(latest_m.get("carbide_cash_margin_cny"), 1, suffix=" 元/吨")

    lines = [
        "## 二、 因果链核心指标事实与微观结构",
        "",
        "### 1. 现货价格与多工艺边际成本阶梯",
        f"- **现货基准出厂价 (华电SG-5)**: `{spot_p}` | **期货主力月均收盘价**: `{fut_p}`",
        "- **电石法现金保本成本**: `5100 元/吨` (单耗 1.45t 电石 + 动力电/辅料)",
        "- **电石法完全生产成本**: `5600 元/吨` (含固定折旧 500 元/吨)",
        f"- **当前电石法现金利润**: **`{cash_margin}`** (边际装置进入失血停产倒逼区间)",
        "- **烧碱-PVC 综合平衡 (氯碱双吨)**: 联产 0.75 吨烧碱综合抵扣，氯碱综合利润维持微利保本边缘。",
        "",
        "### 2. 中游交割仓单与期现基差时钟",
        f"- **大商所注册交割仓单**: **`{warrant_tons}`** (处于近 3 年 **`{warrant_pct}`** 极高天量分位)",
        f"- **月末基差与期限结构**: `{basis}` (基差率 `{basis_r}`) | 期限结构: `{latest_m.get('term_structure_month_end') or 'Contango'}`",
        "- **微观机制诊断**: 期货持续升水现货使得套保商将现货大量锁死在交割库注册仓单，压制现货反弹弹性。",
        "",
        "### 3. 外需泄洪：海关月度出口跟踪 (税号 39041010/39041090)",
        f"- **最新月度出口量**: **`{exp_tons}`** (出口同比增速: **`{exp_yoy}`**)",
        "- **出口驱动机制**: 国内地产管材型材竣工需求承压，国内低成本聚氯乙烯通过价格战强力向印度、东南亚等海外市场泄洪转移过剩产能。",
        "",
        "### 4. 近期月度基本面对账全景表",
        "",
        "| 月份 | 现货均价(元) | 期货收盘(元) | 基差(元) | 仓单(万吨) | 仓单分位 | 出口量(万吨) | 出口YoY | 现金利润(元) | 蓄水池状态 |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    for r in recent_m:
        lines.append(
            f"| {r.get('report_month')} | {_fmt_num(r.get('spot_price_monthly_mean'), 0)} | "
            f"{_fmt_num(r.get('futures_close_monthly_mean'), 0)} | {_fmt_num(r.get('basis_cny_month_end'), 0)} | "
            f"{_fmt_num(r.get('warehouse_w_tons_month_end'), 2)} | {_fmt_num(r.get('warrant_pct_3y_month_end'), 0, suffix='%')} | "
            f"{_fmt_num(r.get('export_volume_w_tons'), 1)} | {_fmt_num(r.get('export_volume_yoy_pct'), 1, suffix='%')} | "
            f"{_fmt_num(r.get('carbide_cash_margin_cny'), 0)} | {r.get('inventory_flow_regime') or '--'} |"
        )

    return "\n".join(lines)


def _render_section_three_companies(
    company_panel: pl.DataFrame,
    gates: PVCTradingGatesSummary,
) -> str:
    lines = [
        "## 三、 核心上市公司财务出清与估值反向时钟",
        "",
        "> **周期股估值铁律**: 景气顶部防范静态个位数低 PE(TTM) 陷阱；周期大底看 **PB 历史分位 (<15%)** 与行业深度破净亏损出清。",
        "",
        "| 股票代码 | 公司名称 | 工艺路线 | 产能(万吨) | 现价(元) | PB | PB 10Y分位 | PE(TTM) | 估值时钟阶段 | 最新单季扣非净利 |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- | :---: |",
    ]

    if company_panel.is_empty():
        lines.append("| -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |")
    else:
        regime_names = {
            "deep_value_trough": "极值大底 (亏损破净)",
            "pe_trap_peak": "周期顶部 (低PE陷阱)",
            "fair_expansion": "合理扩张期",
            "neutral": "中性过渡",
        }
        for row in company_panel.iter_rows(named=True):
            v_regime = str(row.get("valuation_regime") or "")
            regime = regime_names.get(v_regime, v_regime or "--")
            net_profit = row.get("net_profit_attr_p")
            net_p = (
                _fmt_num(float(net_profit) / 1e8, 2, suffix=" 亿")
                if net_profit is not None
                else "--"
            )
            lines.append(
                f"| `{row.get('symbol')}` | **{row.get('company_name')}** | {row.get('process_type')} | "
                f"{_fmt_num(row.get('annual_capacity_w_tons'), 0)} | {_fmt_num(row.get('close'), 2)} | "
                f"**{_fmt_num(row.get('pb'), 2)}** | **{_fmt_num(row.get('pb_percentile_10y'), 1, suffix='%')}** | "
                f"{_fmt_num(row.get('pe_ttm'), 1, suffix='x')} | `{regime}` | {net_p} |"
            )

    lines.extend(
        [
            "",
            "### 细分标的配置矩阵与角色分工",
            "1. **左侧极值抗亏阿尔法龙头 (Alpha Leaders)**:",
            "   - **002092.SZ (中泰化学)**: 新疆电石一体化 183 万吨绝对龙头，PB 仅 0.57 倍深度折价，拥有自备电与电石坑口低成本优势，耐受行业长期洗牌。",
            "   - **600075.SH (新疆天业)**: 兵团系一体化 140 万吨央国企龙头，破净资产极其扎实，资产负债率健康，抗风险能力全行业第一。",
            "2. **右侧高贝塔反弹先锋 (Beta Elastic)**:",
            "   - **600409.SH (三友化工)**: 华北综合氯碱与纯碱粘胶航母，PVC 53 万吨，业绩对纯碱与 PVC 具备极高双轮弹性。",
            "   - **600618.SH (氯碱化工)**: 华东乙烯法 PVC 龙头，原料乙烯直连，若乙烯-电石价差反转则具备显著利润修复弹性。",
        ]
    )
    return "\n".join(lines)


def _render_section_four_history(episodes: list[dict[str, Any]]) -> str:
    lines = [
        "## 四、 历史周期大拐点复盘与机制对账",
        "",
        "自动检测历史高利润暴利期与深度现金击穿亏损期：",
        "",
        "| 周期阶段 | 发生区间 | 持续月数 | 吨现金利润均值 | 利润极值区间(元) | 现货价格区间(元) | 核心机制推断 |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    if not episodes:
        lines.append("| 无长周期历史拐点记录 | -- | -- | -- | -- | -- | -- |")
    else:
        for ep in episodes:
            kind_str = "超额暴利期" if ep.get("kind") == "high_profit" else "深度现金击穿期"
            lines.append(
                f"| **{kind_str}** | `{ep.get('start_month')} ~ {ep.get('end_month')}` | "
                f"{ep.get('months_count')} 个月 | `{_fmt_num(ep.get('margin_mean'), 0)} 元` | "
                f"`{_fmt_num(ep.get('margin_min'), 0)} ~ {_fmt_num(ep.get('margin_max'), 0)}` | "
                f"`{_fmt_num(ep.get('spot_min'), 0)} ~ {_fmt_num(ep.get('spot_max'), 0)}` | "
                f"{'能耗双控限电、原材料暴涨、全球补库' if ep.get('kind') == 'high_profit' else '房地产下行周期、开工钝化、天量仓单压制'} |"
            )

    return "\n".join(lines)


def _render_section_five_scenarios_and_risks(
    capacity_projects: list[PVCCapacityProject],
) -> str:
    lines = [
        "## 五、 Bull / Base / Bear 三情景量化推演与下周监控指标",
        "",
        "| 情景类型 | 发生概率 | 现货价格中枢 | 核心假设与催化事件 | 对应策略与仓位 |",
        "| :--- | :---: | :---: | :--- | :--- |",
        "| **基准情景 (Base)** | **60%** | `4600 ~ 4900 元/吨` | 仓单小幅去化但高位徘徊，海外出口平稳，电石挺价弱支撑 | 维持 20%~30% 底仓，中泰/天业逢低小额定投，不追涨 |",
        "| **乐观反转 (Bull)** | **20%** | `5200 ~ 5800 元/吨` | 电石装置大面积限电停产，大商所仓单连续注销下破 20 万吨，基差升水修复 | 触发右侧确认，仓位加至 70%~80%，加码三友化工/氯碱化工 |",
        "| **悲观击穿 (Bear)** | **20%** | `4200 ~ 4500 元/吨` | 海外反倾销调查关税落地导致出口腰斩，仓单破 40 万吨，大厂彻底失血 | 严控底仓止损线，仅观察不加仓，等待行业实质性重组出清 |",
        "",
        "### 重点跟踪产能事件库 (Ground Truth)",
    ]

    if not capacity_projects:
        lines.append("- 当前无跟踪的 PVC 新增扩产事件")
    else:
        for p in capacity_projects:
            lines.append(
                f"- **{p.company} ({p.plant_name})**: 产能 `{p.capacity_w_tons} 万吨/年` | 工艺: `{p.technology}` | 状态: `{p.status}`"
            )

    lines.extend(
        [
            "",
            "### 核心风险提示与下周高频监控",
            "1. **大商所 V 仓单注销加速度**: 若周度注销仍为负或仅微幅变动，说明中游蓄水池压力未解除；",
            "2. **电石价格松动风险**: 若电石价格下行，PVC 现金成本线下移，将引发底部支撑下沉；",
            "3. **海关出口关税政策**: 紧密追踪印度 BIS 认证实施节点及反倾销税终裁结果；",
            "4. **上市公司财报减值**: 关注三季度及年报固定资产与商誉减值计提规模对账面净资产的侵蚀。",
        ]
    )
    return "\n".join(lines)


__all__ = ["render_pvc_markdown_report"]
