"""PTA 全景对账与双雄 SOTP 测算研报渲染器。

输出包含宏观供需剪刀差、仓单流向状态机、交易门禁决策、双雄三情景预测与敏感性矩阵的 Markdown 研报。
"""

from __future__ import annotations

import datetime
from typing import Any

import polars as pl

from stock_analytics.pipelines.pta.panorama import (
    CHAIN_MARGIN_REGIME_CN,
    FLOW_REGIME_CN,
)
from stock_analytics.pipelines.pta.projections import PtaProjectionResult


def render_markdown(
    panorama_df: pl.DataFrame,
    projects: list[dict[str, Any]],
    gate_res: dict[str, Any],
    company_panel: pl.DataFrame | None = None,
    hengli_projections: list[PtaProjectionResult] | None = None,
    tongkun_projections: list[PtaProjectionResult] | None = None,
    sensitivity_df: pl.DataFrame | None = None,
    episodes: list[dict[str, Any]] | None = None,
    as_of: str | None = None,
) -> str:
    """渲染生产级 PTA 全景基本面对账与量化研报。"""
    today_str = as_of or datetime.date.today().isoformat()

    lines: list[str] = [
        "# PTA (精对苯二甲酸 / TA) 最小可行闭环全景基本面对账研报",
        "",
        f"> **生成时间**: {today_str} | **品类属性**: A 类大宗标准化与期货品种 (`A_commodity_standard`)",
        "> **核心数据源**: 郑商所 CZCE 仓单与行情 + NBS 实物产量 + GACC 海关出口 + 100ppi 现货基准 + 双雄 SOTP 预测引擎",
        "",
        "---",
        "",
        "## 一、 周期股分阶段量化交易门禁诊断 (commodity_standard_gate)",
        "",
    ]

    # 1. 门禁状态汇总
    overall = gate_res.get("overall_regime", "neutral_monitoring")
    rec_action = gate_res.get("recommended_action", "wait_and_see")
    active_gates = ", ".join(gate_res.get("active_gates", [])) or "无触发 (观望期)"

    regime_map = {
        "top_escape": "【一票否决逃顶】(高负荷/超额暴利/个位数低PE陷阱)",
        "right_side_bull": "【右侧胜率反转确认】(检修去库/基差转强/需求放量)",
        "left_side_bottom": "【左侧赔率筑底】(跌穿现金保本/深度破净/布局成本龙头)",
        "neutral_monitoring": "【中性监控磨底】(等待明确物理减产或补库拐点)",
    }

    action_map = {
        "clear_position": "清仓离场 / 坚决不参与最后一棒博弈",
        "heavy_position_attack": "重仓进攻 (仓位上限 80%) / 首选弹性龙头 601233.SH (桐昆股份)",
        "light_position_build": "轻仓试探建仓 (仓位上限 30%) / 首选抗亏阿尔法 600346.SH (恒力石化)",
        "wait_and_see": "保持观望 / 跟踪周度开工率与现货基差变化",
    }

    lines.extend(
        [
            f"- **当前周期定位**: {regime_map.get(overall, overall)}",
            f"- **量化操作建议**: {action_map.get(rec_action, rec_action)}",
            f"- **触发门禁清单**: `{active_gates}`",
            "",
            "### 门禁详细体检",
            "| 门禁类型 | 触发状态 | 核心条件满足情况 | 优选标的与仓位控制 |",
            "| :--- | :---: | :--- | :--- |",
        ]
    )

    g_details = gate_res.get("gate_details", {})
    l_g = g_details.get("left_side_odds", {})
    lines.append(
        f"| **左侧赔率门禁** | {'✅ 触发' if l_g.get('triggered') else '❌ 未触发'} | 加工费亏损线: {l_g.get('margin_triggered')} / 估值破净: {l_g.get('valuation_triggered')} | {l_g.get('target', '恒力石化')} (上限 {l_g.get('max_position_pct', 30)}%) |"
    )
    r_g = g_details.get("right_side_confirmation", {})
    lines.append(
        f"| **右侧胜率门禁** | {'✅ 触发' if r_g.get('triggered') else '❌ 未触发'} | 基差升水: {r_g.get('basis_confirmed')} / 持续去库: {r_g.get('destocking_confirmed')} / 需求验证: {r_g.get('demand_confirmed')} | {r_g.get('target', '桐昆股份')} (上限 {r_g.get('max_position_pct', 80)}%) |"
    )
    t_g = g_details.get("top_escape", {})
    lines.append(
        f"| **逃顶一票否决** | {'⚠️ 触发' if t_g.get('triggered') else '✅ 安全'} | 超额暴利: {t_g.get('high_profit')} / 被动累库: {t_g.get('passive_accumulation')} / 低PE陷阱: {t_g.get('pe_trap')} | {t_g.get('action', '清仓')} |"
    )

    lines.extend(["", "---", "", "## 二、 供需物理量、期货仓单与库存蓄水池对账全景"])

    if not panorama_df.is_empty():
        recent = panorama_df.tail(6).to_dicts()
        lines.extend(
            [
                "| 月份 | PTA产量 (万吨) | 化纤产量 (万吨) | 供需剪刀差 (yoy) | PTA加工费 (元/吨) | POY加工差 (元/吨) | 上下游利润博弈 | 仓单月末 (张) | 蓄水池流向 | 基差率 (%) |",
                "| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
            ]
        )
        for r in recent:
            m = r.get("report_month")
            p_out = f"{r.get('pta_output_w_tons'):.1f}" if r.get("pta_output_w_tons") else "--"
            f_out = (
                f"{r.get('synthetic_fiber_production'):.1f}"
                if r.get("synthetic_fiber_production")
                else "--"
            )
            sc = (
                f"{r.get('scissors_spread_yoy'):+.1f}%"
                if r.get("scissors_spread_yoy") is not None
                else "--"
            )
            sp = (
                f"{r.get('spread_margin_monthly_avg'):.0f}"
                if r.get("spread_margin_monthly_avg") is not None
                else "--"
            )
            poy_sp = (
                f"{r.get('poy_spread_monthly_avg'):.0f}"
                if r.get("poy_spread_monthly_avg") is not None
                else "--"
            )
            cmr = CHAIN_MARGIN_REGIME_CN.get(str(r.get("chain_margin_regime")), "--")
            rec = (
                f"{r.get('warehouse_receipt_month_end'):.0f}"
                if r.get("warehouse_receipt_month_end")
                else "--"
            )
            fl = FLOW_REGIME_CN.get(str(r.get("inventory_flow_regime")), "--")
            bs = f"{r.get('basis_rate_pct'):+.2f}%" if r.get("basis_rate_pct") is not None else "--"
            lines.append(
                f"| {m} | {p_out} | {f_out} | {sc} | {sp} | {poy_sp} | {cmr} | {rec} | {fl} | {bs} |"
            )

        lines.extend(
            [
                "",
                "> **期现交割制度警示 (CZCE 9月大注销)**：郑商所交割细则规定每年 9 月第 15 个交易日之前，老 PTA 标准仓单必须集中全部注销（转现货出库或重新检验）。因此每年 8-9 月仓单都会发生制度性断崖式清零/降至数千张（如 2022 年 9 月降至 1,002 张、2023 年降至 5,639 张、2024 年降至 8,603 张、2026 年降至 1,069 张）。此断崖式去化属于**交易所制度性期转现/显性库存隐性化**，绝不能简单误判为终端实体纺织需求的爆发性去库。",
            ]
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 三、 GACC 海关出口与海外外需泄洪对账",
            "> 跟踪聚酯化纤（涤纶长丝 + 聚酯短纤）海外月度出口实物量、出口增速与出口拉动率（泄库比例）。数据源仅采用海关总署黄金事实表 `customs_trade_gacc`。",
        ]
    )

    if not panorama_df.is_empty() and "polyester_export_w_tons" in panorama_df.columns:
        exp_recent = (
            panorama_df.filter(pl.col("polyester_export_w_tons").is_not_null()).tail(12).to_dicts()
        )
        if exp_recent:
            lines.extend(
                [
                    "",
                    "| 报告月份 | 国内化纤产量 (万吨) | 聚酯出口量 (万吨) | 出口同比增速 (YoY) | 出口泄库拉动率 (%) | 外需状态诊断 |",
                    "| :---: | :---: | :---: | :---: | :---: | :---: |",
                ]
            )
            for r in exp_recent:
                m = r.get("report_month")
                f_out = (
                    f"{r.get('synthetic_fiber_production'):.1f}"
                    if r.get("synthetic_fiber_production")
                    else "--"
                )
                e_vol = (
                    f"{r.get('polyester_export_w_tons'):.2f}"
                    if r.get("polyester_export_w_tons")
                    else "--"
                )
                e_yoy = (
                    f"{r.get('polyester_export_yoy'):+.1f}%"
                    if r.get("polyester_export_yoy") is not None
                    else "--"
                )
                pull = (
                    f"{r.get('export_pull_rate_pct'):.2f}%"
                    if r.get("export_pull_rate_pct") is not None
                    else "--"
                )
                pull_val = float(r.get("export_pull_rate_pct") or 0.0)
                status = (
                    "强力泄库"
                    if pull_val >= 7.5
                    else ("平稳泄洪" if pull_val >= 5.5 else "外需承压")
                )
                lines.append(f"| {m} | {f_out} | {e_vol} | {e_yoy} | {pull} | {status} |")

    lines.extend(
        [
            "",
            "## 四、 双雄 (恒力石化 vs 桐昆股份) SOTP 分部测算与情景推演",
            "",
        ]
    )

    # 恒力石化 SOTP
    if hengli_projections:
        lines.extend(
            [
                "### 1. 恒力石化 (`600346.SH`) - 上游大炼化一体化极致成本龙头",
                "> 周期股估值反向时钟准则：底部净利亏损/微利时 PE 失效，启用资产重置成本与破净防御线 (PB Floor) 托底。",
                "| 情景标尺 | 营业收入 (亿元) | 综合毛利 (亿元) | 财务费用 (亿元) | 归母净利润 (亿元) | 隐含 ROE | 估值锚点 | 隐含 PB | 公允市值 (亿元) |",
                "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
            ]
        )
        for pr in hengli_projections:
            rev = pr.total_revenue_cny / 1e8
            gp = pr.total_gross_profit_cny / 1e8
            fe = pr.finance_expense_cny / 1e8
            np_ = pr.net_profit_cny / 1e8
            mv = pr.fair_market_value_cny / 1e8
            if pr.valuation_method == "pb_asset_floor":
                anchor_str = f"**{pr.target_pb:.2f}x PB (重置托底)**"
            else:
                anchor_str = f"{pr.target_pe:.1f}x PE" if pr.target_pe is not None else "--"
            lines.append(
                f"| **{pr.scenario_name}** | {rev:.1f} | {gp:.1f} | {fe:.1f} | **{np_:.1f}** | {pr.implied_roe:.1f}% | {anchor_str} | {pr.implied_pb:.2f}x | **{mv:.1f}** |"
            )
        lines.append("")

    # 桐昆股份 SOTP
    if tongkun_projections:
        lines.extend(
            [
                "### 2. 桐昆股份 (`601233.SH`) - 下游涤纶长丝绝对龙头 + 浙石化投资收益",
                "> 周期股估值反向时钟准则：底部长丝亏损时看破净极值底线，中枢与景气高峰按长丝吨毛利修复及浙石化投资收益弹性定价。",
                "| 情景标尺 | 营业收入 (亿元) | 综合毛利 (亿元) | 浙石化收益 (亿元) | 归母净利润 (亿元) | 隐含 ROE | 估值锚点 | 隐含 PB | 公允市值 (亿元) |",
                "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
            ]
        )
        for pr in tongkun_projections:
            rev = pr.total_revenue_cny / 1e8
            gp = pr.total_gross_profit_cny / 1e8
            eq_inv = pr.equity_investment_income_cny / 1e8
            np_ = pr.net_profit_cny / 1e8
            mv = pr.fair_market_value_cny / 1e8
            if pr.valuation_method == "pb_asset_floor":
                anchor_str = f"**{pr.target_pb:.2f}x PB (破净底线)**"
            else:
                anchor_str = f"{pr.target_pe:.1f}x PE" if pr.target_pe is not None else "--"
            lines.append(
                f"| **{pr.scenario_name}** | {rev:.1f} | {gp:.1f} | {eq_inv:.1f} | **{np_:.1f}** | {pr.implied_roe:.1f}% | {anchor_str} | {pr.implied_pb:.2f}x | **{mv:.1f}** |"
            )
        lines.append("")

    # 敏感性分析
    if sensitivity_df is not None and not sensitivity_df.is_empty():
        lines.extend(
            [
                "---",
                "",
                "## 五、 敏感性分析矩阵 (归母净利润 / 亿元)",
                "> **基准情景**: 中性中枢复苏 (`mid_cycle`) | **X 轴**: 现货价格 (元/吨) | **Y 轴**: 原料 PX CFR 价格 (元/吨)",
                "",
            ]
        )
        headers = sensitivity_df.columns
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join([":---:"] * len(headers)) + " |")
        for r in sensitivity_df.iter_rows(named=True):
            vals = [str(r[c]) for c in headers]
            lines.append("| " + " | ".join(vals) + " |")
        lines.append("")

    # 历史大拐点回测
    if episodes:
        lines.extend(
            [
                "---",
                "",
                "## 六、 历史加工费大拐点与后验表现",
                "| 拐点类型 | 起始月份 | 结束月份 | 持续月数 | 期间平均加工费 (元/吨) | 之后 3 个月均价 (元/吨) |",
                "| :--- | :---: | :---: | :---: | :---: | :---: |",
            ]
        )
        for ep in episodes:
            t_str = "超额暴利顶区" if ep["type"] == "high_profit_peak" else "跌穿现金流底区"
            fu = (
                f"{ep['follow_up_avg_spread']:.0f}"
                if ep.get("follow_up_avg_spread") is not None
                else "--"
            )
            lines.append(
                f"| **{t_str}** | {ep['start_month']} | {ep['end_month']} | {ep['duration_months']} | {ep['avg_spread']:.0f} | {fu} |"
            )
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## 七、 风险提示",
            "1. **原油与地缘波动风险**: 原油单边暴跌将引发大炼化库存巨额减值；",
            "2. **宏观纺织外需收缩**: 欧美及新兴市场纺服关税壁垒提升压制长丝开工率；",
            "3. **大炼化重资产利息刚性**: 负债去化进度若慢于预期，高额财务费用将持续侵蚀业绩。",
        ]
    )

    return "\n".join(lines)
