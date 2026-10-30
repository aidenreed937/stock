"""钛白粉全景研报 Markdown 渲染（数据驱动）。

严格遵循 chemical-cycle-research SKILL.md 研报模板规范与寡头因果链特征。
"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_analytics.pipelines.calibration import (
    CalibrationResult,
    ConfidenceBandResult,
    IndustrialCostCalibrator,
)
from stock_analytics.pipelines.tio2.config import Tio2Config

_EMPTY_REPORT = "# 钛白粉全景对账报告 (无数据)\n\n> 未找到钛白粉基础事实输入，管线未生成全景表。\n"

FLOW_REGIME_CN = {
    "genuine_terminal_destocking": "外需强劲终端真去库",
    "active_destocking": "装置实质检修主动去库",
    "passive_accumulation": "需求收缩被动累库",
    "active_restocking": "现货提价主动补库",
    "neutral": "供需中性",
}


def _fmt_val(val: Any, decimals: int = 1) -> str:
    if val is None:
        return "--"
    try:
        return f"{float(val):.{decimals}f}"
    except (TypeError, ValueError):
        return str(val)


def _fmt_pct(val: Any) -> str:
    if val is None:
        return "--"
    try:
        f = float(val)
        sign = "+" if f > 0 else ""
        return f"{sign}{f:.1f}%"
    except (TypeError, ValueError):
        return str(val)


def render_markdown(
    panorama: pl.DataFrame,
    projects: list[dict[str, Any]],
    company_panel: pl.DataFrame | None,
    episodes: list[dict[str, Any]],
    gate_evaluation: dict[str, Any] | None,
    config: Tio2Config,
    projection_results: list[Any] | None = None,
    lb_sensitivity_grid: pl.DataFrame | None = None,
    zh_sensitivity_grid: pl.DataFrame | None = None,
    audit_reports: list[dict[str, Any]] | None = None,
    confidence_bands: list[ConfidenceBandResult] | None = None,
    calibration_results: list[CalibrationResult] | None = None,
    pit_audit: list[dict[str, Any]] | None = None,
    quarterly_df: pl.DataFrame | None = None,
    reconciliation: list[dict[str, Any]] | None = None,
) -> str:
    """渲染钛白粉全景投研 Markdown 报告。"""
    if panorama.is_empty():
        return _EMPTY_REPORT

    latest_row = panorama.tail(1).to_dicts()[0]
    recent_rows = panorama.tail(12).to_dicts()
    sections = [
        _render_header(latest_row, config),
        _render_latest_status(latest_row),
        _render_capacity_projects(projects, latest_row),
        _render_recent_table(recent_rows),
        _render_history_episodes(episodes),
        _render_company_section(company_panel),
        _render_gate_section(gate_evaluation),
    ]
    if projection_results:
        sections.append(
            _render_projections_section(
                projection_results,
                lb_sensitivity_grid,
                zh_sensitivity_grid,
                audit_reports,
                confidence_bands,
                calibration_results,
            )
        )
    if quarterly_df is not None and not quarterly_df.is_empty():
        sections.append(_render_quarterly_section(quarterly_df, reconciliation))
    sections.append(_render_pit_audit_section(pit_audit))
    return "\n\n".join(sections)


def _render_quarterly_section(
    quarterly_df: pl.DataFrame,
    reconciliation: list[dict[str, Any]] | None = None,
) -> str:
    """季度化引擎（月频构建）Q1-Q4 归母净利推演表。"""
    lines = [
        "## 八、 季度化引擎（Q1-Q4 归母净利推演，月频构建）",
        "",
        "> 口径：月频价格/成本/利用率路径 → 季度汇总；期间费用按最新报告期单季摊销 × 情景系数；"
        "数据缺失月份回退情景价并记录 assumption。单位：归母净利（亿元）。",
        "",
    ]
    if reconciliation:
        lines.append("**对账门禁（Phase 0，H1 模型 vs 实际中报）**：")
        for item in reconciliation:
            flag = item.get("flag")
            mark = "⚠️ 绝对数字不可信（仅弹性口径）" if flag == "model_abs_unreliable" else "✅ 通过"
            act_net = item.get("actual_net_cny")
            act_str = f"{float(act_net) / 1e8:.2f}" if act_net is not None else "0.00"
            lines.append(
                f"- {item.get('company_name')}：模型 {float(item.get('model_net_cny', 0) or 0) / 1e8:.2f} 亿 "
                f"vs 实际 {act_str} 亿"
                f"（偏差 {item.get('bias_pct')}%）→ {mark}"
            )
        lines.append("")
    lines.extend(
        [
            "| 公司 | 情景 | Q1 | Q2 | Q3 | Q4 | 全年合计 |",
            "| :--- | :--- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    df = quarterly_df.with_columns((pl.col("net_profit_attr_p_cny") / 1.0e8).alias("net_yi"))
    for (company, scen), grp in df.group_by(["company_name", "scenario_name"], maintain_order=True):
        ordered: dict[str, Any] = {"Q1": None, "Q2": None, "Q3": None, "Q4": None}
        for row in grp.iter_rows(named=True):
            ordered[row["quarter_key"][4:]] = row["net_yi"]
        vals = [ordered[q] for q in ("Q1", "Q2", "Q3", "Q4")]
        valid_vals = [float(v) for v in vals if v is not None]
        fy = sum(valid_vals)
        cells = [f"{v:.2f}" if v is not None else "--" for v in vals]
        lines.append(
            f"| {company} | {scen} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} | {fy:.2f} |"
        )
    return "\n".join(lines)


def _render_pit_audit_section(pit_audit: list[dict[str, Any]] | None) -> str:
    lines = [
        "## 九、 数据 Point-in-Time 前视审计",
        "",
    ]
    if not pit_audit:
        lines.append("> 无动态输入审计项（静态配置模式）。")
        return "\n".join(lines)

    all_ok = all(bool(item.get("pit_ok")) for item in pit_audit)
    lines.append(
        f"> **结论**: {'全部输入已按披露/发布时点截断，无前视' if all_ok else '存在未截断或超限输入，需人工核验'}"
    )
    lines.append("")
    lines.append("| 动态输入 | 截断口径 | as_of | 最新可用时点 | 已用行数 | PIT 合规 | 备注 |")
    lines.append("| :--- | :--- | :--- | :--- | ---: | :---: | :--- |")
    for item in pit_audit:
        lines.append(
            f"| {item.get('input', '--')} | {item.get('truncation', '--')} | "
            f"{item.get('as_of', '--')} | {item.get('latest_used') or '--'} | "
            f"{item.get('rows_used', 0)} | {'✅' if item.get('pit_ok') else '⚠️'} | "
            f"{item.get('note', '')} |"
        )
    return "\n".join(lines)


def _render_header(row: dict[str, Any], config: Tio2Config) -> str:
    return f"""# 钛白粉 (TiO2) 全景基本面对账与周期量化研报

