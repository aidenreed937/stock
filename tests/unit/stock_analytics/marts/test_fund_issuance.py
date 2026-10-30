"""公募月度新发规模 Mart 单元测试。"""

from __future__ import annotations

import polars as pl

from stock_analytics.marts.fund_issuance import (
    FUND_ISSUANCE_SCHEMA,
    build_fund_issuance_frame,
    empty_fund_issuance,
)


def test_empty_fund_issuance() -> None:
    """测试空表 schema 稳定性。"""
    df = empty_fund_issuance()
    assert df.is_empty()
    assert set(df.columns) == set(FUND_ISSUANCE_SCHEMA.keys())


def test_build_fund_issuance_frame_with_empty_input() -> None:
    """测试空输入与缺失日期列场景。"""
    assert build_fund_issuance_frame(pl.DataFrame()).is_empty()
    no_date_df = pl.DataFrame({"ts_code": ["000001.OF"], "name": ["华夏成长"]})
    assert build_fund_issuance_frame(no_date_df).is_empty()


def test_build_fund_issuance_frame_aggregation_and_indicators() -> None:
    """测试月度分组聚合、类型分类、12M 均线与 5Y 历史百分位计算。"""
    # 构造跨越多个月份的模拟基金数据
    data = {
        "ts_code": [
            "000001.OF",
            "000002.OF",
            "000003.OF",
            "000004.OF",
            "000005.OF",
            "000006.OF",
        ],
        "name": [
            "华夏成长股票",
            "易方达积极混合",
            "招商招悦债券",
            "富国中证芯片ETF",
            "广发货币A",
            "南方均衡混合",
        ],
        "fund_type": [
            "股票型",
            "混合型",
            "债券型",
            "指数型",
            "货币型",
            "混合型",
        ],
        "found_date": [
            "20210115",
            "20210120",
            "20210125",
            "20210210",
            "20210215",
            "20210305",
        ],
        "issue_amount": [
            50.0,  # 50 亿元 (股票)
            80.0,  # 80 亿元 (混合)
            20.0,  # 20 亿元 (债券)
            30.0,  # 30 亿元 (指数型/偏股)
            10.0,  # 10 亿元 (货币/其他)
            40.0,  # 40 亿元 (混合)
        ],
    }
    fund_basic = pl.DataFrame(data)
    result = build_fund_issuance_frame(fund_basic)

    assert len(result) == 3
    assert result["month"].to_list() == ["2021-01", "2021-02", "2021-03"]

    # 2021-01: 3只基金 (2只偏股=50+80=130亿, 1只债券=20亿)
    jan = result.filter(pl.col("month") == "2021-01").to_dicts()[0]
    assert jan["total_fund_count"] == 3
    assert jan["total_issue_amount_yi"] == 150.0
    assert jan["equity_fund_count"] == 2
    assert jan["equity_issue_amount_yi"] == 130.0
    assert jan["bond_fund_count"] == 1
    assert jan["bond_issue_amount_yi"] == 20.0
    assert jan["other_fund_count"] == 0

    # 2021-02: 2只基金 (1只指数偏股=30亿, 1只货币其他=10亿)
    feb = result.filter(pl.col("month") == "2021-02").to_dicts()[0]
    assert feb["total_fund_count"] == 2
    assert feb["equity_fund_count"] == 1
    assert feb["equity_issue_amount_yi"] == 30.0
    assert feb["other_fund_count"] == 1
    assert feb["other_issue_amount_yi"] == 10.0

    # 2021-03: 1只偏股混合=40亿
    mar = result.filter(pl.col("month") == "2021-03").to_dicts()[0]
    assert mar["total_fund_count"] == 1
    assert mar["equity_fund_count"] == 1
    assert mar["equity_issue_amount_yi"] == 40.0

    # 校验均线与百分位字段存在且合法
    assert "equity_issue_ma12m_yi" in result.columns
    assert "equity_issue_pct5y" in result.columns
    assert "equity_fund_count_pct5y" in result.columns
    assert result["equity_issue_pct5y"].null_count() == 0
    assert result["equity_fund_count_pct5y"].null_count() == 0
    # 最大发行量 130 亿在 2021-01，其分位数应最高
    assert result["equity_issue_pct5y"][0] >= result["equity_issue_pct5y"][1]


def test_build_fund_issuance_frame_keeps_null_when_issue_amount_missing() -> None:
    """整月 issue_amount 缺失时必须保留 null，不得伪造成 0 发行。"""
    fund_basic = pl.DataFrame(
        {
            "ts_code": ["000001.OF", "000002.OF", "000003.OF"],
            "fund_type": ["股票型", "混合型", "股票型"],
            "found_date": ["20210115", "20210215", "20210315"],
            "issue_amount": [100.0, None, 120.0],
        }
    )
    result = build_fund_issuance_frame(fund_basic)

    feb = result.filter(pl.col("month") == "2021-02").to_dicts()[0]
    assert feb["equity_fund_count"] == 1
    assert feb["total_issue_amount_yi"] is None
    assert feb["equity_issue_amount_yi"] is None
    assert feb["equity_issue_pct5y"] is None
    assert feb["equity_fund_count_pct5y"] == 50.0

    # 缺失月不参与分位：3 月窗口内有效值仅 2 个（100、120），
    # 120 高于 1 个、等于 1 个（自身）→ (1 + 0.5*1)/2 = 75
    mar = result.filter(pl.col("month") == "2021-03").to_dicts()[0]
    assert mar["equity_issue_amount_yi"] == 120.0
    assert mar["equity_issue_pct5y"] == 75.0
