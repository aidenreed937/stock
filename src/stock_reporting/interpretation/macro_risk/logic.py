from typing import Any


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _grade_leverage(val: float | None) -> tuple[str, str, str]:
    if val is None:
        return "数据暂缺", "⚪", "历史数据不足"
    if val >= 85.0:
        return "极度高危", "🔴", "存量杠杆触顶，严防连环多杀多强平"
    if val >= 65.0:
        return "偏高警惕", "🟡", "杠杆资金积聚，容错空间收窄"
    if val <= 30.0:
        return "杠杆健康", "🟢", "场内杠杆处于低位，无踩踏风险"
    return "规模适中", "⚪", "杠杆水平处于正常区间"


def _grade_crowding(val: float | None) -> tuple[str, str, str]:
    if val is None:
        return "数据暂缺", "⚪", "历史数据不足"
    if val >= 85.0:
        return "严重过热", "🔴", "换手极度亢奋，短线买力濒临透支"
    if val >= 65.0:
        return "偏热过载", "🟡", "交易活跃度高，面临动量失速"
    if val <= 20.0:
        return "地量冰点", "🟢", "交投极度低迷，常对应坚实地量底"
    return "换手适中", "⚪", "交投活跃度处于正常区间"


def _grade_flow(
    val: float | None, etf_score: float | None = None, div_score: float | None = None
) -> tuple[str, str, str]:
    if val is None:
        return "数据暂缺", "⚪", "历史数据不足"
    if etf_score is not None and etf_score >= 90.0:
        return "国家队托底", "🟢", "宽基ETF获大额净申购托底，对冲现货抛压"
    if div_score is not None and div_score >= 85.0 and val is not None and val >= 65.0:
        return "主力派发", "🔴", "主力坚决流出且散户激进接盘，筹码严重背离"
    if val >= 80.0:
        return "坚决出逃", "🔴", "主力资金单向大幅净流出，防范真摔"
    if val >= 60.0:
        return "流出承压", "🟡", "主力资金持续净流出"
    if val <= 30.0:
        return "流入活跃", "🟢", "主力资金积极回流加仓"
    return "流向平衡", "⚪", "主力资金流向未见明显倾斜"


def _grade_sentiment(val: float | None) -> tuple[str, str, str]:
    if val is None:
        return "数据暂缺", "⚪", "历史数据不足"
    if val >= 80.0:
        return "极度恐慌", "🟢", "期权抢买Put避险，反向做多胜率极高"
    if val >= 60.0:
        return "恐慌升温", "🟡", "避险情绪上升，波动率放大"
    if val <= 20.0:
        return "极度自满", "🔴", "波动率降至冰点，警惕突发利空杀伤"
    return "情绪平稳", "⚪", "期权定价与避险情绪处于正常区间"


def _grade_breadth(val: float | None) -> tuple[str, str, str]:
    if val is None:
        return "数据暂缺", "⚪", "历史数据不足"
    if val >= 85.0:
        return "全面普跌", "🟡", "个股大面积破位，短期情绪宣泄充分"
    if val <= 20.0:
        return "全线普涨", "⚪", "赚钱效应扩散，涨多后警惕分化"
    return "结构均衡", "⚪", "涨跌家数与新高新低未现极端背离"


def _grade_valuation(val: float | None) -> tuple[str, str, str]:
    if val is None:
        return "数据暂缺", "⚪", "历史数据不足"
    if val >= 80.0:
        return "估值昂贵", "🔴", "ERP与PB处于高位，中长线期望空间压缩"
    if val >= 60.0:
        return "估值偏高", "🟡", "安全边际收窄，需业绩消化"
    if val <= 20.0:
        return "极度低估", "🟢", "安全边际极高，长线配置价值突出"
    return "估值合理", "⚪", "处于历史中位数水平"


