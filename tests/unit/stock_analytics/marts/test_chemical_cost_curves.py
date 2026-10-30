"""化工多工艺供给成本曲线与边际出清分位 Mart 单元测试。

覆盖：
1. 成本阶梯产能覆盖率计算 (calc_coverage_percentile) 及其单调性与边界；
2. 供给成本曲线与出清分位 Mart 构建 (build_chemical_cost_curves_mart) 与 Schema 契约；
3. 工艺成本阶梯 (Merit Order) 排序与累积产能 100% 封闭性；
4. 跌破边际高成本装置现金流保本线时的左侧见底反转信号 (bottom_signal_triggered) 触发。
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from stock_analytics.marts.chemical_cost_curves import (
    LADDER_SCHEMA,
    SUMMARY_SCHEMA,
    build_chemical_cost_curves_mart,
    calc_coverage_percentile,
)


def test_calc_coverage_percentile() -> None:
    # 模拟纯碱三工艺成本与产能分布: 天然碱 15% (950元), 联碱 45% (1550元), 氨碱 40% (1750元)
    points = [(950.0, 15.0), (1550.0, 45.0), (1750.0, 40.0)]

    # 极低价格: 覆盖 0%
    assert calc_coverage_percentile(points, 700.0) == 0.0

    # 极高价格: 覆盖 100%
    assert calc_coverage_percentile(points, 2200.0) == 100.0

    # 中间价格测试
    cov_1000 = calc_coverage_percentile(points, 1000.0)
    cov_1600 = calc_coverage_percentile(points, 1600.0)
    assert 0.0 < cov_1000 < cov_1600 < 100.0


def test_build_chemical_cost_curves_mart_mock(tmp_path: Path) -> None:
    out_dir = tmp_path / "cost_curves_test"

    # 模拟纯碱跌破边际现金成本 (1000元 < 1480元现金保本)，PTA处于超额暴利 (7000元 > 5200元)
    custom_spots = {
        "SA": 1000.0,
        "TA": 7000.0,
        "MEG": 6500.0,
        "V": 4500.0,
    }

    summary_df, ladder_df = build_chemical_cost_curves_mart(
        spot_prices_override=custom_spots,
        output_dir=out_dir,
    )

    assert not summary_df.is_empty()
    assert not ladder_df.is_empty()

    # 验证 Schema 契约
    for col, c_type in SUMMARY_SCHEMA.items():
        assert col in summary_df.columns
        assert summary_df.schema[col] == c_type

    for col, c_type in LADDER_SCHEMA.items():
        assert col in ladder_df.columns
        assert ladder_df.schema[col] == c_type

    # 验证落盘
    assert (out_dir / "chemical_cost_curves.parquet").exists()
    assert (out_dir / "chemical_process_cost_ladders.parquet").exists()

    # 验证纯碱触发左侧见底信号
    sa_summary = summary_df.filter(pl.col("commodity_code") == "SA").to_dicts()[0]
    assert sa_summary["bottom_signal_triggered"] is True
    assert sa_summary["curve_regime"] == "deep_cash_drain_bottom"
    assert sa_summary["spread_vs_marginal_cash_cost"] < 0.0

    # 验证 PTA 为超额暴利
    ta_summary = summary_df.filter(pl.col("commodity_code") == "TA").to_dicts()[0]
    assert ta_summary["bottom_signal_triggered"] is False
    assert ta_summary["curve_regime"] == "super_profit"


def test_cost_ladders_monotonicity_and_closure() -> None:
    # 验证所有品种各工艺的累积产能最终闭合于 100%
    summary_df, ladder_df = build_chemical_cost_curves_mart()

    for sym in summary_df["commodity_code"].to_list():
        sym_ladders = ladder_df.filter(pl.col("commodity_code") == sym)
        assert not sym_ladders.is_empty()

        # 验证完全成本升序排序
        costs = sym_ladders["full_cost_cny"].to_list()
        assert costs == sorted(costs)

        # 验证累积产能最终闭合到 100%
        final_cum = sym_ladders["cum_capacity_share_pct"].to_list()[-1]
        assert pytest.approx(final_cum, abs=0.1) == 100.0


def test_cost_models_versioning_date_filter(tmp_path: Path) -> None:
    from datetime import date

    # 1. 回测 2021 年: 纯碱天然碱法 (2023生效) 应当被过滤排除 (防前视偏差)
    _, ladder_2021 = build_chemical_cost_curves_mart(
        as_of_date=date(2021, 6, 1), output_dir=tmp_path / "2021"
    )
    sa_2021_routes = ladder_2021.filter(pl.col("commodity_code") == "SA")["process_key"].to_list()
    assert "natural_alkali" not in sa_2021_routes
    assert "solvay_process" in sa_2021_routes
    assert "hou_process" in sa_2021_routes
    # 产能重新归一化到 100%
    sa_2021_cum = ladder_2021.filter(pl.col("commodity_code") == "SA")[
        "cum_capacity_share_pct"
    ].to_list()[-1]
    assert pytest.approx(sa_2021_cum, abs=0.1) == 100.0

    # 2. 2023 年试车期: 命中阶段一切片 (全国原始占比 8%, 付现加工费 220)
    _, ladder_2023 = build_chemical_cost_curves_mart(
        as_of_date=date(2023, 10, 1), output_dir=tmp_path / "2023"
    )
    sa_2023_na = ladder_2023.filter(
        (pl.col("commodity_code") == "SA") & (pl.col("process_key") == "natural_alkali")
    ).row(0, named=True)
    assert sa_2023_na is not None

    # 3. 2025 年一期达产期: 命中阶段二切片 (全国原始占比 15%, 付现加工费 180)
    _, ladder_2025 = build_chemical_cost_curves_mart(
        as_of_date=date(2025, 5, 1), output_dir=tmp_path / "2025"
    )
    sa_2025_na = ladder_2025.filter(
        (pl.col("commodity_code") == "SA") & (pl.col("process_key") == "natural_alkali")
    ).row(0, named=True)
    assert (
        pytest.approx(sa_2023_na["cash_cost_cny"] - sa_2025_na["cash_cost_cny"], abs=0.01) == 40.0
    )

    # 4. 实盘 2026 年二期重塑期: 命中阶段三切片 (全国原始占比 22%, 付现加工费 160)
    _, ladder_2026 = build_chemical_cost_curves_mart(
        as_of_date=date(2026, 9, 18), output_dir=tmp_path / "2026"
    )
    sa_2026_routes = ladder_2026.filter(pl.col("commodity_code") == "SA")["process_key"].to_list()
    assert "natural_alkali" in sa_2026_routes
    assert len(sa_2026_routes) == 3
    sa_2026_na = ladder_2026.filter(
        (pl.col("commodity_code") == "SA") & (pl.col("process_key") == "natural_alkali")
    ).row(0, named=True)
    assert (
        pytest.approx(sa_2025_na["cash_cost_cny"] - sa_2026_na["cash_cost_cny"], abs=0.01) == 20.0
    )


def test_cost_models_timeline_mode(tmp_path: Path) -> None:
    from datetime import date

    import yaml

    # 构造带 timeline 时间线的模拟工艺配置
    mock_yaml = {
        "schema_version": 1,
        "product_name": "测试化工品",
        "symbol": "TEST_CHEM",
        "models": {
            "advanced_route": {
                "name": "先进时间线工艺",
                # 顶层永久单耗
                "coefficients": {"thermal_coal": 0.28},
                # 时间线切片
                "timeline": [
                    {
                        "valid_from": "2021-01-01",
                        "valid_to": "2024-12-31",
                        "cash_fixed_cost": 180.0,
                        "fixed_cost": 320.0,
                        "national_capacity_share": 0.10,
                        "cost_tier": "lowest_alpha",
                    },
                    {
                        "valid_from": "2025-01-01",
                        "valid_to": "9999-12-31",
                        "cash_fixed_cost": 210.0,
                        "fixed_cost": 360.0,
                        "national_capacity_share": 0.20,
                        "cost_tier": "lowest_alpha",
                    },
                ],
            }
        },
    }

    cfg_file = tmp_path / "test_cost_models.yaml"
    cfg_file.write_text(yaml.dump(mock_yaml), encoding="utf-8")

    custom_configs = {"TEST_CHEM": cfg_file}

    # 1. 2023 年评估：应当命中第一切片 (加工费 180)
    _, ladder_2023 = build_chemical_cost_curves_mart(
        as_of_date=date(2023, 6, 1),
        config_paths=custom_configs,
        output_dir=tmp_path / "out_2023",
    )
    row_2023 = ladder_2023.row(0, named=True)
    assert row_2023["process_key"] == "advanced_route"
    assert pytest.approx(row_2023["cum_capacity_share_pct"], abs=0.1) == 100.0

    # 2. 2026 年评估：应当命中第二切片 (加工费 210, 增量 30 元)
    _, ladder_2026 = build_chemical_cost_curves_mart(
        as_of_date=date(2026, 9, 1),
        config_paths=custom_configs,
        output_dir=tmp_path / "out_2026",
    )
    row_2026 = ladder_2026.row(0, named=True)
    # 相比 2023 年切片，现金成本刚好增加 30.0 元 (210 - 180)
    assert pytest.approx(row_2026["cash_cost_cny"] - row_2023["cash_cost_cny"], abs=0.01) == 30.0

    # 3. 2020 年评估：早于 2021-01-01，不在任何切片内，应当被跳过
    _, ladder_2020 = build_chemical_cost_curves_mart(
        as_of_date=date(2020, 6, 1),
        config_paths=custom_configs,
        output_dir=tmp_path / "out_2020",
    )
    assert ladder_2020.is_empty()
