"""全市场聚合监控配置测试。"""

from pathlib import Path

import pytest

from stock_reporting.interpretation.market_aggregate.config import (
    load_market_aggregate_config,
)


def test_load_default_market_aggregate_config() -> None:
    config = load_market_aggregate_config()

    assert config.title == "A 股全市场实时聚合监控"
    assert config.source == "tencent"
    assert config.interval_seconds == pytest.approx(60.0)
    assert config.universe.dataset == "stock_basic"
    assert config.fetch.batch_size == 100
    assert config.cache.fresh_ttl_seconds == pytest.approx(30.0)
    assert config.thresholds.strong_move_pct == pytest.approx(5.0)
    assert config.report.metrics[0].metric_id == "coverage"
    assert config.report.metrics[-1].metric_id == "amount_top_5pct_share"


def test_load_market_aggregate_config_from_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "market_aggregate.yaml"
    config_path.write_text(
        """
market_aggregate:
  schema_version: 2
  title: "测试聚合监控"
  artifact_root: "data/test-aggregate"
  interval_seconds: 15
  universe:
    dataset: "stock_basic"
  fetch:
    batch_size: 50
  cache:
    fresh_ttl_seconds: 10
    max_age_seconds: 90
  thresholds:
    strong_move_pct: 3.5
  quality:
    min_coverage_ratio: 0.9
  report:
    template: "aggregate/market_aggregate.md.j2"
    metrics:
      - id: breadth_counts
        label: "广度"
        section: "自定义"
        enabled: true
      - id: amount_total
        label: "成交额"
        enabled: false
    limitations: ["测试限制"]
""",
        encoding="utf-8",
    )

    config = load_market_aggregate_config(config_path)

    assert config.schema_version == 2
    assert config.title == "测试聚合监控"
    assert config.interval_seconds == pytest.approx(15.0)
    assert config.universe.dataset == "stock_basic"
    assert config.fetch.batch_size == 50
    assert config.cache.max_age_seconds == pytest.approx(90.0)
    assert config.thresholds.strong_move_pct == pytest.approx(3.5)
    assert config.quality.min_coverage_ratio == pytest.approx(0.9)
    assert config.report.metrics[0].section == "自定义"
    assert not config.report.metrics[1].enabled
    assert config.report.limitations == ("测试限制",)
