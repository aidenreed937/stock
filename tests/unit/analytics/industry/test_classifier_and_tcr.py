"""行业分类解析器与 TCR 拥挤度时间切片/白名单过滤单元测试。"""

from datetime import date

import polars as pl
import pytest

from stock.analytics.industry.classifier import IndustryClassifier
from stock.analytics.industry.tcr import TCRCalculator


def test_industry_classifier_dynamic_resolution() -> None:
    """验证行业分类器能够正确解析 801xxx 及 6 位代码为标准行业中文名称。"""
    classifier = IndustryClassifier()

    l1_codes = classifier.get_l1_codes("SW2021")
    assert len(l1_codes) == 31
    assert "801080.SI" in l1_codes
    assert "801780.SI" in l1_codes
    assert "801980.SI" in l1_codes  # 美容护理
    assert "801001.SI" not in l1_codes  # 申万A股综合指数不在一级行业集合中

    assert classifier.resolve_name("801080.SI") == "电子"
    assert classifier.resolve_name("270000") == "电子"
    assert classifier.resolve_name("801780.SI") == "银行"
    assert classifier.resolve_name("480000") == "银行"
    assert classifier.resolve_name("801980.SI") == "美容护理"
    assert classifier.resolve_name("770000") == "美容护理"
    assert classifier.resolve_name("801030.SI") == "基础化工"
    assert classifier.resolve_name("801730.SI") == "电力设备"
    assert classifier.resolve_name("640000") == "机械设备"
    assert classifier.resolve_name("650000") == "国防军工"
    assert classifier.resolve_name("710000") == "计算机"


def test_tcr_calculator_strict_date_and_l1_filter() -> None:
    """验证 TCR 拥挤度计算严格按 target_date 截断，并精确过滤掉综合大盘指数。"""
    records = [
        {"trade_date": date(2026, 8, 12), "symbol": "801080.SI", "amount": 3000.0},
        {"trade_date": date(2026, 8, 12), "symbol": "801780.SI", "amount": 4000.0},
        {"trade_date": date(2026, 8, 12), "symbol": "801120.SI", "amount": 3000.0},
        # 综合指数 801001.SI (必须被剔除)
        {"trade_date": date(2026, 8, 12), "symbol": "801001.SI", "amount": 20000.0},
        # 2026-08-13 未来数据 (必须被截断)
        {"trade_date": date(2026, 8, 13), "symbol": "801080.SI", "amount": 9000.0},
        {"trade_date": date(2026, 8, 13), "symbol": "801780.SI", "amount": 1000.0},
    ]

    df = pl.DataFrame(records)

    calc = TCRCalculator()
    res = calc.calculate_daily_tcr(
        target_date=date(2026, 8, 12),
        sw_daily_df=df,
        crowded_threshold=25.0,
    )

    assert res is not None
    # 验证日期严格是 2026-08-12，未读取 08-13
    assert res.trade_date == date(2026, 8, 12)
    # 验证总成交额：只统计 3 个一级行业 (3000+4000+3000 = 10000)，801001 被成功剔除
    assert len(res.industries) == 3
    # 验证 TCR 百分比总和为 100%
    tcr_sum = sum(ind.tcr for ind in res.industries)
    assert tcr_sum == pytest.approx(100.0, 0.1)

    # 验证拥挤度警报：银行 40% (>25% 阈值) 触发拥挤，电子 30% 触发拥挤
    assert "银行" in res.crowded_industries
    assert "电子" in res.crowded_industries
    assert res.top1_industry == "银行"
    assert res.top1_tcr == pytest.approx(40.0, 0.1)
