"""宏观风控双轨制雷达：研报评级分段、图标与定性建议业务逻辑。

所有阈值分段、图标与话术均优先从 `config/reporting/macro_risk_thresholds.yaml` 加载，
实现投研文案与 Python 代码层彻底解耦。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from stock_reporting.interpretation.macro_risk.config import (
    grade_dim,
    index_threshold,
    load_reporting_config,
    safe_float,
)
from stock_reporting.interpretation.macro_risk.dispersion import build_component_dispersion
from stock_reporting.interpretation.macro_risk.position_hint import dd_position_hint


def evaluate_macro_risk(
    row: dict[str, Any],
    config_path: Path | str | None = None,
    dd_from_high: float | None = None,
) -> dict[str, Any]:
    """根据当日指标快照生成多维风险评级与投研建议。

    Args:
        row: 当日因子快照（含 overheat_index / panic_index / dim_* 等）。
        config_path: 研报阈值配置路径。
        dd_from_high: 基准距前 120 交易日高点回撤（负值，如 -0.08 = 距高点跌 8%）。
            用于在恐慌极值时提示「市场位置」风险（深底/中继/高位假冰点）。
    """
    cfg = load_reporting_config(config_path)

    def _get(k: str) -> float | None:
        return safe_float(row.get(k)) if row.get(k) is not None else None

    overheat = _get("overheat_index")
    panic = _get("panic_index")
    crowding = _get("dim_crowding")

    val_valuation = _get("dim_valuation")
    val_leverage = _get("dim_leverage")
    val_crowding = _get("dim_crowding")
    val_flow = _get("dim_flow")
    val_sentiment = _get("dim_fear")
    val_breadth = _get("dim_breadth")
    val_smart_score = _get("smart_money_pct")
    val_div_score = _get("divergence_score")
    val_corporate = _get("dim_corporate")
    val_insider_net = _get("insider_net_score")
    val_insider_sell = _get("insider_sell_score")
    val_unlock = _get("unlock_amount_score")
    val_repurchase = _get("repurchase_score")
    val_cross_asset = _get("dim_cross_asset")

    overheat_critical = index_threshold(cfg, "overheat", "threshold_critical", 65.0)
    overheat_warning = index_threshold(cfg, "overheat", "threshold_warning", 60.0)
    panic_critical = index_threshold(cfg, "panic", "threshold_critical", 70.0)
    panic_warning = index_threshold(cfg, "panic", "threshold_warning", 60.0)
    crowding_split = index_threshold(cfg, "panic", "crowding_split", 45.0)
    corp_pressure_low_th = index_threshold(cfg, "panic", "corp_pressure_low", 25.0)
    corp_pressure_high_th = index_threshold(cfg, "panic", "corp_pressure_high", 75.0)
    buyback_support_th = index_threshold(cfg, "panic", "buyback_support", 30.0)
    buyback_absent_th = index_threshold(cfg, "panic", "buyback_absent", 70.0)
    smart_support_th = index_threshold(cfg, "panic", "smart_support", 80.0)
    smart_observe_th = index_threshold(cfg, "panic", "smart_observe", 40.0)
    insider_sell_high = index_threshold(cfg, "overheat", "insider_sell_high", 75.0)
    unlock_high = index_threshold(cfg, "overheat", "unlock_high", 80.0)
    divergence_evidence = index_threshold(cfg, "overheat", "divergence_evidence", 70.0)
    turnover_evidence = index_threshold(cfg, "overheat", "turnover_evidence", 85.0)

    # 双轨指数缺失 → fail-closed 判「数据暂缺」，不得静默落入「情绪平稳」
    if overheat is None or panic is None:
        status = "宏观指数数据暂缺 (无法评级)"
        level = "warning"
        scenario = "data_missing"
        advice = (
            "- **当前状态**：双轨指数（overheat / panic）数据缺失，无法生成风险评级。\n"
            "- **市场定性**：请先核对宏观风控管线产物完整性（manifest.data_completeness）。\n"
            "👉 **操作建议**：数据补齐前不依据本报告做仓位决策。"
        )
        empty_dims: dict[str, float] = {}
        return {
            "status": status,
            "level": level,
            "overheat_value": None,
            "panic_value": None,
            "top_driver": "数据暂缺",
            "top_driver_val": 0.0,
            "dimensions": empty_dims,
            "risk_tiers": [],
            "advice": advice,
            "scenario": scenario,
        }

    special_flow = {"div_score": val_div_score}

    s_lev, b_lev, d_lev = grade_dim("leverage", val_leverage, cfg)
    s_crw, b_crw, d_crw = grade_dim("crowding", val_crowding, cfg)
    s_flw, b_flw, d_flw = grade_dim("flow", val_flow, cfg, special_flow)
    s_sen, b_sen, d_sen = grade_dim("fear", val_sentiment, cfg)
    s_brd, b_brd, d_brd = grade_dim("breadth", val_breadth, cfg)
    s_val, b_val, d_val = grade_dim("valuation", val_valuation, cfg)
    s_corp, b_corp, d_corp = grade_dim("corporate", val_corporate, cfg)
    s_cross, b_cross, d_cross = grade_dim("cross_asset", val_cross_asset, cfg)

    # 成分分歧披露：维度分是成分分位均值，成分反向时均值会读成「中枢/平衡」
    dispersion = build_component_dispersion(row, cfg)
    disp_by_dim = {d["dim"]: d for d in dispersion}

    def _annotate(dim_key: str, desc: str) -> str:
        """在维度话术后追加成分极差，避免均值掩盖反向读数。"""
        info = disp_by_dim.get(dim_key)
        if info is None:
            return desc
        return (
            f"{desc} ⚠️ 成分极差 {info['spread']:.0f}："
            f"{info['low_label']} {info['low']:.0f} vs {info['high_label']} {info['high']:.0f}"
            "（合成分不代表成分一致）"
        )

    d_lev = _annotate("leverage", d_lev)
    d_crw = _annotate("crowding", d_crw)
    d_flw = _annotate("flow", d_flw)
    d_sen = _annotate("fear", d_sen)
    d_brd = _annotate("breadth", d_brd)
    d_val = _annotate("valuation", d_val)
    d_cross = _annotate("cross_asset", d_cross)

    corporate_reading = []
    if val_insider_net is not None:
        if val_insider_net >= 75.0:
            corporate_reading.append("内部人净买入偏弱")
        elif val_insider_net <= 25.0:
            corporate_reading.append("内部人净买入偏强")
    if val_insider_sell is not None:
        if val_insider_sell >= insider_sell_high:
            corporate_reading.append("减持压力偏高")
        elif val_insider_sell <= 25.0:
            corporate_reading.append("减持压力偏低")
    if val_unlock is not None:
        if val_unlock >= unlock_high:
            corporate_reading.append("解禁压力偏高")
        elif val_unlock <= 40.0:
            corporate_reading.append("解禁压力不突出")

    if corporate_reading:
        corporate_summary = "、".join(corporate_reading)
    else:
        corporate_summary = "增减持与解禁未见明显极端"

    if val_repurchase is not None and val_repurchase <= buyback_support_th:
        buyback_summary = "回购较活跃，是独立正向参考，不计入综合分"
    elif val_repurchase is not None and val_repurchase >= buyback_absent_th:
        buyback_summary = "回购偏弱，是独立参考，不计入综合分"
    else:
        buyback_summary = "回购未见明显异常，且不计入综合分"
    d_corp = f"近5年相对水平显示，{corporate_summary}；{buyback_summary}。"
    d_corp = _annotate("corporate", d_corp)

    risk_tiers = [
        {
            "name": "生存与毁灭级风险 (硬约束 / 强平与失速)",
            "metrics": [
                {
                    "name": "两融杠杆",
                    "code": "dim_leverage",
                    "val": val_leverage,
                    "status": s_lev,
                    "badge": b_lev,
                    "desc": d_lev,
                },
                {
                    "name": "换手拥挤",
                    "code": "dim_crowding",
                    "val": val_crowding,
                    "status": s_crw,
                    "badge": b_crw,
                    "desc": d_crw,
                },
                {
                    "name": "资金与筹码",
                    "code": "dim_flow",
                    "val": val_flow,
                    "status": s_flw,
                    "badge": b_flw,
                    "desc": d_flw,
                },
            ],
        },
        {
            "name": "拐点与博弈级信号 (快变量 / 情绪与超跌)",
            "metrics": [
                {
                    "name": "期权情绪",
                    "code": "dim_fear",
                    "val": val_sentiment,
                    "status": s_sen,
                    "badge": b_sen,
                    "desc": d_sen,
                },
                {
                    "name": "市场广度",
                    "code": "dim_breadth",
                    "val": val_breadth,
                    "status": s_brd,
                    "badge": b_brd,
                    "desc": d_brd,
                },
            ],
        },
        {
            "name": "长线估值与安全边际 (慢变量 / 空间)",
            "metrics": [
                {
                    "name": "大盘估值",
                    "code": "dim_valuation",
                    "val": val_valuation,
                    "status": s_val,
                    "badge": b_val,
                    "desc": d_val,
                },
                {
                    "name": "产业资本",
                    "code": "dim_corporate",
                    "val": val_corporate,
                    "status": s_corp,
                    "badge": b_corp,
                    "desc": d_corp,
                },
                {
                    "name": "跨资产宏观",
                    "code": "dim_cross_asset",
                    "val": val_cross_asset,
                    "status": s_cross,
                    "badge": b_cross,
                    "desc": d_cross,
                },
            ],
        },
    ]

    val_div = _get("divergence_score")
    val_turnover = _get("market_turnover_score")

    advice = ""
    scenario = "safe"
    if overheat >= overheat_critical and panic >= panic_critical:
        status = "双极值共振 —— 【高位杠杆踩踏 (严禁抄底)】"
        level = "danger"
        scenario = "dual_extreme"
        advice = (
            f"- **当前状态**：狂热指数 ({overheat:.1f}) 与 恐慌指数 ({panic:.1f}) 发生罕见双极值共振。\n"
            "- **市场定性**：存量杠杆与换手拥挤度极高，同时遭遇突发恐慌性广度承压。\n"
            "- **后续推演**：属于典型的杠杆多杀多破位初期，切勿将单日急跌误判为‘超跌黄金坑’，后续仍有被动平仓与连锁回撤风险。\n"
            "👉 **操作建议**：坚决逢反弹减仓，严禁在杠杆出清前左侧盲目加杠杆抄底；以生命线（20日均线）跌破为刚性止损线。"
        )
    elif overheat >= overheat_critical:
        has_top_divergence = (
            val_insider_sell is not None and val_insider_sell >= insider_sell_high
        ) or (val_unlock is not None and val_unlock >= unlock_high)
        extra_evidences = []
        if val_div is not None and val_div >= divergence_evidence:
            extra_evidences.append(f"资金与筹码博弈分歧度极高 ({val_div:.1f})，资金结构明显分化")
        if val_turnover is not None and val_turnover >= turnover_evidence:
            extra_evidences.append(
                f"全市场换手率触及天花板 ({val_turnover:.1f})，买盘进入物理耗尽区"
            )
        evidence_str = f"（核心证据：{'; '.join(extra_evidences)}）" if extra_evidences else ""

        if has_top_divergence:
            status = "极度狂热 —— 【高位产业资本出逃背离 (见顶预警)】"
            # 显示实际满足阈值条件的证据值：减持/解禁取「达标者」（避免显示未达阈值的一项误导读者）
            sell_parts = []
            if val_insider_sell is not None and val_insider_sell >= insider_sell_high:
                sell_parts.append(f"大股东减持 ({val_insider_sell:.1f})")
            if val_unlock is not None and val_unlock >= unlock_high:
                sell_parts.append(f"限售解禁 ({val_unlock:.1f})")
            sell_desc = "、".join(sell_parts) if sell_parts else "产业资本出逃"
            advice = (
                f"- **当前状态**：狂热指数 ({overheat:.1f}) 突破警戒线，{sell_desc}同步爆发{evidence_str}。\n"
                "- **市场定性**：产业资本与大股东密集套现兑现，形成高位资金结构背离。\n"
                "- **后续推演**：二级市场承接流动性正在被产业资本实质性抽干，主升浪已进入尾声，未来季度预期收益极大概率为负。\n"
                "👉 **操作建议**：严禁加杠杆追高；全面收紧止盈线，以生命线（20日均线）跌破为右侧退出开关，跌破坚决清仓进攻端退守国债/黄金避险。"
            )
        else:
            status = "极度狂热 (极高回撤风险)"
            advice = (
                f"- **当前状态**：狂热指数 ({overheat:.1f}) 已突破危险阈值{evidence_str}。\n"
                "- **市场定性**：全市场资金处于极度亢奋的“博傻”阶段。\n"
                "- **后续推演**：无论当前是否处于护盘期，未来一季度的预期收益极大概率为负。\n"
                "👉 **操作建议**：狂热区不盲目左侧猜顶，但严禁加杠杆追高；收紧止盈线，以生命线（20日均线）跌破为右侧退出开关，跌破坚决清仓进攻端。"
            )
        level = "danger"
        scenario = "overheat_extreme"
    elif panic >= panic_critical:
        val_rep_val = (
            safe_float(row.get("repurchase_score"))
            if row.get("repurchase_score") is not None
            else None
        )
        corp_pressure_low = val_corporate is not None and val_corporate <= corp_pressure_low_th
        corp_pressure_high = val_corporate is not None and val_corporate >= corp_pressure_high_th
        buyback_support = val_rep_val is not None and val_rep_val <= buyback_support_th
        buyback_absent = val_rep_val is not None and val_rep_val >= buyback_absent_th
        smart_money_support = val_smart_score is not None and val_smart_score >= smart_support_th
        partial_corp_support = corp_pressure_low or buyback_support
        strong_corp_support = corp_pressure_low and buyback_support
        buyback_only_support = buyback_support and not corp_pressure_low
        is_corp_absent = corp_pressure_high and (val_rep_val is None or buyback_absent)

        support_parts = []
        if corp_pressure_low:
            support_parts.append(f"产业资本综合压力低 ({val_corporate:.1f})")
        if buyback_support:
            support_parts.append(f"回购反向分位低 ({val_rep_val:.1f})，对应回购金额偏高")
        if smart_money_support:
            support_parts.append(f"聪明钱组合高分位 ({val_smart_score:.1f})")
        support_desc = "，".join(support_parts)

        pressure_parts = []
        if corp_pressure_high:
            pressure_parts.append(f"产业资本综合压力高 ({val_corporate:.1f})")
        if buyback_absent:
            pressure_parts.append(f"回购反向分位高 ({val_rep_val:.1f})，对应回购金额不足")
        pressure_desc = "，".join(pressure_parts) or "产业资本压力未见缓和"

        is_corp_lead = (
            val_smart_score is not None and val_smart_score < smart_observe_th and corp_pressure_low
        )

        if is_corp_lead:
            status = "极度恐慌 —— 【微观产业底抢跑 (产业压力缓和/回购高发)】"
            advice = (
                f"- **当前状态**：恐慌指数偏高 ({panic:.1f})，聪明钱组合尚在观望 ({val_smart_score:.1f})，但{support_desc}。\n"
                "- **市场定性**：产业资本压力先于宏观风险缓和，对部分细分行业估值底线形成初步支撑。\n"
                "- **后续推演**：微观基本面底部信号开始出现，但仍需价格与资金面确认。\n"
                "👉 **操作建议**：可左侧小步分批观察绩优蓝筹与红利资产，避免一次性重仓。"
            )
            level = "opportunity"
            scenario = "panic_corporate_lead"
        elif strong_corp_support or (corp_pressure_low and smart_money_support):
            status = "极度恐慌 —— 【产业托底真黄金坑 (低压力/回购共振底)】"
            advice = (
                f"- **当前状态**：恐慌指数突破危险阈值 ({panic:.1f})，同时{support_desc}。\n"
                "- **市场定性**：二级市场非理性情绪杀跌与产业资本低压力、回购高发或聪明钱接货形成共振。\n"
                "- **后续推演**：底部支撑明显增强，但仍需尊重趋势生命线，避免把反弹当作确定性反转。\n"
                "👉 **操作建议**：左侧分批配置大盘宽基与高股息红利，保留仓位纪律并等待均值回归。"
            )
            level = "opportunity"
            scenario = "panic_true_gold_pit"
        elif partial_corp_support:
            if buyback_only_support:
                corp_support_status = (
                    "产业资本综合压力仍高"
                    if corp_pressure_high
                    else "产业资本综合压力尚未降至低压区"
                )
                status = "极度恐慌 —— 【回购单项支撑 (产业压力未缓和/底部待确认)】"
                advice = (
                    f"- **当前状态**：恐慌指数突破危险阈值 ({panic:.1f})，{support_desc}，但{corp_support_status}。\n"
                    "- **市场定性**：回购提供局部缓冲，但不能等同于产业资本综合压力缓和，产业底尚未确认。\n"
                    "- **后续推演**：继续观察内部人减持、解禁压力、聪明钱与价格趋势是否同步改善。\n"
                    "👉 **操作建议**：只做小步分批观察，不把回购单项信号当作满仓抄底依据。"
                )
            else:
                status = "极度恐慌 —— 【产业资本低压力支撑 (底部信号待确认)】"
                advice = (
                    f"- **当前状态**：恐慌指数突破危险阈值 ({panic:.1f})，{support_desc}，但产业托底证据尚未形成强共振。\n"
                    "- **市场定性**：当前更接近产业资本压力缓和，而非已确认的大额回购托底。\n"
                    "- **后续推演**：下行压力有所缓冲，后续仍需观察回购、聪明钱与价格趋势是否继续确认。\n"
                    "👉 **操作建议**：只做小步分批低吸或观察，不把单一低压力信号当作满仓抄底依据。"
                )
            level = "opportunity"
            scenario = "panic_buyback_only" if buyback_only_support else "panic_partial_support"
        elif is_corp_absent:
            status = "极度恐慌 —— 【警惕多杀多中继 (产业压力高/假黄金坑)】"
            advice = (
                f"- **当前状态**：恐慌指数爆表 ({panic:.1f})，但{pressure_desc}。\n"
                "- **市场定性**：暴跌主要由场内杠杆爆仓与情绪踩踏造成，产业资本压力并未同步缓和。\n"
                "- **后续推演**：属于典型的流动性挤压中继，谨防单日反弹诱多，后续仍面临二次下探与多杀多连环风险。\n"
                "👉 **操作建议**：严禁盲目左侧加杠杆抄底；坚决以生命线（20日均线）为防线，未重新站上前保持防守或持有债金避险。"
            )
            level = "warning"
            scenario = "panic_false_gold_pit"
        elif crowding is None:
            # 换手拥挤度缺失（S1）：不得把缺失当作「冰点」给出重仓建议，fail-closed 披露数据缺口
            status = "极度恐慌 —— 【恐慌极值 (换手数据缺失)】"
            advice = (
                f"- **当前状态**：恐慌指数爆表 ({panic:.1f})，但换手拥挤度数据缺失，无法区分放量/缩量出清。\n"
                "- **市场定性**：恐慌极值成立，但缺换手维度佐证，底部形态判断置信度下降。\n"
                "- **后续推演**：恐慌极值后仍可能二次下探，需补数确认换手状态再下结论。\n"
                "👉 **操作建议**：不因恐慌极值直接重仓；先核对数据完整性，补数后按放量/缩量口径重新评级。"
            )
            level = "warning"
            scenario = "panic_crowding_missing"
        elif crowding > crowding_split:
            status = "极度恐慌 —— 【放量出清底】"
            advice = (
                f"- **当前状态**：恐慌爆表 ({panic:.1f})，且换手拥挤度偏高 ({crowding:.1f})。\n"
                "- **市场定性**：带血筹码疯狂出逃，典型的多杀多“爆仓出清”。\n"
                "- **后续推演**：通常呈 V 型反转，反弹极具爆发力，但短期余震剧烈。\n"
                "👉 **操作建议**：左侧分批建仓，切忌一次性打满，留足子弹。"
            )
            level = "opportunity"
            scenario = "panic_volume_bottom"
        else:
            status = "极度恐慌 —— 【缩量绝望底】"
            advice = (
                f"- **当前状态**：恐慌爆表 ({panic:.1f})，且换手拥挤度降至低位 ({crowding:.1f})。\n"
                "- **市场定性**：市场极度绝望，流动性枯竭，无人问津。\n"
                "- **后续推演**：历史上缩量恐慌底多为坚实底部，但“空间封死”类表述不作绝对化承诺。\n"
                "👉 **操作建议**：可分批配置宽基，仍需留足子弹，避免单日押注。"
            )
            level = "opportunity"
            scenario = "panic_shrink_bottom"

        # 恐慌极值的位置风险提示（识别「假冰点」）：见 position_hint.dd_position_hint
        if dd_from_high is not None:
            advice += dd_position_hint(dd_from_high, cfg)

    elif overheat >= overheat_warning:
        status = "局部过热 (随时可能见顶)"
        level = "warning"
        scenario = "overheat_warning"
        advice = (
            f"- **当前状态**：狂热指数较高 ({overheat:.1f})，资金博弈加剧。\n"
            "- **市场定性**：情绪高昂，随时面临流动性反噬。\n"
            "👉 **操作建议**：多头头寸停止追高，逐步锁定高位利润；以生命线（20日均线）为防守底线，跌破果断减仓退守红利。"
        )
    elif panic >= panic_warning:
        status = "恐慌蔓延 (进入左侧底部区域)"
        level = "warning"
        scenario = "panic_warning"
        advice = (
            f"- **当前状态**：恐慌情绪蔓延 ({panic:.1f})，部分资金开始踩踏。\n"
            "- **市场定性**：已进入非理性抛售的高赔率区间。\n"
            "👉 **操作建议**：停止杀跌，开始寻找被错杀的优质标的。"
        )
    else:
        status = "情绪平稳 (无明显宏观系统性风险)"
        level = "safe"
        advice = (
            "- **当前状态**：恐慌与狂热指数均处于正常区间。\n"
            "- **市场定性**：无系统性崩盘或报复性反弹的宏观驱动力。\n"
            "👉 **操作建议**：轻指数重结构，集中精力挖掘行业轮动机会。"
        )

    # 8 维画像；缺失维度剔除，避免 0.0 被误选为 top_driver。
    raw_dims = {
        "估值 (Valuation)": val_valuation,
        "杠杆 (Leverage)": val_leverage,
        "情绪 (Sentiment)": val_sentiment,
        "拥挤度 (Crowding)": crowding,
        "资金与筹码 (Flow)": val_flow,
        "市场广度 (Breadth)": val_breadth,
        "产业资本 (Corporate)": val_corporate,
        "跨资产宏观 (CrossAsset)": val_cross_asset,
    }
    dims: dict[str, float] = {k: v for k, v in raw_dims.items() if v is not None}
    top_dim = max(dims.items(), key=lambda x: x[1]) if dims else ("数据暂缺", 0.0)

    # 排版：操作建议从列表项中独立成段（前加空行），避免与「后续推演」挤在一行
    advice = advice.replace("\n👉 **操作建议**", "\n\n👉 **操作建议**")

    # 慢速顶背离闸门提醒：copper_gold/cb_price 中期高位接近「慢速减仓闸门」激活线。
    slow_gate = _slow_gate_alert(row, cfg)
    if slow_gate["status"] == "watch":
        advice = (
            f"- **⚡ 中期顶背离观测**：dim_slow **{slow_gate['dim_slow']:.0f}**"
            f"（cu {slow_gate['copper']:.0f} / cb {slow_gate['cb']:.0f}）已进入接近激活线"
            f"（{slow_gate['watch']:.0f}/{slow_gate['activate']:.0f}）；若继续上行越过 {slow_gate['activate']:.0f}，"
            f"`macro_slow_top_divergence_etf` 的慢速顶背离闸门将降权益封顶至 30%。可提前留意进攻仓位。\n"
            f"👉 **操作建议**：暂不动仓，但关注 cu/cb 高位能否回落的确认。\n\n" + advice
        )
    elif slow_gate["status"] == "active":
        advice = (
            f"- **🔴 中期顶背离闸门激活**：dim_slow **{slow_gate['dim_slow']:.0f}**"
            f"（cu {slow_gate['copper']:.0f} / cb {slow_gate['cb']:.0f}）已越界，权益封顶将至 30%"
            f"（`macro_slow_top_divergence_etf` 措置）。防守市主跌段回撤可收敛约 10pp。\n"
            f"👉 **操作建议**：尊重慢速顶背离纪律，不逆势加进攻仓。\n\n" + advice
        )

    return {
        "status": status,
        "level": level,
        "overheat_value": overheat,
        "panic_value": panic,
        "top_driver": top_dim[0],
        "top_driver_val": top_dim[1],
        "dimensions": dims,
        "risk_tiers": risk_tiers,
        "advice": advice,
        "scenario": scenario,
        "slow_gate": slow_gate,
        "component_dispersion": dispersion,
    }


def _slow_gate_alert(row: dict[str, Any], cfg: Any) -> dict[str, Any]:
    """慢速顶背离闸门提醒：由 copper_gold/cb_price 分位合成 dim_slow，判定观测/激活状态。

    状态口径（与策略 `MacroSlowTopDivergenceStrategy` 一致）：
    - ``active``：dim_slow >= activate → 闸门激活（权益封顶降至 gate_cap）；
    - ``watch``：watch <= dim_slow < activate → 接近激活线的提醒观测区；
    - ``idle``：其余（闸门释放/未接近）。
    因子列缺失或无分位时 fail-closed 为 idle（数据缺失不预警）。
    """
    copper = safe_float(row.get("copper_gold_score"))
    cb = safe_float(row.get("cb_price_score"))
    gate_cfg = (
        (cfg.get("indices") or {}).get("slow_top_divergence") if isinstance(cfg, dict) else None
    )
    activate = (
        float(gate_cfg.get("activate", 80.0))
        if gate_cfg and isinstance(gate_cfg.get("activate"), int | float)
        else 80.0
    )
    watch = (
        float(gate_cfg.get("watch", 70.0))
        if gate_cfg and isinstance(gate_cfg.get("watch"), int | float)
        else 70.0
    )
    base = {
        "copper": copper,
        "cb": cb,
        "dim_slow": None,
        "activate": activate,
        "watch": watch,
        "status": "idle",
    }
    if copper is None or cb is None:
        return base
    dim_slow = (copper + cb) / 2.0
    base["dim_slow"] = round(dim_slow, 1)
    if dim_slow >= activate:
        base["status"] = "active"
    elif dim_slow >= watch:
        base["status"] = "watch"
    return base


__all__ = ["evaluate_macro_risk", "load_reporting_config"]
