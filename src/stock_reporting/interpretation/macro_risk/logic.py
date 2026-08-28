from typing import Any


def evaluate_macro_risk(row: dict[str, Any]) -> dict[str, Any]:
    overheat = float(row.get("overheat_index", 0.0))
    panic = float(row.get("panic_index", 0.0))
    crowding = float(row.get("dim_crowding", 0.0))

    advice = ""
    # 按照绝对偏离度 (严重程度) 排序判定
    if overheat > 65:
        status = "极度狂热 (极高回撤风险)"
        level = "danger"
        advice = (
            f"- **当前状态**：狂热指数 ({overheat:.1f}) 已突破危险阈值。\n"
            "- **市场定性**：全市场资金处于极度亢奋的“博傻”阶段。\n"
            "- **后续推演**：无论当前是否处于护盘期，未来一季度的预期收益极大概率为负。\n"
            "👉 **操作建议**：坚决止盈，严禁加杠杆追高。"
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
            "👉 **操作建议**：多头头寸逐步止盈，控制仓位暴露。"
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
        "估值 (Valuation)": float(row.get("dim_valuation", 0.0)),
        "杠杆 (Leverage)": float(row.get("dim_leverage", 0.0)),
        "情绪 (Sentiment)": float(row.get("dim_sentiment", 0.0)),
        "拥挤度 (Crowding)": crowding,
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
        "advice": advice,
    }
