import pandas as pd
from stock_data.domain.rules import (
    BasicExclusionRule,
    CompositeRuleChain,
    LiquidityRule,
    ValuationRule,
)


def test_basic_exclusion_rule() -> None:
    df = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000002.SZ", "000010.SZ", "830001.BJ", "600519.SH"],
            "name": ["平安银行", "万科A", "ST华讯", "北交股份", "贵州茅台"],
            "list_date": ["19910403", "19910129", "19910101", "20200101", "20990101"],
        }
    )
    rule = BasicExclusionRule(exclude_st=True, exclude_bj=True, min_age_days=365)
    res = rule.apply(df)
    codes = res["ts_code"].tolist()
    assert "000001.SZ" in codes
    assert "000002.SZ" in codes
    assert "000010.SZ" not in codes
    assert "830001.BJ" not in codes
    assert "600519.SH" not in codes  # 未满足上市天数 (2099年)


def test_liquidity_rule() -> None:
    df = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000002.SZ"],
            "amount": [50000.0, 10000.0],
            "amount_20d": [40000.0, 20000.0],
        }
    )
    rule = LiquidityRule(min_daily_amount_thousand=30000.0, min_amount_20d_thousand=30000.0)
    res = rule.apply(df)
    assert len(res) == 1
    assert res["ts_code"].iloc[0] == "000001.SZ"


def test_valuation_rule() -> None:
    df = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "circ_mv": [2e9, 1e9, 2e9],
            "pb": [1.2, 1.5, 9.0],
        }
    )
    rule = ValuationRule(min_float_mv_yi=15.0, min_pb=0.4, max_pb=8.0)
    res = rule.apply(df)
    assert len(res) == 1
    assert res["ts_code"].iloc[0] == "000001.SZ"


def test_composite_rule_chain() -> None:
    df = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "name": ["平安", "ST股", "正常"],
            "list_date": ["19910101", "19910101", "19910101"],
            "amount": [50000.0, 50000.0, 1000.0],
            "amount_20d": [50000.0, 50000.0, 1000.0],
            "circ_mv": [2e9, 2e9, 2e9],
            "pb": [1.0, 1.0, 1.0],
        }
    )
    chain = CompositeRuleChain()
    chain.add_rule(BasicExclusionRule(exclude_st=True))
    chain.add_rule(LiquidityRule(min_daily_amount_thousand=30000.0))
    res = chain.apply(df)
    assert len(res) == 1
    assert res["ts_code"].iloc[0] == "000001.SZ"
