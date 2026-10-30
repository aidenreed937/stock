"""宏观风控解读逻辑与报告渲染单元测试。"""

from datetime import date

import polars as pl
import pytest

from stock_reporting.interpretation.macro_risk.logic import (
    evaluate_macro_risk,
    load_reporting_config,
)
from stock_reporting.templates.macro_risk_report import render_macro_risk_report


def test_load_reporting_config_missing_path_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_reporting_config(tmp_path / "missing.yaml")


def test_evaluate_macro_risk_dual_extremes() -> None:
    row = {
        "trade_date": date(2015, 6, 26),
        "overheat_index": 69.5,
        "panic_index": 70.9,
        "dim_leverage": 100.0,
        "dim_crowding": 95.9,
        "dim_valuation": 60.0,
        "dim_fear": 27.7,
        "dim_breadth": 95.0,
        "dim_flow": 90.2,
    }
    res = evaluate_macro_risk(row)
    assert "双极值共振" in res["status"]
    assert res["level"] == "danger"
    assert "严禁抄底" in res["status"]
    assert "杠杆多杀多" in res["advice"]


def test_evaluate_macro_risk_extreme_overheat() -> None:
    row = {
        "trade_date": date(2026, 8, 26),
        "overheat_index": 68.0,
        "panic_index": 40.0,
        "dim_leverage": 95.0,
        "dim_crowding": 70.0,
        "dim_valuation": 50.0,
        "dim_fear": 30.0,
    }
    res = evaluate_macro_risk(row)
    assert "极度狂热" in res["status"]
    assert res["level"] == "danger"


def test_evaluate_macro_risk_uses_configured_index_thresholds() -> None:
    """双轨指数灯号使用 YAML 中的 60/65、60/70 阈值。"""
    safe_row = {
        "trade_date": date(2026, 7, 29),
        "overheat_index": 58.0,
        "panic_index": 58.0,
    }
    safe_res = evaluate_macro_risk(safe_row)
    assert safe_res["level"] == "safe"

    warning_row = {
        "trade_date": date(2026, 6, 10),
        "overheat_index": 45.0,
        "panic_index": 66.0,
    }
    warning_res = evaluate_macro_risk(warning_row)
    assert warning_res["level"] == "warning"
    assert "恐慌蔓延" in warning_res["status"]

    overheat_only_row = {
        "trade_date": date(2026, 6, 26),
        "overheat_index": 66.0,
        "panic_index": 66.0,
    }
    overheat_res = evaluate_macro_risk(overheat_only_row)
    assert overheat_res["level"] == "danger"
    assert "极度狂热" in overheat_res["status"]
    assert "双极值共振" not in overheat_res["status"]


def test_evaluate_macro_risk_panic_volume_bottom() -> None:
    row = {
        "trade_date": date(2015, 8, 24),
        "overheat_index": 50.0,
        "panic_index": 92.0,
        "dim_crowding": 85.0,
        "dim_breadth": 99.0,
    }
    res = evaluate_macro_risk(row)
    assert "放量出清底" in res["status"]
    assert res["level"] == "opportunity"


def test_evaluate_macro_risk_panic_shrink_bottom() -> None:
    row = {
        "trade_date": date(2016, 1, 7),
        "overheat_index": 35.0,
        "panic_index": 87.0,
        "dim_crowding": 10.0,
        "dim_breadth": 98.0,
    }
    res = evaluate_macro_risk(row)
    assert "缩量绝望底" in res["status"]
    assert res["level"] == "opportunity"


def test_render_macro_risk_report_dual_extremes() -> None:
    df = pl.DataFrame(
        {
            "trade_date": [date(2015, 6, 26)],
            "overheat_index": [69.5],
            "panic_index": [70.9],
            "dim_valuation": [60.0],
            "dim_leverage": [100.0],
            "dim_fear": [27.7],
            "dim_crowding": [95.9],
            "dim_breadth": [95.0],
            "dim_flow": [90.2],
        }
    )
    md = render_macro_risk_report(df, date(2015, 6, 26))
    assert "雷达日报" in md
    assert "双极值共振" in md
    assert "今日信号" in md
    assert "操作指引" in md


def test_render_macro_risk_report_pro_template() -> None:
    """专业版模板保留全维度穿透与深度归因。"""
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 28)],
            "overheat_index": [69.2],
            "panic_index": [33.9],
            "dim_valuation": [47.2],
            "dim_leverage": [84.9],
            "dim_fear": [28.8],
            "dim_crowding": [78.4],
            "dim_breadth": [37.0],
            "dim_flow": [35.7],
        }
    )
    md = render_macro_risk_report(df, date(2026, 8, 28), template="pro")
    assert "宏观风控双轨制雷达日报" in md
    assert "全维度系统性风险穿透" in md
    assert "深度归因与操作建议" in md


