"""化工海关出口高频映射与外需表观需求 Mart 单元测试。

覆盖：
1. 出口外需景气四象限状态机判定 (_classify_export_regime)；
2. 构建海关出口 Mart (build_chemical_customs_export_mart) 与 Schema 契约验证；
3. 出口依存度 (Export Dependency) 与表观消费量核心计算逻辑；
4. 最新月份摘要提取 (get_latest_chemical_export_summary)。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_analytics.marts.chemical_customs_export import (
    CHEMICAL_CUSTOMS_EXPORT_SCHEMA,
    _classify_export_regime,
    build_chemical_customs_export_mart,
    get_latest_chemical_export_summary,
)


def test_classify_export_regime() -> None:
    # 量价齐升 (量增 > 10%, 均价涨)
    assert _classify_export_regime(15.0, 5.0) == "export_boom"
    # 量增价跌 (以价换量抢份额)
    assert _classify_export_regime(20.0, -3.0) == "volume_driven"
    # 价涨量缩 (供给受阻/成本推升)
    assert _classify_export_regime(-5.0, 8.0) == "price_driven"
    # 量价双弱
    assert _classify_export_regime(-10.0, -2.0) == "export_contraction"
    # 稳态
    assert _classify_export_regime(5.0, 2.0) == "stable"
    # 空值防御
    assert _classify_export_regime(None, 5.0) == "neutral"


def test_build_chemical_customs_export_mart_mock(tmp_path: Path) -> None:
    gacc_mock_path = tmp_path / "mock_gacc.parquet"
    market_mock_path = tmp_path / "mock_market.parquet"
    out_dir = tmp_path / "mart_out"

    # 模拟 GACC 海关出口数据 (钛白粉与纯碱两个月)
    gacc_mock = pl.DataFrame(
        {
            "report_month": ["2026-06", "2026-07", "2026-06", "2026-07"],
            "trade_date": [
                date(2026, 6, 30),
                date(2026, 7, 31),
                date(2026, 6, 30),
                date(2026, 7, 31),
            ],
            "product_name": ["钛白粉", "钛白粉", "纯碱", "纯碱"],
            "export_volume": [1.0e8, 1.2e8, 2.0e8, 2.5e8],  # 1.0e8 kg = 10 万吨
            "export_value_usd": [2.0e8, 2.5e8, 3.0e7, 3.5e7],  # 2.0 亿美元
        }
    )
    gacc_mock.write_parquet(gacc_mock_path)

    # 模拟 NBS 实物产量数据 (纯碱产量)
    market_mock = pl.DataFrame(
        {
            "report_month": ["2026-06", "2026-07"],
            "trade_date": [date(2026, 6, 30), date(2026, 7, 31)],
            "soda_ash_production": [300.0, 320.0],  # 万吨
            "plate_glass_production": [8000.0, 8500.0],  # 万重量箱
        }
    )
    market_mock.write_parquet(market_mock_path)

    mart_df = build_chemical_customs_export_mart(
        gacc_path=gacc_mock_path,
        market_path=market_mock_path,
        output_dir=out_dir,
    )

    assert not mart_df.is_empty()

    # 验证 Schema 契约完备
    for col, c_type in CHEMICAL_CUSTOMS_EXPORT_SCHEMA.items():
        assert col in mart_df.columns
        assert mart_df.schema[col] == c_type

    # 验证文件落盘
    assert (out_dir / "chemical_customs_export.parquet").exists()
    assert (out_dir / "chemical_customs_export_latest.csv").exists()

    # 验证纯碱在 2026-07 的计算结果
    sa_07 = mart_df.filter(
        (pl.col("commodity_code") == "SA") & (pl.col("report_month") == "2026-07")
    ).to_dicts()[0]

    # 出口量 2.5e8 kg = 25.0 万吨
    assert pytest.approx(sa_07["export_volume_w_tons"], rel=1e-3) == 25.0
    # 出口额 35.0 百万美元
    assert pytest.approx(sa_07["export_value_m_usd"], rel=1e-3) == 35.0
    # 离岸均价: 35.0 / 25.0 * 100 = 140.0 美元/吨
    assert pytest.approx(sa_07["export_asp_usd_ton"], rel=1e-3) == 140.0
    # NBS 纯碱产量 320 万吨 => 出口依存度: 25.0 / 320.0 * 100% = 7.81%
    assert pytest.approx(sa_07["export_dependency_pct"], rel=1e-2) == 7.81
    # 纯碱表观消费量: 320.0 - 25.0 = 295.0 万吨
    assert pytest.approx(sa_07["apparent_consumption_w_tons"], rel=1e-3) == 295.0
    # 平板玻璃拉动: 8500 * 0.01 = 85.0 万吨
    assert pytest.approx(sa_07["derived_terminal_demand_w_tons"], rel=1e-3) == 85.0


def test_build_chemical_customs_export_mart_excludes_import_rows(tmp_path: Path) -> None:
    """出口口径回归：import 行不得混入 Mart 出口量价（2026-09-20 修复）。"""
    gacc_mock_path = tmp_path / "mock_gacc.parquet"
    out_dir = tmp_path / "mart_out"

    gacc_mock = pl.DataFrame(
        {
            "report_month": ["2026-07", "2026-07"],
            "trade_date": [date(2026, 7, 31), date(2026, 7, 31)],
            "product_name": ["钛白粉", "钛白粉"],
            "trade_direction": ["export", "import"],
            "export_volume": [1.2e8, 5.0e6],  # 12 万吨出口 + 5 千吨进口
            "export_value_usd": [2.5e8, 1.0e7],
        }
    )
    gacc_mock.write_parquet(gacc_mock_path)

    mart_df = build_chemical_customs_export_mart(
        gacc_path=gacc_mock_path,
        market_path=tmp_path / "missing.parquet",
        output_dir=out_dir,
    )

    row = mart_df.filter(
        (pl.col("commodity_code") == "TiO2") & (pl.col("report_month") == "2026-07")
    ).to_dicts()[0]
    # 只含出口 12 万吨 / 2.5 亿美元，进口行被剔除
    assert pytest.approx(row["export_volume_w_tons"], rel=1e-3) == 12.0
    assert pytest.approx(row["export_value_m_usd"], rel=1e-3) == 250.0
    assert pytest.approx(row["export_asp_usd_ton"], rel=1e-3) == 2083.33


def test_get_latest_chemical_export_summary(tmp_path: Path) -> None:
    sample_df = pl.DataFrame(
        {
            "report_month": ["2026-05", "2026-06", "2026-05", "2026-06"],
            "commodity_code": ["SA", "SA", "TiO2", "TiO2"],
            "export_volume_w_tons": [20.0, 25.0, 12.0, 15.0],
        }
    )
    summary = get_latest_chemical_export_summary(sample_df)
    assert len(summary) == 2
    # 验证提取的都是 2026-06 最新月
    assert set(summary["report_month"].to_list()) == {"2026-06"}
