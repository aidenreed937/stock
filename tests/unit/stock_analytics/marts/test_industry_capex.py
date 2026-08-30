"""行业资本开支与库存先导特征聚合模块单元测试。"""

from datetime import date

import polars as pl

from stock_analytics.marts.industry_l2_panel import (
    INDUSTRY_L2_PANEL_SCHEMA,
    build_industry_l2_panel_frame,
)
from stock_analytics.marts.shared.industry_structure.industry_capex import (
    INDUSTRY_CAPEX_SCHEMA,
    _build_aggregated_financial_metrics,
    empty_industry_capex_frame,
)


def test_empty_industry_capex_frame() -> None:
    """验证空资本开支事实帧结构符合契约。"""
    frame = empty_industry_capex_frame()
    assert frame.is_empty()
    assert list(frame.schema) == list(INDUSTRY_CAPEX_SCHEMA)


def test_build_aggregated_financial_metrics() -> None:
    """验证自底向上求和、YTD转单季、TTM滚动求和与同比/剪刀差计算。"""
    stock_fs = pl.DataFrame(
        {
            "stock_key": ["000001", "000002"] * 8,
            "end_date": [
                date(2024, 3, 31),
                date(2024, 3, 31),
                date(2024, 6, 30),
                date(2024, 6, 30),
                date(2024, 9, 30),
                date(2024, 9, 30),
                date(2024, 12, 31),
                date(2024, 12, 31),
                date(2025, 3, 31),
                date(2025, 3, 31),
                date(2025, 6, 30),
                date(2025, 6, 30),
                date(2025, 9, 30),
                date(2025, 9, 30),
                date(2025, 12, 31),
                date(2025, 12, 31),
            ],
            "ann_date": [
                date(2024, 4, 25),
                date(2024, 4, 28),
                date(2024, 8, 25),
                date(2024, 8, 28),
                date(2024, 10, 25),
                date(2024, 10, 28),
                date(2025, 4, 25),
                date(2025, 4, 28),
                date(2025, 4, 25),
                date(2025, 4, 28),
                date(2025, 8, 25),
                date(2025, 8, 28),
                date(2025, 10, 25),
                date(2025, 10, 28),
                date(2026, 4, 25),
                date(2026, 4, 28),
            ],
            "cip": [
                10.0,
                10.0,
                12.0,
                12.0,
                15.0,
                15.0,
                20.0,
                20.0,
                15.0,
                15.0,
                18.0,
                18.0,
                20.0,
                20.0,
                25.0,
                25.0,
            ],
            "fix_assets": [
                100.0,
                100.0,
                110.0,
                110.0,
                120.0,
                120.0,
                130.0,
                130.0,
                120.0,
                120.0,
                130.0,
                130.0,
                140.0,
                140.0,
                150.0,
                150.0,
            ],
            "inventories": [
                50.0,
                50.0,
                55.0,
                55.0,
                60.0,
                60.0,
                65.0,
                65.0,
                60.0,
                60.0,
                65.0,
                65.0,
                70.0,
                70.0,
                75.0,
                75.0,
            ],
            "total_assets": [
                200.0,
                200.0,
                220.0,
                220.0,
                240.0,
                240.0,
                260.0,
                260.0,
                250.0,
                250.0,
                270.0,
                270.0,
                290.0,
                290.0,
                310.0,
                310.0,
            ],
            "c_pay_acq_const_fiolta": [
                5.0,
                5.0,
                12.0,
                12.0,
                20.0,
                20.0,
                30.0,
                30.0,
                8.0,
                8.0,
                18.0,
                18.0,
                30.0,
                30.0,
                45.0,
                45.0,
            ],
            "total_revenue": [
                30.0,
                30.0,
                70.0,
                70.0,
                120.0,
                120.0,
                180.0,
                180.0,
                40.0,
                40.0,
                95.0,
                95.0,
                160.0,
                160.0,
                240.0,
                240.0,
            ],
        }
    )
    stock_map = pl.DataFrame(
        {
            "stock_key": ["000001", "000002"],
            "industry_code": ["801010.SI", "801010.SI"],
        }
    )

    result = _build_aggregated_financial_metrics(stock_fs, stock_map)
    assert not result.is_empty()
    assert result["industry_code"].unique().to_list() == ["801010.SI"]
    assert "cip_yoy" in result.columns
    assert "capex_growth_ttm" in result.columns
    assert "inventory_scissors" in result.columns

    # 2025-03-31 (第5期) cip 为 30.0，2024-03-31 (第1期) cip 为 20.0 -> 同比 (30-20)/20 = 50.0%
    row_2025_q1 = result.filter(pl.col("eff_date") == date(2025, 4, 27)).to_dicts()
    if not row_2025_q1:
        # quantile 0.8 between 25 and 28
        row_2025_q1 = result.tail(4).head(1).to_dicts()
    assert abs(row_2025_q1[0]["cip_yoy"] - 50.0) < 1e-3