def test_evaluate_macro_risk_flow_active_inflow() -> None:
    row = {
        "trade_date": date(2025, 4, 7),
        "overheat_index": 45.0,
        "panic_index": 80.0,
        "dim_flow": 25.0,
        "dim_crowding": 60.0,
    }
    res = evaluate_macro_risk(row)
    flow_item = next(
        item for tier in res["risk_tiers"] for item in tier["metrics"] if item["code"] == "dim_flow"
    )
    assert flow_item["status"] == "流入活跃"
    assert "🟢" in flow_item["badge"]


def test_evaluate_macro_risk_divergence_distribution() -> None:
    row = {
        "trade_date": date(2021, 2, 18),
        "overheat_index": 68.0,
        "panic_index": 45.0,
        "dim_flow": 72.0,
        "divergence_score": 90.0,
    }
    res = evaluate_macro_risk(row)
    flow_item = next(
        item for tier in res["risk_tiers"] for item in tier["metrics"] if item["code"] == "dim_flow"
    )
    assert flow_item["status"] == "资金筹码背离"
    assert flow_item["desc"] == "资金流向或筹码分歧明显承压，筹码结构严重背离"
    assert "🔴" in flow_item["badge"]


def test_evaluate_macro_risk_true_gold_pit() -> None:
    """测试真黄金坑：恐慌爆表 + 产业低压力/高回购金额共振。"""
    row = {
        "trade_date": date(2026, 3, 23),
        "overheat_index": 40.0,
        "panic_index": 86.0,
        "dim_corporate": 18.0,
        "repurchase_score": 22.0,
    }
    res = evaluate_macro_risk(row)
    assert "产业托底真黄金坑" in res["status"]
    assert res["level"] == "opportunity"
    assert "产业资本综合压力低" in res["advice"]
    assert "对应回购金额偏高" in res["advice"]


def test_evaluate_macro_risk_low_corporate_pressure_not_false_gold_pit() -> None:
    """产业资本低分代表综合压力低，不应被判为产业未托底。"""
    row = {
        "trade_date": date(2026, 8, 24),
        "overheat_index": 40.0,
        "panic_index": 72.0,
        "dim_corporate": 18.8,
        "repurchase_score": 24.0,
    }
    res = evaluate_macro_risk(row)
    assert "假黄金坑" not in res["status"]
    assert "产业资本综合压力低" in res["advice"]


def test_evaluate_macro_risk_false_gold_pit_warning() -> None:
    """测试假黄金坑警示：恐慌高企但产业资本压力高且回购不足。"""
    row = {
        "trade_date": date(2015, 6, 19),
        "overheat_index": 50.0,
        "panic_index": 72.0,
        "dim_corporate": 82.0,
        "repurchase_score": 78.0,
    }
    res = evaluate_macro_risk(row)
    assert "警惕多杀多中继" in res["status"]
    assert "假黄金坑" in res["status"]
    assert res["level"] == "warning"
    assert "严禁盲目左侧加杠杆抄底" in res["advice"]


def test_evaluate_macro_risk_corporate_lead() -> None:
    """测试独立产业底：聪明钱观望但产业压力先行缓和。"""
    row = {
        "trade_date": date(2026, 2, 2),
        "overheat_index": 45.0,
        "panic_index": 72.0,
        "smart_money_pct": 5.0,
        "dim_corporate": 20.0,
        "repurchase_score": 62.0,
    }
    res = evaluate_macro_risk(row)
    assert "微观产业底抢跑" in res["status"]
    assert res["level"] == "opportunity"
    assert "产业资本压力先于宏观风险缓和" in res["advice"]


