"""市场温度计配置加载测试。"""

from pathlib import Path

from stock.analytics.pipelines.market_temperature.config import load_market_temperature_config


def test_load_market_temperature_config(tmp_path: Path) -> None:
    config_path = tmp_path / "market_temperature.yaml"
    config_path.write_text(
        """
market_temperature:
  schema_version: 1
  title: "测试温度计"
  artifact_root: "data/analytics/market_temperature"
  main_window: 20
  short_windows: [5, 10]
  metric_values:
    enabled: false
  dimensions:
    - id: valuation
      name: "估值面"
      weight: 0.2
      metrics:
        - metric_id: valuation_temperature
          aggregation: mean
        - metric_id: fs_profit_growth_temperature
          source: derived
          weight: 0.25
  datasets:
    - data_source: tushare
      dataset: stock_daily_bar
      dimension: technical
      required: true
      max_lag_days: 1
      cadence: trading_daily
      quality_tier: core
    - data_source: tushare
      dataset: opt_basic
      dimension: sentiment
      static: true
      cadence: static
      quality_tier: background
  bands:
    temperature_levels:
      low_opportunity: 25.0
      cool_observation: 45.0
      neutral_rotation: 65.0
      warm_recovery: 85.0
    pressure_levels:
      moderate: 35.0
      high_moderate: 55.0
      high: 75.0
    delta_levels:
      stable: 2.0
      moderate: 4.0
      significant: 15.0
""",
        encoding="utf-8",
    )

    config = load_market_temperature_config(config_path)

    assert config.title == "测试温度计"
    assert config.main_window == 20
    assert config.short_windows == (5, 10)
    assert not config.metric_values.enabled
    assert config.dimensions[0].metrics[0].metric_id == "valuation_temperature"
    assert config.dimensions[0].metrics[0].source == "metric_engine"
    assert config.dimensions[0].metrics[1].source == "derived"
    assert config.dimensions[0].metrics[1].weight == 0.25
    assert config.datasets[0].dataset == "stock_daily_bar"
    assert config.datasets[0].max_lag_days == 1
    assert config.datasets[0].cadence == "trading_daily"
    assert config.datasets[0].quality_tier == "core"
    assert config.datasets[1].dataset == "opt_basic"
    assert config.datasets[1].static is True
    assert config.datasets[1].cadence == "static"
    assert config.bands.temperature_levels.low_opportunity == 25.0
    assert config.bands.pressure_levels.high == 75.0
    assert config.bands.delta_levels.significant == 15.0