def evaluate_macro_risk(row: dict[str, Any]) -> dict[str, Any]:
    overheat = _safe_float(row.get("overheat_index"))
    panic = _safe_float(row.get("panic_index"))
    crowding = _safe_float(row.get("dim_crowding"))

    val_valuation = (
        _safe_float(row.get("dim_valuation")) if row.get("dim_valuation") is not None else None
    )
    val_leverage = (
        _safe_float(row.get("dim_leverage")) if row.get("dim_leverage") is not None else None
    )
    val_crowding = (
        _safe_float(row.get("dim_crowding")) if row.get("dim_crowding") is not None else None
    )
    val_flow = _safe_float(row.get("dim_flow")) if row.get("dim_flow") is not None else None
    val_sentiment = (
        _safe_float(row.get("dim_sentiment")) if row.get("dim_sentiment") is not None else None
    )
    val_breadth = (
        _safe_float(row.get("dim_breadth")) if row.get("dim_breadth") is not None else None
    )

    val_etf_score = (
        _safe_float(row.get("etf_flow_ratio_score"))
        if row.get("etf_flow_ratio_score") is not None
        else None
    )
    val_div_score = (
        _safe_float(row.get("divergence_score_score"))
        if row.get("divergence_score_score") is not None
        else None
    )

    # Tiers grading
    s_lev, b_lev, d_lev = _grade_leverage(val_leverage)
    s_crw, b_crw, d_crw = _grade_crowding(val_crowding)
    s_flw, b_flw, d_flw = _grade_flow(val_flow, etf_score=val_etf_score, div_score=val_div_score)

    s_sen, b_sen, d_sen = _grade_sentiment(val_sentiment)
    s_brd, b_brd, d_brd = _grade_breadth(val_breadth)

    s_val, b_val, d_val = _grade_valuation(val_valuation)

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
                    "name": "主力资金",
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
                    "code": "dim_sentiment",
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
            ],
        },
    ]

    advice = ""
    # 按照绝对偏离度 (严重程度) 排序判定
    if overheat > 65 and panic > 65:
        status = "双极值共振 —— 【高位杠杆踩踏 (严禁抄底)】"
        level = "danger"
        advice = (
            f"- **当前状态**：狂热指数 ({overheat:.1f}) 与 恐慌指数 ({panic:.1f}) 发生罕见双极值共振。\n"
            "- **市场定性**：存量杠杆与换手拥挤度极高，同时遭遇突发恐慌性单日普跌踩踏。\n"
            "- **后续推演**：属于典型的杠杆多杀多破位初期，切勿将单日急跌误判为‘超跌黄金坑’，后续仍有被动平仓与连锁回撤风险。\n"
            "👉 **操作建议**：坚决逢反弹减仓，严禁在杠杆出清前左侧盲目加杠杆抄底；以 20 日均线 (MA20) 作为刚性止损防线。"
        )
    elif overheat > 65:
        status = "极度狂热 (极高回撤风险)"
        level = "danger"
        advice = (
            f"- **当前状态**：狂热指数 ({overheat:.1f}) 已突破危险阈值。\n"
            "- **市场定性**：全市场资金处于极度亢奋的“博傻”阶段。\n"
            "- **后续推演**：无论当前是否处于护盘期，未来一季度的预期收益极大概率为负。\n"
            "👉 **操作建议**：狂热区不盲目左侧猜顶，但严禁加杠杆追高；收紧止盈线，以 20 日均线 (MA20) 作为右侧刚性退出开关，一旦放量跌破 MA20 坚决清仓进攻端。"
        )
    elif panic > 65:
        if crowding > 45:
            status = "极度恐慌 —— 【放量出清底】"
            advice = (
                f"- **当前状态**：恐慌爆表 ({panic:.1f})，且换手拥挤度依然极高 ({crowding:.1f})。\n"
                "- **市场定性**：带血筹码疯狂出逃，典型的多杀多“爆仓出清”。\n"
                "- **后续推演**：通常呈 V 型反转，反弹极具爆发力，但短期余震剧烈。\n"
                "👉 **操作建议**：左侧分批建仓，切忌一次性打满，留足子弹。"
            )
        else:
            status = "极度恐慌 —— 【缩量绝望底】"
            advice = (
                f"- **当前状态**：恐慌爆表 ({panic:.1f})，且换手拥挤度降至冰点 ({crowding:.1f})。\n"
                "- **市场定性**：市场极度绝望，流动性枯竭，无人问津。\n"
                "- **后续推演**：最坚实的长线 U 型底，向下空间已被彻底封死。\n"
                "👉 **操作建议**：果断重仓配置宽基，无需精准择时，耐心锁仓。"
            )
        level = "opportunity"
    elif overheat > 55:
        status = "局部过热 (随时可能见顶)"
        level = "warning"
        advice = (
            f"- **当前状态**：狂热指数较高 ({overheat:.1f})，资金博弈加剧。\n"
            "- **市场定性**：情绪高昂，随时面临流动性反噬。\n"
            "👉 **操作建议**：多头头寸停止追高，逐步锁定高位利润；以 20 日均线 (MA20) 作为防守底线，破位果断减仓退守红利。"
        )
    elif panic > 55:
        status = "恐慌蔓延 (进入左侧底部区域)"
        level = "warning"
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

    dims = {
        "估值 (Valuation)": val_valuation if val_valuation is not None else 0.0,
        "杠杆 (Leverage)": val_leverage if val_leverage is not None else 0.0,
        "情绪 (Sentiment)": val_sentiment if val_sentiment is not None else 0.0,
        "拥挤度 (Crowding)": crowding,
        "主力资金 (Flow)": val_flow if val_flow is not None else 0.0,
        "市场广度 (Breadth)": val_breadth if val_breadth is not None else 0.0,
    }
    top_dim = max(dims.items(), key=lambda x: x[1]) if dims else ("未知", 0.0)

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
    }
