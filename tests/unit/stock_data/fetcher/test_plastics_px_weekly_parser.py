"""单元测试: 苯乙烯 (EB)、聚丙烯 (PP)、对二甲苯 (PX) 周度样本指标解析与物理守恒门禁校验。"""

from __future__ import annotations

from stock_data.fetcher.industry.chemicals.parsers.weekly_survey import (
    CHEMICAL_PHYSICAL_BOUNDS,
    DOWNSTREAM_EXCLUDES,
    parse_commodity_weekly_metrics,
)


def test_eb_weekly_metrics_parsing() -> None:
    """测试苯乙烯 (EB) 开工率、周产量与港口样本库存抽取。"""
    # 模拟真实隆众周报格式
    html_text_output = """
    一、苯乙烯产量及产能利用率趋势定性分析
    本周期（20260904-20260910）国内苯乙烯企业总产量为32.38万吨，较上周增加0.65万吨，环比增加2.05%；
    行业整体产能利用率64.55%，环比增加1.30个百分点。
    """
    res1 = parse_commodity_weekly_metrics(html_text_output, "苯乙烯", "EB")
    assert res1["operating_rate_pct"] == 64.55
    assert res1["weekly_output_w_tons"] == 32.38

    # 模拟真实港口库存周报格式
    html_text_inv = """
    一、江苏苯乙烯港口库存趋势定型分析
    截至2026年9月21日，江苏苯乙烯港口样本库存总量：4.16万吨，较上周同期增加0.73万吨，幅度+21.28%。
    商品量库存在2.68万吨，较上周期增加0.85万吨。
    """
    res2 = parse_commodity_weekly_metrics(html_text_inv, "苯乙烯", "EB")
    assert res2["factory_inventory_w_tons"] == 4.16


def test_eb_downstream_and_bounds_guard() -> None:
    """测试苯乙烯下游排除与物理合理区间门禁。"""
    # 下游 PS/ABS 干扰文本
    downstream_text = """
    本周下游PS装置产能利用率58.20%，ABS行业开工率62.30%，下游需求整体平稳。
    """
    res_down = parse_commodity_weekly_metrics(downstream_text, "苯乙烯", "EB")
    assert res_down["operating_rate_pct"] is None

    # 超出物理守恒的异常开工率 (如 >95% 或 <45%)
    overflow_text = "国内苯乙烯行业整体产能利用率98.50%，总产量55.0万吨。"
    res_overflow = parse_commodity_weekly_metrics(overflow_text, "苯乙烯", "EB")
    assert res_overflow["operating_rate_pct"] is None
    assert res_overflow["weekly_output_w_tons"] is None


def test_pp_weekly_metrics_parsing() -> None:
    """测试聚丙烯 (PP) 开工率、周产量与库存抽取。"""
    # 模拟真实生意社/隆众周报
    html_text = """
    进入9月，国内PP企业检修与重启互现，总体开工率接近70%，较上月底相比大稳小动。
    近期广西石化、东莞巨正源等企业有负荷提升计划，后市有少量供增预期。
    当前周均产量仍在72万吨附近，库存位置接近54万吨处。
    """
    res = parse_commodity_weekly_metrics(html_text, "聚丙烯", "PP")
    assert res["operating_rate_pct"] == 70.0
    assert res["weekly_output_w_tons"] == 72.0
    assert res["factory_inventory_w_tons"] == 54.0

    # 隆众文章格式
    lz_text = """
    本周期聚丙烯平均产能利用率环比下降0.43个百分点至69.48%，中石化产能利用率环比上升4.02%至60.10%。
    """
    res_lz = parse_commodity_weekly_metrics(lz_text, "聚丙烯", "PP")
    assert res_lz["operating_rate_pct"] == 69.48


def test_pp_downstream_and_bounds_guard() -> None:
    """测试聚丙烯下游排除词与物理边界。"""
    downstream_text = "本周BOPP企业开工负荷率52.1%，塑编下游制品开工率45.0%。"
    res_down = parse_commodity_weekly_metrics(downstream_text, "聚丙烯", "PP")
    assert res_down["operating_rate_pct"] is None

    # 异常开工率
    overflow_text = "中国聚丙烯装置平均产能利用率99.5%，中国聚丙烯主要生产企业总库存120.0万吨。"
    res_overflow = parse_commodity_weekly_metrics(overflow_text, "聚丙烯", "PP")
    assert res_overflow["operating_rate_pct"] is None
    assert res_overflow["factory_inventory_w_tons"] is None


def test_px_weekly_metrics_parsing() -> None:
    """测试对二甲苯 (PX) 开工率与周产量抽取。"""
    # 模拟真实隆众周报格式
    html_text = """
    国内PX周均产能利用率80.40%，本周PX产量为66.66万吨，较上周产量微增。
    """
    res = parse_commodity_weekly_metrics(html_text, "对二甲苯", "PX")
    assert res["operating_rate_pct"] == 80.4
    assert res["weekly_output_w_tons"] == 66.66


def test_px_downstream_and_bounds_guard() -> None:
    """测试对二甲苯下游 (PTA/聚酯) 排除与物理守恒。"""
    downstream_text = "本周PTA装置产能利用率82.5%，聚酯长丝短纤开工负荷85.0%。"
    res_down = parse_commodity_weekly_metrics(downstream_text, "对二甲苯", "PX")
    assert res_down["operating_rate_pct"] is None

    # 异常数据
    overflow_text = "国内PX周均产能利用率99.0%，本周PX产量为110.0万吨。"
    res_overflow = parse_commodity_weekly_metrics(overflow_text, "对二甲苯", "PX")
    assert res_overflow["operating_rate_pct"] is None
    assert res_overflow["weekly_output_w_tons"] is None


def test_bounds_and_excludes_registered() -> None:
    """验证三品种物理区间与排除词已登记在常量字典中。"""
    for sym in ("EB", "PP", "PX"):
        assert sym in CHEMICAL_PHYSICAL_BOUNDS
        assert "operating_rate_pct" in CHEMICAL_PHYSICAL_BOUNDS[sym]
        assert "weekly_output_w_tons" in CHEMICAL_PHYSICAL_BOUNDS[sym]
        assert "factory_inventory_w_tons" in CHEMICAL_PHYSICAL_BOUNDS[sym]
        assert sym in DOWNSTREAM_EXCLUDES
        assert len(DOWNSTREAM_EXCLUDES[sym]) >= 5
