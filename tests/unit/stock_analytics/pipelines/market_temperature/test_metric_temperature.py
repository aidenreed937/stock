"""市场温度指标映射测试。"""

import pytest

from stock_analytics.pipelines.market_temperature.metric_temperature import fact_temperature


@pytest.mark.parametrize(
    ("metric_id", "value", "expected"),
    [
        ("main_money_net_inflow_share_20d_cum", -0.07, 0.0),
        ("main_money_net_inflow_share_20d_cum", 0.0, 50.0),
        ("main_money_net_inflow_share_20d_cum", 0.08, 100.0),
        ("margin_balance_growth_60d", 0.02, 60.0),
    ],
)
def test_new_flow_metrics_use_declared_temperature_scales(
    metric_id: str, value: float, expected: float
) -> None:
    row = {"metric_id": metric_id, "value_float": value, "unit": "raw"}

    assert fact_temperature(row, "positive") == pytest.approx(expected)
