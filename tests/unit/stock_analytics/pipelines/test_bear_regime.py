"""熊市识别管线单元测试。"""

from datetime import date, timedelta

import polars as pl

from stock_analytics.pipelines.bear_regime import (
    BearRegimeConfig,
    identify_bear_regimes,
)


def _dates(n: int) -> list[date]:
    return [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]


def test_identify_price_bears() -> None:
    """价格引擎: 基准先涨后崩 (250日新高回撤>20% 且持续>=60交易日) 应识别出熊市。"""
    n = 260
    bench = (
        [float(100 + i) for i in range(60)]
        + [120.0 * (1 - 0.33 * (i / 149)) for i in range(150)]
        + [80.0] * 50
    )
    wide = pl.DataFrame(
        {"trade_date": _dates(n), "中证全指": bench, "macro_rotation_v5_etf": bench}
    )
    res = identify_bear_regimes(wide, risk_factors=None)
    price = res[res["识别引擎"].str.startswith("价格回撤")]
    assert not price.empty
    assert len(price["熊市区间"].unique()) == 1


def test_identify_factor_bears_filtered() -> None:
    """四低共振: 仅估值/杠杆低 (不足 3 项) 且价格处于 250 日区间高位时不应识别。"""
    n = 300
    # 价格先涨后高位横盘: 250 日滚动分位处于高位 (不低)
    bench = [float(100 + i) for i in range(200)] + [300.0] * 100
    wide = pl.DataFrame(
        {"trade_date": _dates(n), "中证全指": bench, "macro_rotation_v5_etf": bench}
    )
    risk = pl.DataFrame(
        {
            "trade_date": _dates(n),
            "dim_leverage": [30.0] * n,
            "dim_crowding": [50.0] * n,
            "dim_valuation": [30.0] * n,
        }
    )
    res = identify_bear_regimes(wide, risk_factors=risk)
    if not res.empty:
        factor = res[res["识别引擎"].str.startswith("四低共振")]
        assert factor.empty


def test_identify_factor_bears_confirmed() -> None:
    """四低共振: 估值/成交/杠杆/价格 全部低位时应识别为熊市底部。"""
    n = 300
    bench = [float(100 - i * 0.2) for i in range(n)]
    wide = pl.DataFrame(
        {"trade_date": _dates(n), "中证全指": bench, "macro_rotation_v5_etf": bench}
    )
    risk = pl.DataFrame(
        {
            "trade_date": _dates(n),
            "dim_leverage": [30.0] * n,
            "dim_crowding": [30.0] * n,
            "dim_valuation": [30.0] * n,
        }
    )
    res = identify_bear_regimes(wide, risk_factors=risk)
    factor = res[res["识别引擎"].str.startswith("四低共振")]
    assert not factor.empty
    assert {"识别引擎", "熊市区间", "区间收益", "最深回撤", "回本所需交易日"}.issubset(res.columns)


def test_custom_config_thresholds() -> None:
    """自定义配置: 提高四低共振项数要求后识别更严格。"""
    n = 300
    bench = [float(100 - i * 0.2) for i in range(n)]
    wide = pl.DataFrame(
        {"trade_date": _dates(n), "中证全指": bench, "macro_rotation_v5_etf": bench}
    )
    risk = pl.DataFrame(
        {
            "trade_date": _dates(n),
            "dim_leverage": [30.0] * n,
            "dim_crowding": [30.0] * n,
            "dim_valuation": [30.0] * n,
        }
    )
    # 要求 4 项全共振: 价格+估值+成交+杠杆 (价格分位低, 满足) -> 应识别
    cfg = BearRegimeConfig(factor_score_min=4)
    res = identify_bear_regimes(wide, risk_factors=risk, cfg=cfg)
    factor = res[res["识别引擎"].str.startswith("四低共振")]
    assert not factor.empty
