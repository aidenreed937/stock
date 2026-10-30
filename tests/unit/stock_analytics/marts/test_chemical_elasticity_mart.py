"""化工大宗周期核心上市公司业绩与估值弹性 Mart 单元测试。

覆盖：
1. 弹性画像配置加载与增值税率默认值；
2. 量化金融工程核心公式准确性（增值税 13% 扣除、实际所得税率、净外售折减、EPS 增厚）；
3. 构建化学品业绩弹性 Mart 与 Schema 契约验证；
4. 自定义多品种价格跳涨/暴跌多情景模拟器 (simulate_spot_price_shocks)。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import polars as pl
import pytest

from stock_analytics.marts.chemical_elasticity_mart import (
    CHEMICAL_ELASTICITY_SCHEMA,
    build_chemical_elasticity_mart,
    load_company_elasticity_config,
    simulate_spot_price_shocks,
)


def test_load_company_elasticity_config() -> None:
    # 验证旧单体配置文件已彻底废弃不存在
    assert not Path("config/industry/chemicals/company_elasticities.yaml").exists()

    vat_rate, companies = load_company_elasticity_config()
    assert vat_rate == 0.13
    assert len(companies) >= 25

    # 验证关键品种覆盖
    commodity_codes = {c["commodity_code"] for c in companies}
    expected_codes = {
        "SA",
        "TA",
        "POY",
        "TIO2",
        "MDI",
        "TDI",
        "MA",
        "UR",
        "R32",
        "R134A",
        "MEG",
        "V",
    }
    assert expected_codes.issubset(commodity_codes)


def test_math_elasticity_formulas() -> None:
    # 验证增值税扣除与 EPS 弹性理论公式
    # 设定：价格跳变 100 元/吨含税，增值税 13%，有效所得税 15%
    # 净外售产能 100 万吨，总股本 10 亿股 (100,000 万股)
    vat = 0.13
    tax = 0.15
    delta_p_inc = 100.0
    delta_p_ex = delta_p_inc / (1.0 + vat)

    net_cap_w = 100.0
    total_shares_w = 100000.0

    profit_delta_cny = delta_p_ex * (net_cap_w * 10000.0) * (1.0 - tax)
    profit_delta_100m = profit_delta_cny / 1.0e8
    eps_delta = profit_delta_cny / (total_shares_w * 10000.0)

    # 88.495575 * 1,000,000 * 0.85 = 75,221,238.94 CNY => 0.7522 亿元
    assert pytest.approx(profit_delta_100m, rel=1e-3) == 0.7522
    assert pytest.approx(eps_delta, rel=1e-3) == 0.0752


def test_build_chemical_elasticity_mart_mock_catalog(tmp_path: Path) -> None:
    mock_catalog = MagicMock()

    # 模拟两家公司的 daily_basic 行情
    daily_mock = pl.DataFrame(
        {
            "symbol": ["000683.SZ", "000822.SZ"],
            "trade_date": [date(2026, 9, 15), date(2026, 9, 15)],
            "close": [6.50, 4.20],
            "total_share": [371683.0, 107508.0],
            "total_mv": [24159395000.0, 4515336000.0],
            "pe_ttm": [22.0, 15.0],
            "pb": [1.8, 0.95],
        }
    )
    mock_catalog.load_dataset.return_value = daily_mock

    out_dir = tmp_path / "mart_test"
    mart_df = build_chemical_elasticity_mart(
        catalog=mock_catalog,
        output_dir=out_dir,
    )

    assert not mart_df.is_empty()
    # 验证 Schema 契约完备
    for col_name, col_type in CHEMICAL_ELASTICITY_SCHEMA.items():
        assert col_name in mart_df.columns
        assert mart_df.schema[col_name] == col_type

    # 验证落盘文件生成
    assert (out_dir / "chemical_elasticity_mart.parquet").exists()
    assert (out_dir / "chemical_elasticity_mart_latest.csv").exists()


def test_simulate_spot_price_shocks() -> None:
    base_df = pl.DataFrame(
        {
            "symbol": ["000683.SZ", "600346.SH"],
            "commodity_code": ["SA", "TA"],
            "profit_delta_100m_per_100cny": [3.2345, 9.0279],
            "eps_delta_per_100cny": [0.0870, 0.1283],
        }
    )

    shocks = {"SA": 300.0, "TA": -100.0}
    sim_df = simulate_spot_price_shocks(base_df, shocks)

    # SA 跳涨 300: 增厚 3 倍
    sa_row = sim_df.filter(pl.col("commodity_code") == "SA").to_dicts()[0]
    assert pytest.approx(sa_row["custom_profit_delta_100m"], rel=1e-3) == 9.7035
    assert pytest.approx(sa_row["custom_eps_delta"], rel=1e-3) == 0.2610

    # TA 下跌 100: 缩减 -1 倍
    ta_row = sim_df.filter(pl.col("commodity_code") == "TA").to_dicts()[0]
    assert pytest.approx(ta_row["custom_profit_delta_100m"], rel=1e-3) == -9.0279
    assert pytest.approx(ta_row["custom_eps_delta"], rel=1e-3) == -0.1283
