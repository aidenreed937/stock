from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.industry_trend.config import (
    IndustryTrendConfig,
    load_industry_trend_config,
)
from stock_analytics.pipelines.industry_trend.factor_panel import (
    build_industry_trend_panel,
    load_latest_industry_trend_panel,
    save_industry_trend_panel,
)
from stock_data.core.runtime import DataRuntimeContext

_PANEL_COLUMNS = {
    "trade_date",
    "industry_code",
    "industry_name",
    "direction_score",
    "supply_demand_score",
    "bargaining_score",
    "prosperity_score",
    "crowding_score",
    "composite_trend_score",
    "trend_momentum",
}


def _write_panel_mart(tmp_path: Path) -> None:
    """构造最小 industry_panel_daily.parquet：3 行业 1 交易日。"""
    mart_dir = tmp_path / "curated" / "mart"
    mart_dir.mkdir(parents=True, exist_ok=True)
    d = date(2026, 8, 25)
    df = pl.DataFrame(
        {
            "as_of_date": [d, d, d],
            "industry_code": ["801010.SI", "801030.SI", "801050.SI"],
            "industry_name": ["农林牧渔", "基础化工", "有色金属"],
            "forecast_positive_share": [0.8, 0.6, 0.4],
            "express_profit_growth_median": [30.0, 20.0, 10.0],
            "revenue_growth_ttm": [10.0, 15.0, -5.0],
            "profit_growth_ttm": [30.0, 20.0, 10.0],
            "tcr_percentile": [20.0, 50.0, 80.0],
            "amount_yi": [100.0, 200.0, 300.0],
        }
    )
    df.write_parquet(mart_dir / "industry_panel_daily.parquet")


def test_load_config_defaults() -> None:
    config = load_industry_trend_config("config/analytics/industry_trend_tracking.yaml")
    assert isinstance(config, IndustryTrendConfig)
    assert config.trend_lookback == 63
    assert abs(config.weights["prosperity"] - 2.0 / 3.0) < 1e-3
    assert abs(config.weights["crowding"] - 1.0 / 3.0) < 1e-3
    assert config.weights["direction"] == 0.0


def test_build_industry_trend_panel_three_layer(tmp_path: Path) -> None:
    _write_panel_mart(tmp_path)
    panel = build_industry_trend_panel(runtime=DataRuntimeContext.from_root(tmp_path))
    assert _PANEL_COLUMNS.issubset(panel.columns)
    assert len(panel) == 3

    by_code = {row["industry_code"]: row for row in panel.to_dicts()}
    # 供需层：量价齐升（A=100, B=50 双增速之和分位）> 供给收缩（C 惩罚 20）
    assert by_code["801010.SI"]["supply_demand_score"] == 100.0
    assert by_code["801030.SI"]["supply_demand_score"] == 50.0
    assert by_code["801050.SI"]["supply_demand_score"] == 20.0
    # 议价权层：量价齐升门内按净利−营收增速分位（A=100, B=0），门外中性 30
    assert by_code["801010.SI"]["bargaining_score"] == 100.0
    assert by_code["801030.SI"]["bargaining_score"] == 0.0
    assert by_code["801050.SI"]["bargaining_score"] == 30.0
    # 方向层：数据缺口 → 中性 50
    assert all(row["direction_score"] == 50.0 for row in panel.to_dicts())
    # 复合得分与环比均为 0-100 数值
    for row in panel.to_dicts():
        assert 0.0 <= row["composite_trend_score"] <= 100.0
        assert row["prosperity_score"] >= 0.0


def test_build_industry_trend_panel_runs_on_real_mart() -> None:
    panel = build_industry_trend_panel(start_date=date(2026, 8, 1))
    assert not panel.is_empty()
    assert _PANEL_COLUMNS.issubset(panel.columns)
    assert panel["industry_code"].n_unique() >= 10


def test_direction_defensive_gate_penalizes_risk_quadrant(tmp_path: Path) -> None:
    """方向高位 × 非量价齐升 → composite 防守减分；方向中性时不减分。"""
    # 因子层防守门默认关闭（改由策略层过滤），此测试显式开启
    import yaml

    cfg_payload = yaml.safe_load(
        Path("config/analytics/industry_trend_tracking.yaml").read_text(encoding="utf-8")
    )
    cfg_payload["direction_defensive_gate"] = True
    cfg_tmp = tmp_path / "gate_on.yaml"
    cfg_tmp.write_text(yaml.dump(cfg_payload, allow_unicode=True), encoding="utf-8")

    mart_dir = tmp_path / "curated" / "mart"
    mart_dir.mkdir(parents=True, exist_ok=True)
    d = date(2026, 8, 25)
    # 供给收缩行业（营收负、净利正 = 非量价齐升）
    pl.DataFrame(
        {
            "as_of_date": [d],
            "industry_code": ["801050.SI"],
            "industry_name": ["有色金属"],
            "forecast_positive_share": [0.6],
            "express_profit_growth_median": [20.0],
            "revenue_growth_ttm": [-5.0],
            "profit_growth_ttm": [10.0],
            "tcr_percentile": [30.0],
            "amount_yi": [100.0],
        }
    ).write_parquet(mart_dir / "industry_panel_daily.parquet")

    # 方向高位映射
    pl.DataFrame(
        {
            "trade_date": [d],
            "industry_code": ["801050.SI"],
            "direction_score": [90.0],
        }
    ).write_parquet(mart_dir / "global_resonance_map.parquet")

    panel = build_industry_trend_panel(
        config_path=cfg_tmp, runtime=DataRuntimeContext.from_root(tmp_path)
    )
    row = panel.row(0, named=True)
    assert row["direction_score"] == 90.0
    # 单行业横截面分位为空 → fc/ex 中性 50，prosperity=50
    baseline = 2.0 / 3.0 * row["prosperity_score"] + 1.0 / 3.0 * (100.0 - row["crowding_score"])
    assert row["composite_trend_score"] <= baseline - 10.0  # 防守减分约 20

    # 对照：direction 中性（50 < 66）→ 不减分
    pl.DataFrame(
        {
            "trade_date": [d],
            "industry_code": ["801050.SI"],
            "direction_score": [50.0],
        }
    ).write_parquet(mart_dir / "global_resonance_map.parquet")
    panel2 = build_industry_trend_panel(
        config_path=cfg_tmp, runtime=DataRuntimeContext.from_root(tmp_path)
    )
    row2 = panel2.row(0, named=True)
    assert row2["composite_trend_score"] > row["composite_trend_score"]


def test_save_and_load_industry_trend_panel(tmp_path: Path) -> None:
    panel = pl.DataFrame(
        {
            "trade_date": [date(2026, 8, 25), date(2026, 8, 26)],
            "industry_code": ["801010.SI", "801010.SI"],
            "industry_name": ["农林牧渔", "农林牧渔"],
            "direction_score": [50.0, 50.0],
            "supply_demand_score": [80.0, 82.0],
            "bargaining_score": [60.0, 61.0],
            "prosperity_score": [70.0, 72.0],
            "crowding_score": [30.0, 31.0],
            "composite_trend_score": [65.0, 66.0],
            "trend_momentum": [1.0, 2.0],
        }
    )
    save_industry_trend_panel(panel, output_dir=tmp_path, as_of=date(2026, 8, 26))
    _run_dir, loaded, _manifest = load_latest_industry_trend_panel(artifact_root=tmp_path)
    assert len(loaded) == 2
    assert loaded["industry_code"].to_list() == ["801010.SI", "801010.SI"]