def test_evaluate_macro_risk_buyback_only_support_with_high_corporate_pressure() -> None:
    """回购高发但产业资本综合压力高时，不得误判为产业底抢跑。"""
    row = {
        "trade_date": date(2026, 10, 29),
        "overheat_index": 45.0,
        "panic_index": 72.0,
        "smart_money_pct": 5.0,
        "dim_corporate": 92.3,
        "repurchase_score": 5.2,
    }
    res = evaluate_macro_risk(row)
    assert "回购单项支撑" in res["status"]
    assert "微观产业底抢跑" not in res["status"]
    assert "产业压力未缓和" in res["status"]
    assert "产业资本综合压力仍高" in res["advice"]
    assert res["scenario"] == "panic_buyback_only"

    md = render_macro_risk_report(
        pl.DataFrame(
            {
                "trade_date": [date(2026, 10, 29)],
                "overheat_index": [45.0],
                "panic_index": [72.0],
                "smart_money_pct": [5.0],
                "dim_corporate": [92.3],
                "repurchase_score": [5.2],
            }
        ),
        date(2026, 10, 29),
    )
    assert "产业资本综合压力仍高" in md
    assert "产业资本只是低压力" not in md


def test_evaluate_macro_risk_high_corporate_pressure_blocks_true_gold_pit() -> None:
    """回购与聪明钱同时支持，但综合产业压力高时也不能称为真黄金坑。"""
    row = {
        "trade_date": date(2026, 10, 29),
        "overheat_index": 45.0,
        "panic_index": 72.0,
        "smart_money_pct": 85.0,
        "dim_corporate": 82.0,
        "repurchase_score": 20.0,
    }
    res = evaluate_macro_risk(row)
    assert "产业托底真黄金坑" not in res["status"]
    assert "回购单项支撑" in res["status"]


def test_render_macro_risk_report_false_gold_pit_action_guide() -> None:
    """普通版操作指引不得与假黄金坑分支冲突。"""
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 19)],
            "overheat_index": [40.0],
            "panic_index": [72.0],
            "dim_corporate": [82.0],
            "repurchase_score": [78.0],
        }
    )
    md = render_macro_risk_report(df, date(2026, 8, 19))
    assert "假黄金坑" in md
    assert "不要左侧抄底" in md
    assert "恐慌区可左侧分批低吸" not in md


def test_evaluate_macro_risk_breadth_text_is_not_overstated() -> None:
    row = {
        "trade_date": date(2026, 8, 28),
        "overheat_index": 45.0,
        "panic_index": 45.0,
        "dim_breadth": 19.5,
    }
    res = evaluate_macro_risk(row)
    breadth_item = next(
        item
        for tier in res["risk_tiers"]
        for item in tier["metrics"]
        if item["code"] == "dim_breadth"
    )
    assert breadth_item["status"] == "广度扩散"
    assert "上涨占优或新高扩散" in breadth_item["desc"]
    assert "全线普涨" not in breadth_item["status"]


def test_evaluate_macro_risk_top_corporate_divergence() -> None:
    """测试牛市顶部背离：狂热高位 + 董监高大额减持出逃。"""
    row = {
        "trade_date": date(2015, 6, 12),
        "overheat_index": 71.5,
        "panic_index": 35.0,
        "insider_sell_score": 98.7,
        "unlock_amount_score": 85.7,
    }
    res = evaluate_macro_risk(row)
    assert "高位产业资本出逃背离" in res["status"]
    assert res["level"] == "danger"
    assert "产业资本与大股东密集套现兑现" in res["advice"]
    assert "生命线" in res["advice"]


def test_evaluate_macro_risk_panic_dd_deep_confirm() -> None:
    """恐慌极值 + 距前120日高点回撤 ≥20% → 深底确认提示。"""
    row = {
        "trade_date": date(2018, 10, 18),
        "overheat_index": 30.0,
        "panic_index": 83.5,
        "dim_crowding": 20.0,
    }
    res = evaluate_macro_risk(row, dd_from_high=-0.29)
    assert res["level"] == "opportunity"
    assert "深底确认" in res["advice"]
    assert "真冰点" in res["advice"]


def test_evaluate_macro_risk_panic_dd_midterm_warn() -> None:
    """恐慌极值 + 回撤 10%~20% → 中继风险提示。"""
    row = {
        "trade_date": date(2026, 7, 13),
        "overheat_index": 45.0,
        "panic_index": 78.0,
        "dim_crowding": 70.0,
    }
    res = evaluate_macro_risk(row, dd_from_high=-0.10)
    assert res["level"] == "opportunity"
    assert "中继风险" in res["advice"]
    assert "分批建仓优于一次性满仓" in res["advice"]


def test_evaluate_macro_risk_panic_dd_shallow_fake_bottom() -> None:
    """恐慌极值 + 回撤 <10% → 假冰点预警。"""
    row = {
        "trade_date": date(2026, 7, 7),
        "overheat_index": 45.0,
        "panic_index": 77.2,
        "dim_crowding": 75.0,
    }
    res = evaluate_macro_risk(row, dd_from_high=-0.07)
    assert res["level"] == "opportunity"
    assert "假冰点预警" in res["advice"]
    assert "接飞刀风险" in res["advice"]


