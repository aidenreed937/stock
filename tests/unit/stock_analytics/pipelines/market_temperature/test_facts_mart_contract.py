"""市场温度指标与宽表特征绑定契约测试。"""

from stock_analytics.features.builtin_specs import get_all_builtin_specs
from stock_analytics.marts.shared.market_temperature.facts_mart import _MARKET_DAILY_COLUMN_MAP


def test_market_daily_bindings_are_declared_by_feature_specs() -> None:
    expected = {
        metric_id: spec.feature_id
        for spec in get_all_builtin_specs()
        if spec.is_materialized_wide
        for metric_id in spec.market_metric_ids
    }

    assert expected == _MARKET_DAILY_COLUMN_MAP
    assert _MARKET_DAILY_COLUMN_MAP["advance_share"] == "advance_ratio"
    assert _MARKET_DAILY_COLUMN_MAP["main_money_net_inflow_share"] == "main_net_inflow_ratio"
