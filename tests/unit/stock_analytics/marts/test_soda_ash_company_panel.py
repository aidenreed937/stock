"""纯碱上市公司盈利与估值反向时钟面板 Mart 单元测试。

覆盖：
1. 估值反向时钟状态机判定 (classify_valuation_regime)；
2. 纯碱公司配置加载 (load_soda_ash_company_configs)；
3. 空面板与 Schema 契约完备性；
4. 季报财务与资产减值损失提取 (build_soda_ash_financial_panel)；
5. PIT (按公告日 ann_date) 合并无前视性与滚动估值分位计算。
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import polars as pl

from stock_analytics.marts.soda_ash_company_panel import (
    SODA_ASH_COMPANY_FINANCIALS_SCHEMA,
    SODA_ASH_COMPANY_PANEL_SCHEMA,
    build_company_timeline_frame,
    build_soda_ash_company_panel,
    build_soda_ash_financial_panel,
    classify_valuation_regime,
    empty_soda_ash_company_financials,
    empty_soda_ash_company_panel,
    load_soda_ash_company_configs,
)


def test_classify_valuation_regime_deep_value_trough() -> None:
    # 破净且亏损 (如中盐化工 2026 最新状态)
    assert classify_valuation_regime(0.79, 1.67, None, -2.72e8) == "deep_value_trough"
    # PB 10Y 分位处于 2.7% 极低位，PE 为空
    assert classify_valuation_regime(1.01, 2.7, None, -7.46e7) == "deep_value_trough"
    # PB 10Y 分位处于 10% 极低位，高 PE (数十倍以上，如 45x)
    assert classify_valuation_regime(1.1, 10.0, 45.0, 1.0e6) == "deep_value_trough"


def test_classify_valuation_regime_pe_trap_peak() -> None:
    # 周期大顶：低个位数 PE (7.5x)，但 PB 极高 (3.5x，分位 95%)
    assert classify_valuation_regime(3.5, 95.0, 7.5, 1.5e9) == "pe_trap_peak"
    # PB >= 2.5 且 PE <= 10
    assert classify_valuation_regime(2.8, 80.0, 8.2, 5.0e8) == "pe_trap_peak"


def test_classify_valuation_regime_fair_expansion() -> None:
    # 戴维斯双击/合理扩张：PB 10Y 分位 50%，PE 20x，净利润正
    assert classify_valuation_regime(1.8, 50.0, 20.0, 8.0e8) == "fair_expansion"


def test_classify_valuation_regime_neutral_and_none() -> None:
    # PB 为 None
    assert classify_valuation_regime(None, None, 15.0, 1e8) == "neutral"
    # 中性状态 (如 PB 30% 分位，PE 为负但不破净)
    assert classify_valuation_regime(1.2, 30.0, None, -1e8) == "neutral"


def test_empty_panel_schemas() -> None:
    p = empty_soda_ash_company_panel()
    assert set(p.columns) == set(SODA_ASH_COMPANY_PANEL_SCHEMA.keys())
    assert len(p) == 0

    f = empty_soda_ash_company_financials()
    assert set(f.columns) == set(SODA_ASH_COMPANY_FINANCIALS_SCHEMA.keys())
    assert len(f) == 0


def test_load_soda_ash_company_configs() -> None:
    configs = load_soda_ash_company_configs()
    assert len(configs) >= 5
    symbols = {c["symbol"] for c in configs}
    assert {"000683.SZ", "000822.SZ", "600328.SH", "600409.SH", "000707.SZ"}.issubset(symbols)


def test_build_soda_ash_financial_panel_with_mock() -> None:
    mock_cat = MagicMock()

    mock_inc = pl.DataFrame(
        {
            "symbol": ["000683.SZ"],
            "end_date": [date(2026, 6, 30)],
            "ann_date": [date(2026, 7, 31)],
            "total_revenue": [6.03e9],
            "n_income_attr_p": [8.34e8],
            "assets_impair_loss": [-1.14e7],
        }
    )
    mock_bs = pl.DataFrame(
        {
            "symbol": ["000683.SZ"],
            "end_date": [date(2026, 6, 30)],
            "inventories": [9.79e8],
            "total_hldr_eqy_exc_min_int": [1.23e10],
        }
    )

    def load_ds(name: str, **kwargs: object) -> pl.DataFrame:
        if name == "income":
            return mock_inc
        if name == "balancesheet":
            return mock_bs
        return pl.DataFrame()

    mock_cat.load_dataset.side_effect = load_ds

    res = build_soda_ash_financial_panel(
        mock_cat,
        companies=[
            {
                "symbol": "000683.SZ",
                "name": "远兴能源",
                "process_type": "natural_alkali",
                "cost_tier": "lowest_alpha",
                "soda_revenue_share_approx": 0.65,
            }
        ],
    )

    assert len(res) == 1
    row = res.to_dicts()[0]
    assert row["symbol"] == "000683.SZ"
    assert row["company_name"] == "远兴能源"
    assert row["net_profit_attr_p"] == 8.34e8
    assert row["assets_impair_loss"] == -1.14e7
    assert row["inventories"] == 9.79e8
    assert row["total_equity"] == 1.23e10


def test_build_soda_ash_company_panel_pit() -> None:
    """验证按 ann_date 实行 PIT 无前视合并。"""
    mock_cat = MagicMock()

    # 财报于 2026-07-31 公告
    mock_inc = pl.DataFrame(
        {
            "symbol": ["000683.SZ"],
            "end_date": [date(2026, 6, 30)],
            "ann_date": [date(2026, 7, 31)],
            "total_revenue": [6.03e9],
            "n_income_attr_p": [8.34e8],
            "assets_impair_loss": [-1.14e7],
        }
    )
    mock_bs = pl.DataFrame(
        {
            "symbol": ["000683.SZ"],
            "end_date": [date(2026, 6, 30)],
            "inventories": [9.79e8],
            "total_hldr_eqy_exc_min_int": [1.23e10],
        }
    )

    # 日频数据：公告前 2026-07-30 与公告后 2026-08-01
    mock_daily = pl.DataFrame(
        {
            "symbol": ["000683.SZ", "000683.SZ"],
            "trade_date": [date(2026, 7, 30), date(2026, 8, 3)],
            "close": [6.0, 6.2],
            "total_mv": [2.2e10, 2.3e10],
            "circ_mv": [2.2e10, 2.3e10],
            "turnover_rate": [1.5, 1.8],
            "pb": [1.8, 1.85],
            "pe_ttm": [22.0, 22.5],
        }
    )

    def load_ds(name: str, **kwargs: object) -> pl.DataFrame:
        if name == "daily_basic":
            return mock_daily
        if name == "income":
            return mock_inc
        if name == "balancesheet":
            return mock_bs
        return pl.DataFrame()

    mock_cat.load_dataset.side_effect = load_ds

    panel = build_soda_ash_company_panel(
        mock_cat,
        companies=[
            {
                "symbol": "000683.SZ",
                "name": "远兴能源",
                "process_type": "natural_alkali",
                "cost_tier": "lowest_alpha",
                "annual_capacity_w_tons": 500.0,
                "soda_revenue_share_approx": 0.65,
            }
        ],
    )

    rows = panel.sort("trade_date").to_dicts()
    assert len(rows) == 2

    # 公告日前：2026-07-30 不能拿到 2026-06-30 的中报数据 (无前视性)
    assert rows[0]["trade_date"] == date(2026, 7, 30)
    assert rows[0]["fin_report_date"] is None
    assert rows[0]["net_profit_attr_p"] is None

    # 公告日后：2026-08-03 成功生效
    assert rows[1]["trade_date"] == date(2026, 8, 3)
    assert rows[1]["fin_report_date"] == date(2026, 6, 30)
    assert rows[1]["net_profit_attr_p"] == 8.34e8
    assert rows[1]["assets_impair_loss"] == -1.14e7


def test_build_soda_ash_financial_panel_with_dynamic_fina_mainbz() -> None:
    """验证从 fina_mainbz 真实主营业务构成表中动态提取纯碱营收占比并前向填充。"""
    mock_cat = MagicMock()

    # 包含中报 (2025-06-30)、三季报 (2025-09-30，通常不拆解产品)、年报 (2025-12-31)
    mock_inc = pl.DataFrame(
        {
            "symbol": ["000683.SZ", "000683.SZ", "000683.SZ", "000707.SZ"],
            "end_date": [
                date(2025, 6, 30),
                date(2025, 9, 30),
                date(2025, 12, 31),
                date(2025, 6, 30),
            ],
            "ann_date": [
                date(2025, 8, 8),
                date(2025, 10, 28),
                date(2026, 4, 21),
                date(2025, 8, 22),
            ],
            "total_revenue": [5.0e9, 8.0e9, 1.2e10, 1.0e9],
            "n_income_attr_p": [1.0e9, 1.5e9, 2.0e9, 5.0e7],
            "assets_impair_loss": [0.0, 0.0, -1.0e7, 0.0],
        }
    )
    mock_bs = pl.DataFrame(
        {
            "symbol": ["000683.SZ", "000683.SZ", "000683.SZ", "000707.SZ"],
            "end_date": [
                date(2025, 6, 30),
                date(2025, 9, 30),
                date(2025, 12, 31),
                date(2025, 6, 30),
            ],
            "inventories": [5.0e8, 6.0e8, 7.0e8, 2.0e8],
            "total_hldr_eqy_exc_min_int": [1.0e10, 1.1e10, 1.2e10, 3.0e9],
        }
    )
    # fina_mainbz:
    # 000683 在 2025-06-30 纯碱 sales 3.0e9 (3.0/5.0 = 60%)
    # 000683 在 2025-12-31 纯碱 sales 7.44e9 (7.44/12.0 = 62%)
    # 000707 在 2025-06-30 联碱及其他化工产品 sales 9.0e8 (9.0/10.0 = 90%)
    mock_mbz = pl.DataFrame(
        {
            "symbol": ["000683.SZ", "000683.SZ", "000683.SZ", "000683.SZ", "000707.SZ"],
            "end_date": [
                date(2025, 6, 30),
                date(2025, 6, 30),
                date(2025, 12, 31),
                date(2025, 12, 31),
                date(2025, 6, 30),
            ],
            "bz_item": [
                "纯碱",
                "小苏打",
                "纯碱",
                "尿素",
                "联碱及其他化工产品",
            ],
            "bz_sales": [3.0e9, 5.0e8, 7.44e9, 2.0e9, 9.0e8],
            "bz_code": ["P", "P", "P", "P", "P"],
        }
    )

    def load_ds(name: str, **kwargs: object) -> pl.DataFrame:
        if name == "income":
            return mock_inc
        if name == "balancesheet":
            return mock_bs
        if name == "fina_mainbz":
            return mock_mbz
        return pl.DataFrame()

    mock_cat.load_dataset.side_effect = load_ds

    res = build_soda_ash_financial_panel(
        mock_cat,
        companies=[
            {
                "symbol": "000683.SZ",
                "name": "远兴能源",
                "process_type": "natural_alkali",
                "cost_tier": "lowest_alpha",
                "soda_product_keywords": ["纯碱"],
                "soda_revenue_share_approx": 0.50,
            },
            {
                "symbol": "000707.SZ",
                "name": "双环科技",
                "process_type": "hou_process",
                "cost_tier": "hou_double_ton",
                "soda_product_keywords": ["纯碱", "联碱"],
                "soda_revenue_share_approx": 0.50,
            },
        ],
    )

    assert len(res) == 4
    rows_by_sym = {(r["symbol"], r["end_date"]): r for r in res.to_dicts()}

    # 1. 000683 2025-06-30: 动态计算 3.0e9 / 5.0e9 = 0.60
    r1 = rows_by_sym[("000683.SZ", date(2025, 6, 30))]
    assert abs(r1["soda_revenue_share"] - 0.60) < 1e-4
    assert abs(r1["soda_revenue_share_approx"] - 0.60) < 1e-4

    # 2. 000683 2025-09-30 (三季报无细分): 前向填充 0.60，绝不退化至配置的 0.50
    r2 = rows_by_sym[("000683.SZ", date(2025, 9, 30))]
    assert abs(r2["soda_revenue_share"] - 0.60) < 1e-4

    # 3. 000683 2025-12-31: 动态计算 7.44e9 / 1.2e10 = 0.62
    r3 = rows_by_sym[("000683.SZ", date(2025, 12, 31))]
    assert abs(r3["soda_revenue_share"] - 0.62) < 1e-4

    # 4. 000707 2025-06-30: 匹配“联碱及其他化工产品” 9.0e8 / 1.0e9 = 0.90
    r4 = rows_by_sym[("000707.SZ", date(2025, 6, 30))]
    assert abs(r4["soda_revenue_share"] - 0.90) < 1e-4


def test_build_company_timeline_frame() -> None:
    """验证从 YAML 加载并展开纯碱上市公司历史时间轴。"""
    configs = load_soda_ash_company_configs()
    timeline_df = build_company_timeline_frame(configs)

    assert not timeline_df.is_empty()
    assert "symbol" in timeline_df.columns
    assert "effective_date" in timeline_df.columns
    assert "annual_capacity_w_tons" in timeline_df.columns
    assert "equity_ratio" in timeline_df.columns

    # 1. 远兴能源 000683.SZ 历史演进检查
    yx_rows = timeline_df.filter(pl.col("symbol") == "000683.SZ").sort("effective_date").to_dicts()
    assert len(yx_rows) >= 8

    # 2000-01-01 历史回溯基准与 2016 初始基地 (180 万吨，权益 1.0)
    assert yx_rows[0]["effective_date"] == date(2000, 1, 1)
    assert yx_rows[0]["annual_capacity_w_tons"] == 180.0
    assert yx_rows[0]["equity_ratio"] == 1.0
    assert yx_rows[1]["effective_date"] == date(2016, 1, 1)
    assert yx_rows[1]["annual_capacity_w_tons"] == 180.0
    assert yx_rows[1]["equity_ratio"] == 1.0

    # 2021 设立银根矿业，权益 0.60
    assert yx_rows[2]["effective_date"] == date(2021, 1, 1)
    assert yx_rows[2]["equity_ratio"] == 0.60

    # 2022 重组受让 26% 股权，权益 0.86
    assert yx_rows[3]["effective_date"] == date(2022, 12, 1)
    assert yx_rows[3]["equity_ratio"] == 0.86

    # 2023-06-28 一期 1 线投料：桐柏老基地 180 + 150 = 330 万吨
    assert yx_rows[4]["effective_date"] == date(2023, 6, 28)
    assert yx_rows[4]["annual_capacity_w_tons"] == 330.0

    # 一期 2/3/4 线逐线投料，与 capacity_projects.yaml 的 actual_start 严格对齐
    assert yx_rows[5]["effective_date"] == date(2023, 11, 20)
    assert yx_rows[5]["annual_capacity_w_tons"] == 480.0
    assert yx_rows[6]["effective_date"] == date(2024, 1, 22)
    assert yx_rows[6]["annual_capacity_w_tons"] == 580.0
    assert yx_rows[7]["effective_date"] == date(2024, 5, 30)
    assert yx_rows[7]["annual_capacity_w_tons"] == 680.0
    assert yx_rows[7]["equity_ratio"] == 0.86

    # 2. 中盐化工 600328.SH 重组前后产能切换检查
    zy_rows = timeline_df.filter(pl.col("symbol") == "600328.SH").sort("effective_date").to_dicts()
    assert len(zy_rows) >= 3
    assert zy_rows[0]["effective_date"] == date(2000, 1, 1)
    assert zy_rows[0]["annual_capacity_w_tons"] == 30.0
    assert zy_rows[1]["annual_capacity_w_tons"] == 30.0
    assert zy_rows[2]["annual_capacity_w_tons"] == 390.0
    assert zy_rows[2]["effective_date"] == date(2019, 12, 25)


def test_build_soda_ash_company_panel_point_in_time_timeline() -> None:
    """验证跨周期日频行情下，公司产能与权益按时间轴精确 PIT 匹配（零前视）。"""
    mock_cat = MagicMock()

    # 远兴能源在 2018、2021、2023、2024 四个历史交易日，以及中盐化工重组前后的历史交易日
    mock_daily = pl.DataFrame(
        {
            "symbol": [
                "000683.SZ",
                "000683.SZ",
                "000683.SZ",
                "000683.SZ",
                "600328.SH",
                "600328.SH",
            ],
            "trade_date": [
                date(2018, 5, 2),
                date(2021, 6, 1),
                date(2023, 8, 1),
                date(2024, 3, 1),
                date(2018, 5, 2),
                date(2024, 3, 1),
            ],
            "close": [3.0, 4.0, 6.5, 7.0, 8.0, 7.5],
            "total_mv": [1.0e10, 1.5e10, 2.5e10, 2.8e10, 8.0e9, 1.8e10],
            "circ_mv": [1.0e10, 1.5e10, 2.5e10, 2.8e10, 8.0e9, 1.8e10],
            "turnover_rate": [1.0, 1.2, 2.0, 1.5, 0.8, 1.1],
            "pb": [1.2, 1.4, 2.0, 2.1, 1.1, 0.9],
            "pe_ttm": [15.0, 18.0, 20.0, 22.0, 16.0, 12.0],
        }
    )

    def load_ds(name: str, **kwargs: object) -> pl.DataFrame:
        if name == "daily_basic":
            return mock_daily
        return pl.DataFrame()

    mock_cat.load_dataset.side_effect = load_ds

    panel = build_soda_ash_company_panel(mock_cat)
    assert not panel.is_empty()

    rows_by_key = {(r["symbol"], r["trade_date"]): r for r in panel.to_dicts()}

    # 1. 远兴 2018-05-02: 处于 2016-01-01 节点，产能 180 万吨，权益 1.0
    r_2018 = rows_by_key[("000683.SZ", date(2018, 5, 2))]
    assert r_2018["annual_capacity_w_tons"] == 180.0
    assert r_2018["equity_ratio"] == 1.0

    # 2. 远兴 2021-06-01: 处于 2021-01-01 节点，产能 180 万吨，权益 0.60
    r_2021 = rows_by_key[("000683.SZ", date(2021, 6, 1))]
    assert r_2021["annual_capacity_w_tons"] == 180.0
    assert r_2021["equity_ratio"] == 0.60

    # 3. 远兴 2023-08-01: 处于 2023-06-28 节点，产能增至 330 万吨，权益 0.86
    r_2023 = rows_by_key[("000683.SZ", date(2023, 8, 1))]
    assert r_2023["annual_capacity_w_tons"] == 330.0
    assert r_2023["equity_ratio"] == 0.86

    # 4. 远兴 2024-03-01: 处于 2024-01-22 节点 (一期3线已投料)，产能 580 万吨，权益 0.86
    r_2024 = rows_by_key[("000683.SZ", date(2024, 3, 1))]
    assert r_2024["annual_capacity_w_tons"] == 580.0
    assert r_2024["equity_ratio"] == 0.86

    # 5. 中盐化工 2018-05-02 (重组前兰太实业): 产能 30 万吨
    r_zy_2018 = rows_by_key[("600328.SH", date(2018, 5, 2))]
    assert r_zy_2018["annual_capacity_w_tons"] == 30.0

    # 6. 中盐化工 2024-03-01 (重组后注入纯碱资产): 产能 390 万吨
    r_zy_2024 = rows_by_key[("600328.SH", date(2024, 3, 1))]
    assert r_zy_2024["annual_capacity_w_tons"] == 390.0
