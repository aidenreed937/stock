"""钛白粉上市公司盈利与估值反向时钟面板 Mart 单元测试。

覆盖：
1. 估值反向时钟状态机判定 (classify_valuation_regime)；
2. 钛白粉公司配置加载 (load_tio2_company_configs)；
3. 空面板与 Schema 契约完备性；
4. 季报财务与资产减值损失提取 (build_tio2_financial_panel)；
5. PIT (按公告日 ann_date) 合并无前视性与滚动估值分位计算。
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import polars as pl

from stock_analytics.marts.tio2_company_panel import (
    TIO2_COMPANY_FINANCIALS_SCHEMA,
    TIO2_COMPANY_PANEL_SCHEMA,
    build_tio2_company_panel,
    build_tio2_financial_panel,
    classify_valuation_regime,
    empty_tio2_company_financials,
    empty_tio2_company_panel,
    load_tio2_company_configs,
)


def test_classify_valuation_regime_deep_value_trough() -> None:
    # 破净且亏损
    assert classify_valuation_regime(0.85, 2.0, None, -1.5e8) == "deep_value_trough"
    # PB 10Y 分位处于 5% 极低位，PE 为空或亏损
    assert classify_valuation_regime(1.05, 5.0, None, -5.0e7) == "deep_value_trough"
    # PB 10Y 分位处于 15% 极低位，高 PE (如 45x)
    assert classify_valuation_regime(1.1, 15.0, 45.0, 1.0e6) == "deep_value_trough"


def test_classify_valuation_regime_pe_trap_peak() -> None:
    # 周期大顶：低个位数 PE (8.5x)，但 PB 极高 (3.2x，分位 95%)
    assert classify_valuation_regime(3.2, 95.0, 8.5, 3.5e9) == "pe_trap_peak"
    # PB >= 2.5 且 PE <= 12
    assert classify_valuation_regime(2.6, 80.0, 10.0, 1.0e9) == "pe_trap_peak"


def test_classify_valuation_regime_fair_expansion() -> None:
    # 戴维斯双击/合理扩张：PB 10Y 分位 50%，PE 20x，净利润正
    assert classify_valuation_regime(1.8, 50.0, 20.0, 8.0e8) == "fair_expansion"


def test_classify_valuation_regime_neutral_and_none() -> None:
    # PB 为 None
    assert classify_valuation_regime(None, None, 15.0, 1e8) == "neutral"
    # 中性状态 (如 PB 30% 分位，PE 为负但不破净)
    assert classify_valuation_regime(1.2, 30.0, None, -1e8) == "neutral"


def test_empty_panel_schemas() -> None:
    p = empty_tio2_company_panel()
    assert set(p.columns) == set(TIO2_COMPANY_PANEL_SCHEMA.keys())
    assert len(p) == 0

    f = empty_tio2_company_financials()
    assert set(f.columns) == set(TIO2_COMPANY_FINANCIALS_SCHEMA.keys())
    assert len(f) == 0


def test_load_tio2_company_configs() -> None:
    configs = load_tio2_company_configs()
    assert len(configs) >= 4
    symbols = {c["symbol"] for c in configs}
    assert {"002601.SZ", "002145.SZ", "002136.SZ", "000545.SZ"}.issubset(symbols)


def test_build_tio2_financial_panel_with_mock() -> None:
    mock_cat = MagicMock()

    mock_inc = pl.DataFrame(
        {
            "symbol": ["002601.SZ"],
            "end_date": [date(2026, 6, 30)],
            "ann_date": [date(2026, 7, 31)],
            "total_revenue": [1.4e10],
            "n_income_attr_p": [1.8e9],
            "assets_impair_loss": [-3.0e7],
        }
    )
    mock_bs = pl.DataFrame(
        {
            "symbol": ["002601.SZ"],
            "end_date": [date(2026, 6, 30)],
            "inventories": [4.5e9],
            "total_hldr_eqy_exc_min_int": [2.3e10],
        }
    )

    def load_ds(name: str, **kwargs: object) -> pl.DataFrame:
        if name == "income":
            return mock_inc
        if name == "balancesheet":
            return mock_bs
        return pl.DataFrame()

    mock_cat.load_dataset.side_effect = load_ds

    res = build_tio2_financial_panel(
        mock_cat,
        companies=[
            {
                "symbol": "002601.SZ",
                "name": "龙佰集团",
                "process_type": "chloride_and_sulfate",
                "cost_tier": "lowest_alpha",
                "role": "integrated_oligopoly_leader",
                "tio2_revenue_share_approx": 0.54,
            }
        ],
    )

    assert len(res) == 1
    row = res.to_dicts()[0]
    assert row["symbol"] == "002601.SZ"
    assert row["company_name"] == "龙佰集团"
    assert row["net_profit_attr_p"] == 1.8e9
    assert row["assets_impair_loss"] == -3.0e7
    assert row["inventories"] == 4.5e9
    assert row["total_equity"] == 2.3e10


def test_build_tio2_company_panel_pit() -> None:
    """验证按 ann_date 实行 PIT 无前视合并。"""
    mock_cat = MagicMock()

    # 财报于 2026-07-31 公告
    mock_inc = pl.DataFrame(
        {
            "symbol": ["002601.SZ"],
            "end_date": [date(2026, 6, 30)],
            "ann_date": [date(2026, 7, 31)],
            "total_revenue": [1.4e10],
            "n_income_attr_p": [1.8e9],
            "assets_impair_loss": [-3.0e7],
        }
    )
    mock_bs = pl.DataFrame(
        {
            "symbol": ["002601.SZ"],
            "end_date": [date(2026, 6, 30)],
            "inventories": [4.5e9],
            "total_hldr_eqy_exc_min_int": [2.3e10],
        }
    )

    # 日频数据：公告前 2026-07-30 与公告后 2026-08-03
    mock_daily = pl.DataFrame(
        {
            "symbol": ["002601.SZ", "002601.SZ"],
            "trade_date": [date(2026, 7, 30), date(2026, 8, 3)],
            "close": [18.0, 18.5],
            "total_mv": [4.3e10, 4.4e10],
            "circ_mv": [4.3e10, 4.4e10],
            "turnover_rate": [1.2, 1.5],
            "pb": [1.8, 1.85],
            "pe_ttm": [15.0, 15.5],
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

    panel = build_tio2_company_panel(
        mock_cat,
        companies=[
            {
                "symbol": "002601.SZ",
                "name": "龙佰集团",
                "process_type": "chloride_and_sulfate",
                "cost_tier": "lowest_alpha",
                "role": "integrated_oligopoly_leader",
                "annual_capacity_w_tons": 151.0,
                "tio2_revenue_share_approx": 0.54,
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
    assert rows[1]["net_profit_attr_p"] == 1.8e9