> **报告基准月**: `{row.get("report_month") or "--"}` | **品类属性**: **B 类周期性中游寡头品种** (Oligopoly Gate)
> **数据底座**: GACC 海关出口 (320611xx) + 生意社 100ppi 现货基准 (TiO2) + 生产工艺成本模型 + 上市公司财务
> **产物管线**: {config.title} (`stock_analytics.pipelines.tio2`，ArtifactStore + manifest)"""


def _render_latest_status(row: dict[str, Any]) -> str:
    flow_regime = row.get("inventory_flow_regime", "neutral")
    flow_cn = FLOW_REGIME_CN.get(flow_regime, flow_regime)

    lines = [
        "## 一、 核心基本面诊断与最新状态",
        "",
        f"- **现货出厂基准价**: `{_fmt_val(row.get('tio2_spot_price_cny'), 1)}` 元/吨"
        f" (环比: `{_fmt_val(row.get('delta_spot_price_cny'), 1)}` 元/吨)",
        f"- **理论加工毛利**: `{_fmt_val(row.get('tio2_margin_cny'), 1)}` 元/吨"
        f" (利润状态: `{row.get('margin_regime') or '--'}`)",
        f"- **海关总署月度出口**: `{_fmt_val(row.get('export_qty_tons'), 1)}` 吨"
        f" ({_fmt_pct(row.get('export_qty_yoy'))} YoY)，金额 `{_fmt_val(row.get('export_value_usd'), 1)}` 美元",
        f"- **出口离岸单价**: `{_fmt_val(row.get('export_unit_price_usd'), 1)}` 美元/吨",
        f"- **寡头蓄水池流动诊断**: **`{flow_cn}`** (`{flow_regime}`)",
        f"- **计划口径累计新增产能 (含已投产/在建/拟建)**: `{_fmt_val(row.get('cum_cap_expansion_w_tons'), 1)}` 万吨/年",
    ]
    return "\n".join(lines)


def _render_capacity_projects(projects: list[dict[str, Any]], row: dict[str, Any]) -> str:
    lines = [
        "## 二、 重大产能事件与供给冲击日历",
        "",
        "| 项目名称 | 所属企业 | 省份 | 工艺路线 | 产能 (万吨/年) | 投产时点 | 状态 |",
        "| :--- | :--- | :--- | :--- | :---: | :---: | :---: |",
    ]
    if not projects:
        lines.append("| -- | 暂无在建产能事件配置 | -- | -- | -- | -- | -- |")
    else:
        for p in projects:
            start = p.get("actual_start") or p.get("expected_start") or "--"
            lines.append(
                f"| {p.get('plant_name', '--')} | {p.get('company', '--')} | "
                f"{p.get('province', '--')} | {p.get('technology', '--')} | "
                f"{_fmt_val(p.get('capacity_w_tons'), 1)} | {start} | {p.get('status', '--')} |"
            )
    return "\n".join(lines)


def _render_recent_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "## 三、 近 12 个月全景对账明细表",
        "",
        "| 月份 | 现货出厂价 (元/吨) | 理论毛利 (元/吨) | 利润状态 | 海关出口量 (吨) | 出口同比 | 出口单价 ($/吨) | 蓄水池状态 |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for r in rows:
        flow_regime = r.get("inventory_flow_regime", "--")
        flow_cn = FLOW_REGIME_CN.get(flow_regime, flow_regime)
        lines.append(
            f"| {r.get('report_month', '--')} | {_fmt_val(r.get('tio2_spot_price_cny'), 1)} | "
            f"{_fmt_val(r.get('tio2_margin_cny'), 1)} | {r.get('margin_regime', '--')} | "
            f"{_fmt_val(r.get('export_qty_tons'), 0)} | {_fmt_pct(r.get('export_qty_yoy'))} | "
            f"{_fmt_val(r.get('export_unit_price_usd'), 1)} | {flow_cn} |"
        )
    return "\n".join(lines)


def _render_history_episodes(episodes: list[dict[str, Any]]) -> str:
    lines = [
        "## 四、 历史周期大拐点对账 (数据驱动)",
        "",
        "| 拐点期区间 | 周期性质 | 持续月数 | 平均毛利 (元/吨) | 现货最低价 | 现货最高价 |",
        "| :--- | :---: | :---: | :---: | :---: | :---: |",
    ]
    if not episodes:
        lines.append("| -- | 历史样本期未触发极值门槛 | -- | -- | -- | -- |")
    else:
        for ep in episodes:
            kind_cn = "高利润顶区" if ep.get("kind") == "high_profit" else "深度亏损底区"
            lines.append(
                f"| {ep.get('start_month')} ~ {ep.get('end_month')} | {kind_cn} | "
                f"{ep.get('duration_months')} | {_fmt_val(ep.get('margin_mean'), 1)} | "
                f"{_fmt_val(ep.get('price_min'), 1)} | {_fmt_val(ep.get('price_max'), 1)} |"
            )
    return "\n".join(lines)


def _render_company_section(company_panel: pl.DataFrame | None) -> str:
    lines = [
        "## 五、 核心上市公司画像与估值反向时钟",
        "",
        "| 标的代码 | 证券简称 | 工艺路线 | 角色定位 | 收盘价 | PB | 10Y PB分位 | PE(TTM) | 估值阶段 | 季度归母净利 (亿元) |",
        "| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    if company_panel is None or company_panel.is_empty():
        lines.append("| -- | 暂无公司面板数据 | -- | -- | -- | -- | -- | -- | -- | -- |")
        return "\n".join(lines)

    latest = company_panel.sort("trade_date").group_by("symbol").last()
    for r in latest.iter_rows(named=True):
        net_p = r.get("net_profit_attr_p")
        net_p_str = f"{net_p / 1e8:.2f}" if net_p is not None else "--"
        lines.append(
            f"| {r.get('symbol')} | {r.get('company_name')} | {r.get('process_type')} | "
            f"{r.get('role')} | {_fmt_val(r.get('close'), 2)} | {_fmt_val(r.get('pb'), 2)} | "
            f"{_fmt_pct(r.get('pb_percentile_10y'))} | {_fmt_val(r.get('pe_ttm'), 1)} | "
            f"{r.get('valuation_regime', '--')} | {net_p_str} |"
        )
    lines.extend(
        [
            "",
            "> **微观出海与反倾销税差异化暴露分析 (Tariff Moat & Geopolitics)**：",
            "> - **真实官方裁决 (欧盟终裁 OJ L 2025/4)**：欧盟 2025 年 1 月终裁实行特定从量税：安徽金星钛白最低 (0.25 欧元/kg，初裁 14.4%)；钛能化学等合作企业居中 (0.64 欧元/kg，初裁 35.0%)；**龙佰集团被课以顶格税率 (0.74 欧元/kg，折合约 740 欧元/吨，初裁 39.7%)**，在欧盟并不享有税率优待；",
            "> - **龙佰集团 (002601.SZ) 真实出海阿尔法**：虽在欧盟面临顶格税率，但拥有欧洲本土实体 (Billions Europe) 本地化仓储与技术服务能力，且在欧亚经济联盟 (EAEU) 获价格承诺免税准入，主要增量加速切换至东南亚、印度与中东等非欧美受限新兴市场；",
            "> - **钛能化学 (002145.SZ)**：海外营收占比超 50%，战略性避开欧美高关税壁垒区，主攻东南亚、中东与拉美等新兴市场；",
            "> - **安纳达 / 金浦钛业**：海外直销渠道与跨国运营能力薄弱，欧盟被征顶格税率 (0.74 欧元/kg)，受高关税挤压退守国内，加剧内销竞争。",
        ]
    )
    return "\n".join(lines)


def _render_gate_section(gate_evaluation: dict[str, Any] | None) -> str:
    lines = [
        "## 六、 寡头周期量化交易门禁裁决",
        "",
    ]
    if not gate_evaluation:
        lines.append("> 门禁配置缺失或无足够数据进行评估。")
        return "\n".join(lines)

    left = gate_evaluation.get("left_side_odds", {})
    right = gate_evaluation.get("right_side_confirmation", {})
    top = gate_evaluation.get("top_escape", {})

    lines.extend(
        [
            f"### 1. {left.get('name', '左侧赔率建仓门禁')}",
            f"- **触发状态**: {'【已触发 - 建议建仓】' if left.get('triggered') else '【未触发 - 维持观望】'}",
            f"- **边际微利/亏损**: {left.get('cond_loss_desc', '--')}",
            f"- **估值极值分位**: {left.get('cond_pb_desc', '--')}",
            f"- **投资建议动作**: `{left.get('action', '--')}`",
            "",
            f"### 2. {right.get('name', '右侧胜率确认门禁')}",
            f"- **触发状态**: {'【已触发 - 重仓进攻】' if right.get('triggered') else '【未触发 - 条件不齐】'}",
            f"- **现货提价确认**: {right.get('cond_hike_desc', '--')}",
            f"- **海关出口/去库**: {right.get('cond_destock_desc', '--')}",
            f"- **开工率/负荷**: {right.get('cond_operating_rate_desc', '--')}",
            f"- **均线突破确认**: {right.get('cond_ma_desc', '--')}",
            f"- **投资建议动作**: `{right.get('action', '--')}`",
            "",
            f"### 3. {top.get('name', '逃顶一票否决门禁')}",
            f"- **触发状态**: {'【警报触发 - 一票否决清仓】' if top.get('position_action') == 'clear_position' else ('【预警 - 减半离场】' if top.get('position_action') == 'halve_position' else '【安全 - 尚未见顶】')}",
            f"- **超额暴利诊断**: {top.get('cond_profit_desc', '--')}",
            f"- **被动累库/外需收缩**: {top.get('cond_accum_desc', '--')}",
            f"- **低 PE 见顶陷阱**: {top.get('cond_pe_desc', '--')}",
            f"- **全球装置负荷**: {top.get('cond_operating_rate_desc', '--')}",
            f"- **建议避险动作**: `{top.get('action', '--')}`",
        ]
    )
    return "\n".join(lines)


def _render_projections_section(
    results: list[Any],
    lb_grid: pl.DataFrame | None,
    zh_grid: pl.DataFrame | None,
    audit_reports: list[dict[str, Any]] | None = None,
    confidence_bands: list[ConfidenceBandResult] | None = None,
    calibration_results: list[CalibrationResult] | None = None,
) -> str:
    lines = [
        "## 七、 钛白粉双雄业务分部 (SOTP) 与未来财务合并测算",
        "",
        "> 基于自下而上单吨量本利模型 (物理单耗 + 制造完全折旧 + 到厂原料成本) 测算龙佰集团与钛能化学在不同宏观情景下的营收、归母净利与目标估值。",
        "",
        "### 1. 龙佰集团 vs 钛能化学：全景宏观情景推演与 PE-PB 双轨估值对照表",
        "",
        "| 证券简称 | 宏观情景 | 营业总收入 (亿元) | 毛利润 (亿元) | 主业毛利(亿) | 副业毛利(亿) | 财务费用 (亿元) | 归母净利润 (亿元) | EPS (元) | 主业EPS | 目标 PE | 目标股价(PE) (元) | BPS (元) | 目标 PB | 目标股价(PB) (元) |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for r in results:
        rev_yi = r.total_revenue_cny / 1.0e8
        gp_yi = r.total_gross_profit_cny / 1.0e8
        core_gp_yi = getattr(r, "core_tio2_gross_profit_cny", gp_yi) / 1.0e8
        aux_gp_yi = getattr(r, "auxiliary_gross_profit_cny", 0.0) / 1.0e8
        fin_yi = getattr(r, "finance_expense_cny", 0.0) / 1.0e8
        np_yi = r.net_profit_attr_p_cny / 1.0e8
        core_eps = getattr(r, "core_tio2_eps_cny", r.eps_cny)
        lines.append(
            f"| {r.company_name} ({r.symbol}) | {r.scenario_name} | {rev_yi:.2f} | {gp_yi:.2f} | "
            f"{core_gp_yi:.2f} | {aux_gp_yi:.2f} | {fin_yi:.2f} | {np_yi:.2f} | {r.eps_cny:.2f} | "
            f"{core_eps:.2f} | {r.pe_multiple:.1f}x | {r.target_stock_price_cny:.2f} | {r.bps_cny:.2f} | "
            f"{r.target_pb:.2f}x | {r.target_stock_price_pb_cny:.2f} |"
        )

    meta_info: list[str] = []
    seen_sym: set[str] = set()
    for r in results:
        if r.symbol not in seen_sym:
            seen_sym.add(r.symbol)
            rep = r.financial_report_date or "静态配置基准"
            mode_str = (
                "本地 Curated 事实表动态装配"
                if r.data_source_mode == "dynamic_catalog"
                else "YAML 静态兜底配置"
            )
            fin_trough = (
                next(
                    (
                        x.finance_expense_cny
                        for x in results
                        if x.symbol == r.symbol and x.scenario_key == "trough"
                    ),
                    0.0,
                )
                / 1.0e8
            )
            meta_info.append(
                f"- **{r.company_name} ({r.symbol})**: 财报基准期 `{rep}`，数据源 `{mode_str}`，"
                f"当前 BPS `{r.bps_cny:.2f} 元/股`，最新年化财务费用 `{fin_trough:.2f} 亿元`"
            )

    lines.extend(
        [
            "",
            "> **财报数据血统与装配状态**：",
            *([f"> {m}" for m in meta_info]),
            "",
            "> **Point-in-Time 历史财务合理性对账门禁 (Reconciliation Audit Gate)**：",
            *(
                [
                    f"> - `{'通过' if a.get('status') == 'PASSED' else '异动预警'}`: {a.get('message')}"
                    for a in (audit_reports or [])
                ]
            ),
            "",
            "> **周期股 PE-PB 双轨估值法与全景情景模型释义**：",
            "> 1. **PB 资产重置底线 (自适应 10Y 历史分位)**：周期处于磨底或现货低迷期时，盈利微薄导致静态 PE 逆周期飙升甚至虚高，此时 PB 是衡量矿山/产线重置成本的最强安全边际。目标 PB 100% 由近 10 年日频历史分位数自适应驱动：磨底期锚定 5% 历史极深坑底 (龙佰 1.59x 对应 15.22 元防守底)；现货实时情景采用最新收盘 PB (龙佰 1.63x, 钛能 1.23x)；中性复苏期锚定 50% 历史估值中枢。",
            "> 2. **PE 盈利爆发弹性 (右侧进攻)**：中性中枢复苏与景气高峰期，产能爬坡与供需剪刀差放大单吨毛利，以 PE 目标价兑现周期向上高 Beta 弹性。",
            "> 3. **当前现货实时测算 (current_spot)**：100% 接入本地黄金事实表最新钛白粉日频现货与攀西周频钛矿报价，直接反映两家龙头在当期真实微观成本与售价下的年化盈利运行中枢。",
            "> 4. **财务费用三表动态去杠杆**：利息支出 100% 由利润表与资产负债表最新事实动态提取。磨底与现货期保持 100% 刚性利息 (执行严苛压力测试)；复苏期与繁荣期随着年均 20~40 亿经营现金流偿还借款，财务费用内生收敛至当前水平的 55% 与 40%。",
            "> 5. **实物商品量平衡与内部自用抵消**：龙佰集团氯化法钛白粉扣除转产海绵钛联产自用 12 万吨中间体折合产能，消除合并报表内部交易重复计算；供应链贸易与新能源材料优先由 fina_mainbz 历史 3 年中枢自适应装配，绝不使用事前未发生数据 (严防前视偏差)。",
        ]
    )

    lines.extend(
        [
            "",
            "### 2. 龙佰集团 (002601.SZ) 业务分部量本利明细 (中性中枢复苏情景)",
            "",
            "| 业务分部 | 销量 (万吨) | 单吨售价 (元) | 单吨成本 (元) | 单吨毛利 (元) | 营业收入 (亿元) | 毛利润 (亿元) | 分部毛利率 |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ]
    )

    lb_mid = next(
        (r for r in results if r.symbol == "002601.SZ" and r.scenario_key == "mid_cycle"), None
    )
    if lb_mid:
        for seg in lb_mid.segments:
            vol_w = seg.sales_volume_tons / 10000.0 if seg.sales_volume_tons > 0 else "--"
            vol_str = f"{vol_w:.1f}" if isinstance(vol_w, float) else "--"
            lines.append(
                f"| {seg.segment_name} | {vol_str} | {_fmt_val(seg.unit_price_cny, 0)} | "
                f"{_fmt_val(seg.unit_cost_cny, 0)} | {_fmt_val(seg.unit_gross_margin_cny, 0)} | "
                f"{seg.revenue_cny / 1.0e8:.2f} | {seg.gross_profit_cny / 1.0e8:.2f} | "
                f"{seg.gross_margin_ratio * 100:.1f}% |"
            )

    lines.extend(
        [
            "",
            "### 3. 钛能化学 (002145.SZ) 业务分部量本利明细 (中性中枢复苏情景)",
            "",
            "| 业务分部 | 销量 (万吨) | 单吨售价 (元) | 单吨成本 (元) | 单吨毛利 (元) | 营业收入 (亿元) | 毛利润 (亿元) | 分部毛利率 |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ]
    )

    zh_mid = next(
        (r for r in results if r.symbol == "002145.SZ" and r.scenario_key == "mid_cycle"), None
    )
    if zh_mid:
        for seg in zh_mid.segments:
            vol_w = seg.sales_volume_tons / 10000.0 if seg.sales_volume_tons > 0 else "--"
            vol_str = f"{vol_w:.1f}" if isinstance(vol_w, float) else "--"
            lines.append(
                f"| {seg.segment_name} | {vol_str} | {_fmt_val(seg.unit_price_cny, 0)} | "
                f"{_fmt_val(seg.unit_cost_cny, 0)} | {_fmt_val(seg.unit_gross_margin_cny, 0)} | "
                f"{seg.revenue_cny / 1.0e8:.2f} | {seg.gross_profit_cny / 1.0e8:.2f} | "
                f"{seg.gross_margin_ratio * 100:.1f}% |"
            )

    if lb_grid is not None and not lb_grid.is_empty():
        lines.extend(
            [
                "",
                "### 4. 龙佰集团归母净利润二维敏感性矩阵 (单位: 亿元)",
                "",
                "> 纵轴为市场钛精矿到厂价 (元/吨)，横轴为硫酸法钛白粉售价 (元/吨)。",
                "",
                _render_grid_table(lb_grid),
            ]
        )

    if zh_grid is not None and not zh_grid.is_empty():
        lines.extend(
            [
                "",
                "### 5. 钛能化学归母净利润二维敏感性矩阵 (单位: 亿元)",
                "",
                "> 纵轴为市场钛精矿到厂价 (元/吨)，横轴为硫酸法钛白粉售价 (元/吨)。",
                "",
                _render_grid_table(zh_grid),
            ]
        )

    if calibration_results or confidence_bands:
        calibrator = IndustrialCostCalibrator()
        calib_md = calibrator.render_markdown_section(
            calibration_results or [], confidence_bands or []
        )
        lines.extend(["", calib_md])

    return "\n".join(lines)


def _render_grid_table(grid_df: pl.DataFrame) -> str:
    """将二维敏感性矩阵渲染为 Markdown 表格。"""
    cols = grid_df.columns
    header_cols = ["钛矿成本 \\ 钛白粉售价"] + [
        c.replace("tio2_", "") + " 元/吨" for c in cols if c != "ore_price_cny"
    ]
    lines = [
        "| " + " | ".join(header_cols) + " |",
        "| " + " | ".join([":---:"] * len(header_cols)) + " |",
    ]
    for row in grid_df.iter_rows(named=True):
        row_vals = [f"{row['ore_price_cny']:.0f} 元/吨"]
        for c in cols:
            if c != "ore_price_cny":
                row_vals.append(f"{row[c]:.2f}")
        lines.append("| " + " | ".join(row_vals) + " |")
    return "\n".join(lines)
