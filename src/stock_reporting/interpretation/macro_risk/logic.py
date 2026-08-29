"""宏观风控双轨制雷达：研报评级分段、图标与定性建议业务逻辑。

所有阈值分段、图标与话术均优先从 `config/reporting/macro_risk_thresholds.yaml` 加载，
实现投研文案与 Python 代码层彻底解耦。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from stock_reporting.interpretation.macro_risk.fallback_config import FALLBACK_CONFIG

_DEFAULT_CONFIG_PATH = Path("config/reporting/macro_risk_thresholds.yaml")


def load_reporting_config(config_path: Path | str | None = None) -> dict[str, Any]:
    """读取研报评级与定性话术配置文件。"""
    cfg_p = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    if cfg_p.is_file():
        try:
            payload = yaml.safe_load(cfg_p.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and "dimensions" in payload:
                return payload
        except Exception:
            pass
    return FALLBACK_CONFIG


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _grade_dim(
    dim_key: str,
    val: float | None,
    cfg: dict[str, Any],
    special_vars: dict[str, float | None] | None = None,
) -> tuple[str, str, str]:
    """根据 YAML 分段配置打分并匹配话术。"""
    dim_cfg = cfg.get("dimensions", {}).get(dim_key, {})
    if val is None:
        missing = dim_cfg.get("missing", {})
        return (
            missing.get("grade", "数据暂缺"),
            missing.get("icon", "⚪"),
            missing.get("comment", "历史数据不足"),
        )

    special_cases = dim_cfg.get("special_cases", [])
    if special_cases and special_vars:
        for sc in special_cases:
            cond = sc.get("condition")
            if cond == "etf_score_gte_90":
                etf_s = special_vars.get("etf_score")
                if etf_s is not None and etf_s >= sc.get("etf_score_min", 90.0):
                    return sc["grade"], sc["icon"], sc["comment"]
            elif cond == "divergence_and_flow":
                div_s = special_vars.get("div_score")
                if (
                    div_s is not None
                    and div_s >= sc.get("div_score_min", 85.0)
                    and val >= sc.get("val_min", 65.0)
                ):
                    return sc["grade"], sc["icon"], sc["comment"]

    tiers = dim_cfg.get("tiers", [])
    default_tier: dict[str, str] = {"grade": "正常", "icon": "⚪", "comment": "处于正常区间"}
    for t in tiers:
        if t.get("default"):
            default_tier = t
            continue
        if "min" in t and val >= float(t["min"]):
            return t["grade"], t["icon"], t["comment"]
        if "max" in t and val <= float(t["max"]):
            return t["grade"], t["icon"], t["comment"]

    return (
        default_tier.get("grade", "正常"),
        default_tier.get("icon", "⚪"),
        default_tier.get("comment", "处于正常区间"),
    )


def evaluate_macro_risk(
    row: dict[str, Any], config_path: Path | str | None = None
) -> dict[str, Any]:
    """根据当日指标快照生成多维风险评级与投研建议。"""
    cfg = load_reporting_config(config_path)

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
    val_corporate = (
        _safe_float(row.get("dim_corporate")) if row.get("dim_corporate") is not None else None
    )
    val_cross_asset = (
        _safe_float(row.get("dim_cross_asset")) if row.get("dim_cross_asset") is not None else None
    )

    special_flow = {"etf_score": val_etf_score, "div_score": val_div_score}

    s_lev, b_lev, d_lev = _grade_dim("leverage", val_leverage, cfg)
    s_crw, b_crw, d_crw = _grade_dim("crowding", val_crowding, cfg)
    s_flw, b_flw, d_flw = _grade_dim("flow", val_flow, cfg, special_flow)
    s_sen, b_sen, d_sen = _grade_dim("sentiment", val_sentiment, cfg)
    s_brd, b_brd, d_brd = _grade_dim("breadth", val_breadth, cfg)
    s_val, b_val, d_val = _grade_dim("valuation", val_valuation, cfg)
    s_corp, b_corp, d_corp = _grade_dim("corporate", val_corporate, cfg)
    s_cross, b_cross, d_cross = _grade_dim("cross_asset", val_cross_asset, cfg)

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

    val_fund_issue = (
        _safe_float(row.get("fund_issue_pct_score"))
        if row.get("fund_issue_pct_score") is not None
        else None
    )
    val_insider_sell = (
        _safe_float(row.get("insider_sell_score"))
        if row.get("insider_sell_score") is not None
        else None
    )
    val_unlock = (
        _safe_float(row.get("unlock_amount_score"))
        if row.get("unlock_amount_score") is not None
        else None
    )

    advice = ""
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
        has_top_divergence = (val_fund_issue is not None and val_fund_issue >= 75.0) and (
            (val_insider_sell is not None and val_insider_sell >= 75.0)
            or (val_unlock is not None and val_unlock >= 80.0)
        )
        if has_top_divergence:
            status = "极度狂热 —— 【高位公募接盘与产业资本出逃背离 (见顶预警)】"
            advice = (
                f"- **当前状态**：狂热指数 ({overheat:.1f}) 处于高位，公募新发火爆 ({val_fund_issue:.1f})，而董监高减持与解禁分位同步爆发 ({val_insider_sell if val_insider_sell is not None else val_unlock:.1f})。\n"
                "- **市场定性**：典型的‘场外羊群资金高位狂热接盘、产业资本与大股东密集套现兑现’的大级别背离。\n"
                "- **后续推演**：二级市场承接流动性正在被产业资本实质性抽干，主升浪已进入尾声，未来季度预期收益极大概率为负。\n"
                "👉 **操作建议**：严禁加杠杆追高；全面收紧止盈线，严格以 20 日均线 (MA20) 作为右侧刚性退出开关，放量跌破 MA20 坚决清仓进攻端退守国债/黄金避险。"
            )
        else:
            status = "极度狂热 (极高回撤风险)"
            advice = (
                f"- **当前状态**：狂热指数 ({overheat:.1f}) 已突破危险阈值。\n"
                "- **市场定性**：全市场资金处于极度亢奋的“博傻”阶段。\n"
                "- **后续推演**：无论当前是否处于护盘期，未来一季度的预期收益极大概率为负。\n"
                "👉 **操作建议**：狂热区不盲目左侧猜顶，但严禁加杠杆追高；收紧止盈线，以 20 日均线 (MA20) 作为右侧刚性退出开关，一旦放量跌破 MA20 坚决清仓进攻端。"
            )
        level = "danger"
    elif panic > 65:
        val_rep_val = (
            _safe_float(row.get("repurchase_score"))
            if row.get("repurchase_score") is not None
            else None
        )
        has_corp_support = (val_corporate is not None and val_corporate >= 75.0) or (
            val_rep_val is not None and val_rep_val >= 80.0
        )
        is_corp_absent = (val_corporate is not None and val_corporate <= 25.0) and (
            val_rep_val is None or val_rep_val <= 30.0
        )
        is_corp_lead = (
            val_etf_score is not None
            and val_etf_score < 40.0
            and (
                (val_corporate is not None and val_corporate >= 65.0)
                or (val_rep_val is not None and val_rep_val >= 70.0)
            )
        )

        if is_corp_lead:
            corp_metric = val_corporate if val_corporate is not None else val_rep_val
            status = "极度恐慌 —— 【微观产业底抢跑 (企业大额回购)】"
            advice = (
                f"- **当前状态**：恐慌指数偏高 ({panic:.1f})，国家队 ETF 买盘尚不明显 ({val_etf_score:.1f})，但上市公司回购潮已率先爆发 ({corp_metric:.1f})。\n"
                "- **市场定性**：产业资本先行于宏观调令，对细分行业估值底线展开实质性投票。\n"
                "- **后续推演**：微观企业自发展开托底，筑底周期开启，下行空间有限。\n"
                "👉 **操作建议**：左侧跟随产业资本低吸被错杀的绩优蓝筹与红利资产，防范错过反弹行情。"
            )
        elif has_corp_support:
            corp_metric = val_corporate if val_corporate is not None else val_rep_val
            status = "极度恐慌 —— 【产业托底真黄金坑 (强共振底)】"
            advice = (
                f"- **当前状态**：恐慌指数突破危险阈值 ({panic:.1f})，同时全市场回购与产业资本托底达极高分位 ({corp_metric:.1f})。\n"
                "- **市场定性**：二级市场非理性情绪杀跌与上市公司真金白银大额回购注销发生罕见强共振。\n"
                "- **后续推演**：下行空间已被微观基本面与产业资本托底彻底锁死，极大概率为历史级坚实大底。\n"
                "👉 **操作建议**：坚决在左侧分批重仓配置大盘宽基（沪深300）与高股息红利，无需精准择时，耐心锁仓等待均值回归。"
            )
        elif is_corp_absent:
            corp_metric = val_corporate if val_corporate is not None else 0.0
            status = "极度恐慌 —— 【警惕多杀多中继 (产业未托底/假黄金坑)】"
            advice = (
                f"- **当前状态**：恐慌指数爆表 ({panic:.1f})，但全市场回购分位数仅处于低位 ({corp_metric:.1f})。\n"
                "- **市场定性**：暴跌主要由场内杠杆爆仓与情绪踩踏造成，实体企业尚未认可当前估值底线并大额回购。\n"
                "- **后续推演**：属于典型的流动性挤压中继，谨防单日反弹诱多，后续仍面临二次下探与多杀多连环风险。\n"
                "👉 **操作建议**：严禁盲目左侧加杠杆抄底；坚决以 20 日均线 (MA20) 作为刚性防线，未站稳均线前保持防守或持有债金避险。"
            )
        elif crowding > 45:
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
        "产业资本 (Corporate)": val_corporate if val_corporate is not None else 0.0,
        "跨资产宏观 (CrossAsset)": val_cross_asset if val_cross_asset is not None else 0.0,
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


__all__ = ["evaluate_macro_risk", "load_reporting_config"]