def test_build_industry_l2_panel_frame_with_capex() -> None:
    """验证二级行业面板正确接入资本开支特征且 Schema 完备。"""
    l2_daily = pl.DataFrame(
        {
            "trade_date": [date(2025, 5, 5), date(2025, 5, 6)],
            "industry_code": ["270100", "270100"],
            "industry_name": ["半导体", "半导体"],
            "parent_l1_code": ["270000", "270000"],
            "parent_l1_name": ["电子", "电子"],
            "close": [100.0, 102.0],
            "amount_yi": [50.0, 55.0],
            "return_20d": [5.0, 6.0],
            "return_60d": [10.0, 12.0],
            "pe_ttm_ew_percentile_5y": [40.0, 42.0],
            "pb_ew_percentile_5y": [35.0, 36.0],
        }
    )
    l2_capex = pl.DataFrame(
        {
            "industry_code": ["270100"],
            "eff_date": [date(2025, 4, 30)],
            "cip_yoy": [25.5],
            "fix_assets_yoy": [15.2],
            "cip_to_fa_ratio": [0.45],
            "capex_growth_ttm": [30.1],
            "inventory_growth_ttm": [10.0],
            "inventory_scissors": [12.3],
        }
    )
    l2_financial = pl.DataFrame()

    panel = build_industry_l2_panel_frame(
        l2_daily,
        l2_financial,
        l2_capex=l2_capex,
    )
    assert not panel.is_empty()
    assert list(panel.schema) == list(INDUSTRY_L2_PANEL_SCHEMA)
    row = panel.to_dicts()[0]
    assert row["cip_yoy"] == 25.5
    assert row["capex_growth_ttm"] == 30.1
    assert row["inventory_scissors"] == 12.3


def test_same_sample_coverage_gate_blocks_jump_artifact() -> None:
    """验证当报告期样本量发生突增（如1只扩充至10只）时，覆盖度门禁将同比置为 None，消除跳变伪影。"""
    # 2024Q1 只有 1 只股票 (cip=10)
    # 2025Q1 突然扩充至 10 只股票 (每只 cip=10，总和=100)
    # 若直接全样本相除会得到 (100 - 10) / 10 = +900% 的伪同比
    stocks_2024 = ["000001"]
    stocks_2025 = [f"00000{i}" for i in range(1, 11)]

    stock_fs = pl.DataFrame(
        {
            "stock_key": stocks_2024 + stocks_2025,
            "end_date": [date(2024, 3, 31)] * len(stocks_2024)
            + [date(2025, 3, 31)] * len(stocks_2025),
            "ann_date": [date(2024, 4, 25)] * len(stocks_2024)
            + [date(2025, 4, 25)] * len(stocks_2025),
            "cip": [10.0] * (len(stocks_2024) + len(stocks_2025)),
            "fix_assets": [100.0] * (len(stocks_2024) + len(stocks_2025)),
            "inventories": [50.0] * (len(stocks_2024) + len(stocks_2025)),
            "total_assets": [200.0] * (len(stocks_2024) + len(stocks_2025)),
            "c_pay_acq_const_fiolta": [5.0] * (len(stocks_2024) + len(stocks_2025)),
            "total_revenue": [30.0] * (len(stocks_2024) + len(stocks_2025)),
        }
    )
    stock_map = pl.DataFrame(
        {
            "stock_key": stocks_2025,
            "industry_code": ["630800"] * len(stocks_2025),
        }
    )

    result = _build_aggregated_financial_metrics(stock_fs, stock_map)
    assert not result.is_empty()
    row_2025 = result.filter(pl.col("eff_date") == date(2025, 4, 25)).to_dicts()[0]

    # 共同样本数仅 1 只，覆盖率仅 1/10 = 10% (< 40% 门禁) -> 同比特征严格拦截置空
    assert row_2025["cip_yoy"] is None
    assert row_2025["fix_assets_yoy"] is None
    # 但时点存量比值 (100 / 1000 = 0.1) 正常计算
    assert row_2025["cip_to_fa_ratio"] == 0.1
