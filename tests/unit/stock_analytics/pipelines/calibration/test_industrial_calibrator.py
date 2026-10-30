"""工业单耗倒轧求解器与置信带宽单元测试 (IndustrialCostCalibrator)。"""

import pytest

from stock_analytics.pipelines.calibration.industrial_calibrator import (
    CalibrationResult,
    ConfidenceBandResult,
    IndustrialCostCalibrator,
)


@pytest.fixture
def calibrator() -> IndustrialCostCalibrator:
    return IndustrialCostCalibrator(drift_threshold_pct=8.0)


def test_calibrate_healthy(calibrator: IndustrialCostCalibrator) -> None:
    """测试工业单耗与财报高度吻合的健康状态。"""
    # 假设年产销 55 万吨，钛矿 2200 元/吨，硫酸 280 元/吨
    # 标称矿成本: 0.65 * 900 + 0.35 * 2.3 * 2200 = 585 + 1771 = 2356 元/吨
    # 标称酸成本: 3.0 * 280 = 840 元/吨
    # 标称固定制费: 6600 元/吨
    # 理论总成本: 2356 + 840 + 6600 = 9796 元/吨
    # 55 万吨对应总成本: 550,000 * 9796 = 53.878 亿元
    res = calibrator.calibrate_sulfate_tio2(
        symbol="002601.SZ",
        company_name="龙佰集团",
        reported_sales_cny=8.525e9,  # 85.25 亿营收 (均价 15500 元/吨 -> 55 万吨)
        reported_cost_cny=5.3878e9,
        ore_market_price=2200.0,
        acid_market_price=280.0,
        nominal_ore_captive_ratio=0.65,
        nominal_ore_captive_cost=900.0,
        nominal_fixed_cost=6600.0,
        spot_tio2_price=15500.0,
    )

    assert isinstance(res, CalibrationResult)
    assert res.drift_status == "HEALTHY"
    assert abs(res.cost_bias_pct) <= 1.0
    assert res.implied_captive_ratio is not None
    assert 0.60 <= res.implied_captive_ratio <= 0.70
    assert res.implied_fixed_cost_cny is not None
    assert 6500 <= res.implied_fixed_cost_cny <= 6700


def test_calibrate_drift_upward(calibrator: IndustrialCostCalibrator) -> None:
    """测试成本超预期上升导致的向上漂移预警。"""
    # 实际成本显著走高 (例如动力煤电辅料大涨，单位成本达 12000 元/吨)
    res = calibrator.calibrate_sulfate_tio2(
        symbol="002601.SZ",
        company_name="龙佰集团",
        reported_sales_cny=8.525e9,
        reported_cost_cny=6.60e9,  # 实际总成本 66 亿 -> 单吨 12000 元
        ore_market_price=2200.0,
        acid_market_price=280.0,
        spot_tio2_price=15500.0,
    )

    assert res.drift_status == "DRIFT_UPWARD"
    assert res.cost_bias_pct > 8.0
    assert "显著高于模型标称" in res.details
    # 自给率被稀释反推
    assert res.implied_captive_ratio is not None
    assert res.implied_captive_ratio < 0.65


def test_calibrate_drift_downward(calibrator: IndustrialCostCalibrator) -> None:
    """测试超额技改降本或自产矿增加导致的向下漂移。"""
    # 实际成本显著优异 (单吨仅 8500 元/吨)
    res = calibrator.calibrate_sulfate_tio2(
        symbol="002601.SZ",
        company_name="龙佰集团",
        reported_sales_cny=8.525e9,
        reported_cost_cny=4.675e9,  # 单吨 8500 元
        ore_market_price=2200.0,
        acid_market_price=280.0,
        spot_tio2_price=15500.0,
    )

    assert res.drift_status == "DRIFT_DOWNWARD"
    assert res.cost_bias_pct < -8.0
    assert "显著优于模型标称" in res.details


def test_compute_eps_confidence_band(calibrator: IndustrialCostCalibrator) -> None:
    """测试矿石自给率与动力制费双重波动下的 EPS 置信带宽测算。"""
    band = calibrator.compute_eps_confidence_band(
        symbol="002601.SZ",
        company_name="龙佰集团",
        scenario_key="mid_cycle",
        nominal_eps=1.25,
        annual_capacity_w_tons=65.0,
        total_shares=2.38e9,
        ore_market_price=2200.0,
        nominal_ore_consumption=2.3,
        nominal_ore_captive_cost=900.0,
        nominal_fixed_cost=6600.0,
        captive_ratio_delta=0.10,
        fixed_cost_delta=0.10,
    )

    assert isinstance(band, ConfidenceBandResult)
    assert band.nominal_eps == 1.25
    # 下界必然低于基准，上界必然高于基准
    assert band.low_eps < band.nominal_eps
    assert band.high_eps > band.nominal_eps
    assert band.bandwidth_pct > 0.0

    # 验证 3x3 敏感性二维矩阵
    assert len(band.sensitivity_grid) == 3
    base_row = next(r for r in band.sensitivity_grid if "基准" in r["fixed_cost_scenario"])
    assert base_row["captive_base"] == 1.25
    assert base_row["captive_+10%"] > 1.25
    assert base_row["captive_-10%"] < 1.25


def test_render_markdown_section(calibrator: IndustrialCostCalibrator) -> None:
    """测试研报 Markdown 片段渲染。"""
    res = calibrator.calibrate_sulfate_tio2(
        symbol="002601.SZ",
        company_name="龙佰集团",
        reported_sales_cny=8.525e9,
        reported_cost_cny=5.3878e9,
        ore_market_price=2200.0,
        acid_market_price=280.0,
    )
    band = calibrator.compute_eps_confidence_band(
        symbol="002601.SZ",
        company_name="龙佰集团",
        scenario_key="mid_cycle",
        nominal_eps=1.25,
        annual_capacity_w_tons=65.0,
        total_shares=2.38e9,
        ore_market_price=2200.0,
    )

    md = calibrator.render_markdown_section([res], [band])
    assert "### 工业单耗动态倒轧校准与置信带宽" in md
    assert "龙佰集团" in md
    assert "健康吻合" in md
    assert "二维参数置信带宽推演" in md


def test_invalid_sales_cost(calibrator: IndustrialCostCalibrator) -> None:
    """测试非法财务输入时的防御性异常。"""
    with pytest.raises(ValueError, match="营业收入与营业成本必须大于 0"):
        calibrator.calibrate_sulfate_tio2(
            symbol="002601.SZ",
            company_name="龙佰集团",
            reported_sales_cny=0.0,
            reported_cost_cny=-100.0,
            ore_market_price=2200.0,
            acid_market_price=280.0,
        )