def test_evaluate_macro_risk_panic_no_dd_no_position_hint() -> None:
    """dd_from_high 缺失（数据不足）时，恐慌分支不追加位置提示。"""
    row = {
        "trade_date": date(2020, 3, 23),
        "overheat_index": 30.0,
        "panic_index": 86.7,
        "dim_crowding": 67.9,
    }
    res = evaluate_macro_risk(row, dd_from_high=None)
    assert res["level"] == "opportunity"
    assert "深底确认" not in res["advice"]
    assert "中继风险" not in res["advice"]
    assert "假冰点预警" not in res["advice"]


def test_evaluate_macro_risk_missing_indices_fail_closed() -> None:
    """双轨指数缺失 → 判「数据暂缺」，不得静默落入「情绪平稳」。"""
    res = evaluate_macro_risk({"trade_date": date(2026, 1, 5)})
    assert res["level"] == "warning"
    assert "数据暂缺" in res["status"]
    assert res["scenario"] == "data_missing"
    assert "情绪平稳" not in res["status"]

    only_overheat = evaluate_macro_risk({"trade_date": date(2026, 1, 5), "overheat_index": 40.0})
    assert only_overheat["level"] == "warning"
    assert "数据暂缺" in only_overheat["status"]


def test_evaluate_macro_risk_panic_crowding_missing_fail_closed() -> None:
    """恐慌极值 + 换手拥挤度缺失 → 不误判「缩量绝望底」重仓建议，披露数据缺口。"""
    row = {
        "trade_date": date(2020, 3, 23),
        "overheat_index": 30.0,
        "panic_index": 86.7,
    }
    res = evaluate_macro_risk(row)
    assert res["level"] == "warning"
    assert res["scenario"] == "panic_crowding_missing"
    assert "换手数据缺失" in res["status"]
    assert "缩量绝望底" not in res["status"]
    assert "果断重仓" not in res["advice"]  # 缺失时不给出激进满仓建议
    assert "不因恐慌极值直接重仓" in res["advice"]


def test_evaluate_macro_risk_top_divergence_displays_trigger_value() -> None:
    """高位背离文案只显示实际满足阈值的证据值（unlock 触发时不显示未达标的 insider_sell）。"""
    row = {
        "trade_date": date(2015, 6, 12),
        "overheat_index": 71.5,
        "panic_index": 35.0,
        "insider_sell_score": 60.0,  # 未达 75，不构成触发
        "unlock_amount_score": 85.7,  # 达 80，实际触发
    }
    res = evaluate_macro_risk(row)
    assert "高位产业资本出逃背离" in res["status"]
    assert "限售解禁 (85.7)" in res["advice"]
    assert "大股东减持 (60.0)" not in res["advice"]

    # 减持达标时显示减持
    row2 = {**row, "insider_sell_score": 98.7, "unlock_amount_score": 20.0}
    res2 = evaluate_macro_risk(row2)
    assert "大股东减持 (98.7)" in res2["advice"]
    assert "限售解禁" not in res2["advice"]


def test_action_guide_safe_level_respects_broken_lifeline() -> None:
    """宏观平稳 + 生命线跌破：不得输出「空仓可正常配置」。"""
    from stock_reporting.templates.macro_risk_report import _build_action_guide

    broken = {"close": 5214.0, "ma20": 5503.0, "broken": True}
    guide = _build_action_guide("safe", broken, panic_value=56.3)
    assert "可正常配置" not in guide
    assert "5503" in guide
    assert "进攻端" in guide

    intact = {"close": 5600.0, "ma20": 5503.0, "broken": False}
    assert "可正常配置" in _build_action_guide("safe", intact, panic_value=56.3)


def test_action_guide_warning_level_respects_broken_lifeline() -> None:
    """预警档同样不得在趋势破位时给出无约束话术。"""
    from stock_reporting.templates.macro_risk_report import _build_action_guide

    guide = _build_action_guide(
        "warning", {"close": 5214.0, "ma20": 5503.0, "broken": True}, panic_value=62.0
    )
    assert "MA20" in guide
    assert "进攻端" in guide


def test_trend_note_empty_when_lifeline_intact() -> None:
    from stock_reporting.templates.macro_risk_report import _build_trend_note

    assert _build_trend_note({"close": 5600.0, "ma20": 5503.0, "broken": False}) == ""
    note = _build_trend_note({"close": 5214.0, "ma20": 5503.0, "broken": True})
    assert "趋势纪律" in note and "5503" in note


