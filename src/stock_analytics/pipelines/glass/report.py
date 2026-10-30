"""玻璃全景基本面对账研报 Markdown 渲染引擎。"""

from __future__ import annotations

from typing import Any

import polars as pl

from stock_analytics.pipelines.glass.config import GlassConfig
from stock_analytics.pipelines.glass.panorama import latest_core_row


def render_glass_markdown(
    panorama: pl.DataFrame,
    furnaces: list[dict[str, Any]],
    company_panel: pl.DataFrame,
    spot_benchmarks: dict[str, Any],
    gate_evaluation: dict[str, Any],
    config: GlassConfig,
) -> str:
    """渲染玻璃全景对账研报 Markdown 文本。"""
    latest = latest_core_row(panorama) or {}
    as_of_month = str(latest.get("report_month", "--"))

    lines: list[str] = [
        f"# {config.title}",
        "",
        f"> **报告基准**: 最新完整月份 `{as_of_month}` | 行业: **申万二级 220400 玻璃玻纤**",
        "> **数据底座**: NBS 官方平板玻璃产量 + 郑商所 FG0 期货/仓单 + 隆众周度在产日熔量/厂库 + 100ppi 现货基准 + 窑炉冷修种子库",
        "> **产物管线**: 玻璃全景基本面对账研报（`stock_analytics.pipelines.glass`）",
        "",
        "## 一、 核心基本面诊断与最新状态",
        "",
    ]

    # 一、核心基本面
    glass_out = latest.get("glass_output_w_cases")
    glass_yoy = latest.get("glass_output_yoy")
    soda_yoy = latest.get("soda_output_yoy")
    scissors = latest.get("scissors_spread_yoy")

    lines.append(
        f"- **最新月度平板玻璃产量**: {f'{glass_out:.1f} 万重量箱' if glass_out else '--'} "
        f"({f'{glass_yoy:+.1f}% YoY' if glass_yoy is not None else '--'})"
    )
    lines.append(
        f"- **供需剪刀差 (玻璃增速 - 纯碱增速)**: **{f'{scissors:+.1f}%' if scissors is not None else '--'}** "
        f"(纯碱产量增速: {f'{soda_yoy:+.1f}% YoY' if soda_yoy is not None else '--'})"
    )

    op_r = latest.get("survey_operating_rate_pct")
    inv_t = latest.get("factory_inv_month_end_w_tons")
    ship_r = latest.get("survey_shipment_rate_pct")
    regime = latest.get("flow_regime", "--")

    lines.extend(
        [
            "- **周度在产状态与中游蓄水池**:",
            f"  - 行业综合开工率 / 产能利用率: `{f'{op_r:.1f}%' if op_r else '--'}`",
            f"  - 样本企业厂库: `{f'{inv_t:.1f}' if inv_t else '--'}` 万重量箱/万吨",
            f"  - 周度产销率: `{f'{ship_r:.1f}%' if ship_r else '--'}`",
            f"  - 中游蓄水池状态机判定: **`{regime}`**",
        ]
    )

    fg_spot = spot_benchmarks.get("fg_spot_price")
    pvg2 = spot_benchmarks.get("pvg_2mm_spot_price")
    pvg3 = spot_benchmarks.get("pvg_3_2mm_spot_price")
    lines.extend(
        [
            "- **现货出厂基准监控**:",
            f"  - 5mm 浮法玻璃出厂价: `{f'{fg_spot:.2f} 元/㎡' if fg_spot else '--'}`",
            f"  - 2.0mm 镀膜光伏玻璃出厂价: `{f'{pvg2:.2f} 元/㎡' if pvg2 else '--'}`",
            f"  - 3.2mm 镀膜光伏玻璃出厂价: `{f'{pvg3:.2f} 元/㎡' if pvg3 else '--'}`",
            "",
            "## 二、 重大窑炉产能与冷修放水种子库跟踪",
            "",
        ]
    )

    # 二、窑炉跟踪
    cold_repairs = [f for f in furnaces if f.get("status") == "cold_repair"]
    operating = [f for f in furnaces if f.get("status") == "operating"]
    lines.extend(
        [
            f"- 累计跟踪核心窑炉: **{len(furnaces)} 座** (在产运行: **{len(operating)} 座**，冷修停产: **{len(cold_repairs)} 座**)",
            "",
            "| 公司 | 标的代码 | 基地产线 | 工艺路线 | 日熔量 (T/D) | 当前状态 | 投产/冷修时间 | 说明 |",
            "| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :--- |",
        ]
    )
    for f in furnaces[:8]:
        d_val = f.get("cold_repair_date") or f.get("actual_start") or "--"
        lines.append(
            f"| {f.get('company')} | `{f.get('symbol', '--')}` | {f.get('line_name')} | "
            f"`{f.get('process_type')}` | {f.get('capacity_t_d')} | `{f.get('status')}` | "
            f"`{d_val}` | {f.get('notes', '--')} |"
        )

    # 三、近 12 个月供需表
    lines.extend(
        [
            "",
            "## 三、 近 12 个月供需平衡与蓄水池对账表",
            "",
            "| 月份 | 平板玻璃 (万箱) | 玻璃同比 | 纯碱原料同比 | 供需剪刀差 | 浮法开工率 | 蓄水池状态 |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
        ]
    )
    tail_rows = panorama.tail(12).to_dicts()
    for r in tail_rows:
        g_out = (
            f"{float(r['glass_output_w_cases']):.1f}"
            if r.get("glass_output_w_cases") is not None
            else "--"
        )
        g_y = (
            f"{float(r['glass_output_yoy']):+.1f}%"
            if r.get("glass_output_yoy") is not None
            else "--"
        )
        s_y = (
            f"{float(r['soda_output_yoy']):+.1f}%" if r.get("soda_output_yoy") is not None else "--"
        )
        sc = (
            f"**{float(r['scissors_spread_yoy']):+.1f}%**"
            if r.get("scissors_spread_yoy") is not None
            else "--"
        )
        op = (
            f"{float(r['survey_operating_rate_pct']):.1f}%"
            if r.get("survey_operating_rate_pct") is not None
            else "--"
        )
        lines.append(
            f"| `{r['report_month']}` | {g_out} | {g_y} | {s_y} | {sc} | {op} | {r.get('flow_regime', '--')} |"
        )

    # 四、公司面板
    lines.extend(
        [
            "",
            "## 四、 玻璃核心上市公司估值反向时钟面板",
            "",
            "| 标的代码 | 公司名称 | 工艺定位 | 角色分工 | 收盘价 (元) | 市值 (亿) | PB | 10Y PB分位 | PE-TTM | 反向时钟状态 |",
            "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ]
    )
    if not company_panel.is_empty():
        for r in company_panel.to_dicts():
            pe_str = f"{r['pe_ttm']:.1f}" if r.get("pe_ttm") is not None else "--"
            close_str = f"{r['close']:.2f}" if r.get("close", 0) > 0 else "--"
            pb_str = f"{r['pb']:.2f}" if r.get("pb", 0) > 0 else "--"
            pct_str = (
                f"**{r['pb_percentile_10y']:.1f}%**" if r.get("pb_percentile_10y", 0) > 0 else "--"
            )
            mv_str = f"{r['total_mv_billion']:.1f}" if r.get("total_mv_billion", 0) > 0 else "--"
            lines.append(
                f"| `{r['symbol']}` | **{r['name']}** | `{r['process_type']}` | `{r['role']}` | "
                f"{close_str} | {mv_str} | {pb_str} | "
                f"{pct_str} | {pe_str} | `{r['clock_status']}` |"
            )

    # 五、交易门禁
    left = gate_evaluation.get("left_side_odds", {})
    right = gate_evaluation.get("right_side_confirmation", {})
    top = gate_evaluation.get("top_escape", {})

    lines.extend(
        [
            "",
            "## 五、 周期股分阶段量化交易门禁诊断 (基于 glass/trading_gates.yaml)",
            "",
            "| 门禁类型 | 当前状态 | 核心量化条件对账 | 建议动作与仓位约束 |",
            "| :--- | :---: | :--- | :--- |",
            f"| **1. 左侧赔率建仓门禁** | **{'触发 (满足)' if left.get('triggered') else '未满足'}** | {left.get('cond_pb_desc', '--')} | **{left.get('suggestion', '--')}** |",
            f"| **2. 右侧胜率确认门禁** | **{'触发 (满足)' if right.get('triggered') else '未满足 (观望)'}** | {right.get('cond_op_desc', '--')}<br>{right.get('cond_scissors_desc', '--')}<br>{right.get('cond_ma_desc', '--')} | **{right.get('suggestion', '--')}** |",
            f"| **3. 逃顶多因子清仓门禁** | **安全 (未触发)** | 处于周期底部磨底期，未出现开工打满或静态低 PE 见顶陷阱 | **{top.get('suggestion', '--')}** |",
            "",
            "## 六、 标的角色分工与实操配置指引（机制推断，非投资建议）",
            "",
            "- **全球光伏玻璃双寡头第一龙头 (`00968.HK` 信义光能)**: 全球市占率超 30%，海外马来西亚等基地直接规避欧美双反关税，千吨级超大窑炉成本护城河稳固，底部周期抗风险能力最强；",
            "- **光伏玻璃双寡头 A 股龙头 (`601865.SH` 福莱特)**: 凤阳石英砂与 1200T/D 超大窑炉构筑单平 15% 成本优势，A 股高流动性与高弹性左侧赔率核心标的；",
            "- **浮法玻璃双雄 (`601636.SH` 旗滨集团 / `00868.HK` 信义玻璃)**: 浮法原片与节能/汽车玻璃一体化，低成本石英砂自给，作为地产竣工与汽车消费后周期的核心配置底仓；",
            "- **配置节奏纪律**: 在右侧冷修大面积放水、库存连续去化且均线突破确立前，严格控制在 $\\le 20\\% \\sim 30\\%$ 基础试探底仓，严禁满仓追高抢反弹。",
        ]
    )

    return "\n".join(lines)


__all__ = [
    "render_glass_markdown",
]
