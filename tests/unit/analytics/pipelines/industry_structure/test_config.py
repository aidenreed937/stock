"""行业结构分析配置加载测试。"""

from pathlib import Path

from stock_reporting.interpretation.industry_structure.config import load_industry_structure_config


def test_load_industry_structure_config(tmp_path: Path) -> None:
    config_path = tmp_path / "industry_structure.yaml"
    config_path.write_text(
        """
industry_structure:
  schema_version: 1
  title: "测试行业结构"
  artifact_root: "data/analytics/industry_structure"
  main_window: 20
  short_windows: [5, 10]
  medium_windows: [60, 120]
  classification: "SW2021"
  benchmark: "000985"
  score_weights:
    momentum: 0.4
    valuation: 0.2
    fundamental: 0.2
    crowding: 0.2
  fundamental_blend:
    stale_after_days: 90
    official_weight: 0.7
    fast_weight: 0.3
    stale_official_weight: 0.4
    stale_fast_weight: 0.6
  datasets:
    - data_source: tushare
      dataset: sw_daily
      required: true
      max_lag_days: 1
      cadence: trading_daily
      quality_tier: core
    - data_source: tushare
      dataset: index_classify
      static: true
      cadence: static
      quality_tier: core
  thresholds:
    crowded_threshold: 25.0
    weak_fundamental_score: 35.0
    breadth_share20_strong: 0.65
    breadth_share60_weak: 0.30
    breadth_share60_healthy: 0.55
    score_top_structure: 80.0
    score_crowded_risk: 65.0
    score_lagging: 55.0
""",
        encoding="utf-8",
    )

    config = load_industry_structure_config(config_path)

    assert config.title == "测试行业结构"
    assert config.main_window == 20
    assert config.short_windows == (5, 10)
    assert config.medium_windows == (60, 120)
    assert config.windows == (5, 10, 20, 60, 120)
    assert config.score_weights.momentum == 0.4
    assert config.fundamental_blend.stale_after_days == 90
    assert config.fundamental_blend.stale_fast_weight == 0.6
    assert config.datasets[0].dataset == "sw_daily"
    assert config.datasets[0].required
    assert config.datasets[0].cadence == "trading_daily"
    assert config.datasets[0].quality_tier == "core"
    assert config.datasets[1].static
    assert config.datasets[1].cadence == "static"
    assert config.thresholds.crowded_threshold == 25.0
    assert config.thresholds.weak_fundamental_score == 35.0
    assert config.thresholds.breadth_share20_strong == 0.65
    assert config.thresholds.score_top_structure == 80.0