def test_valuation_tier_partial_undervalued_not_median() -> None:
    """25 分位属偏低估，不能被渲染成「历史中位数水平」。"""
    row = {
        "trade_date": date(2026, 10, 26),
        "overheat_index": 51.5,
        "panic_index": 56.3,
        "dim_valuation": 25.07,
    }
    res = evaluate_macro_risk(row)
    item = next(i for t in res["risk_tiers"] for i in t["metrics"] if i["code"] == "dim_valuation")
    assert item["status"] == "偏低估"
    assert "中位数" not in item["desc"]


def test_flow_divergence_override_when_mean_diluted() -> None:
    """筹码背离度触及极值时，即使合成分被稀释到中枢也判背离。"""
    row = {
        "trade_date": date(2026, 10, 26),
        "overheat_index": 51.5,
        "panic_index": 56.3,
        "dim_flow": 50.39,
        "divergence_score": 99.44,
    }
    res = evaluate_macro_risk(row)
    item = next(i for t in res["risk_tiers"] for i in t["metrics"] if i["code"] == "dim_flow")
    assert item["status"] == "资金筹码背离"

    diluted = {**row, "divergence_score": 86.0}
    item2 = next(
        i
        for t in evaluate_macro_risk(diluted)["risk_tiers"]
        for i in t["metrics"]
        if i["code"] == "dim_flow"
    )
    assert item2["status"] == "流向平衡"


def test_component_dispersion_disclosed_when_components_diverge() -> None:
    """成分极差超阈值时进入披露列表，并写进维度话术。"""
    row = {
        "trade_date": date(2026, 10, 26),
        "overheat_index": 51.5,
        "panic_index": 56.3,
        "dim_fear": 52.1,
        "pcr_score": 6.41,
        "iv_score": 85.85,
        "vix_score": 64.05,
    }
    res = evaluate_macro_risk(row)
    entry = next(d for d in res["component_dispersion"] if d["dim"] == "fear")
    assert entry["spread"] > 50
    assert entry["high_label"] == "隐含波动率IV"
    assert entry["name"] == "期权情绪"
    fear = next(i for t in res["risk_tiers"] for i in t["metrics"] if i["code"] == "dim_fear")
    assert "成分极差" in fear["desc"]


def test_component_dispersion_silent_when_components_agree() -> None:
    row = {
        "trade_date": date(2026, 10, 26),
        "overheat_index": 51.5,
        "panic_index": 56.3,
        "dim_fear": 50.0,
        "pcr_score": 48.0,
        "iv_score": 52.0,
        "vix_score": 50.0,
    }
    res = evaluate_macro_risk(row)
    assert all(d["dim"] != "fear" for d in res["component_dispersion"])


def test_render_report_discloses_dispersion_and_auxiliary_dimensions() -> None:
    """普通投资者版在成分分歧时落出附加维度，但不再展示公募新发指标。"""
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 10, 26)] * 4,
            "overheat_index": [60.0, 55.0, 52.0, 51.5],
            "panic_index": [50.0, 54.0, 55.0, 56.3],
            "dim_flow": [52.0, 51.0, 50.0, 50.4],
            "divergence_score": [97.0, 98.0, 99.0, 99.4],
            "main_ratio_score": [1.5, 1.4, 1.3, 1.28],
            "composite_flow_score": [1.9, 1.6, 1.4, 1.28],
            "smart_money_pct": [6.0, 5.0, 4.0, 4.82],
            "newlow252_ratio_score": [91.0, 82.0, 71.0, 62.3],
        }
    )
    md = render_macro_risk_report(df, date(2026, 10, 26))
    assert "成分分歧提示" in md
    assert "附加维度" in md
    assert "52周新低占比分位" in md
    assert "公募新发" not in md
    assert "新发基金数量分位" not in md


def test_render_report_lists_newlow252_percentile_as_auxiliary() -> None:
    """52 周新低占比分位作为附加维度落出，且不影响双轨指数读数。"""
    df = pl.DataFrame(
        {
            "trade_date": [date(2026, 10, 27), date(2026, 10, 28)],
            "overheat_index": [48.0, 47.2],
            "panic_index": [58.0, 56.4],
            "newlow252_ratio_score": [91.5, 62.3],
        }
    )
    md = render_macro_risk_report(df, date(2026, 10, 28))
    assert "52周新低占比分位" in md
    assert "62.3" in md
