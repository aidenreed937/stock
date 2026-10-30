"""钛白粉全景管线配置加载测试。"""

from __future__ import annotations

from pathlib import Path

from stock_analytics.pipelines.tio2.config import (
    Tio2Config,
    load_tio2_config,
)


def test_load_config_from_yaml() -> None:
    config = load_tio2_config("config/analytics/tio2.yaml")
    assert isinstance(config, Tio2Config)
    assert config.schema_version == 1
    assert config.artifact_root == "data/analytics/tio2"
    assert config.inputs.trading_gates == "config/industry/chemicals/tio2/trading_gates.yaml"
    assert config.inputs.cost_models == "config/industry/chemicals/tio2/cost_models.yaml"
    assert config.inputs.capacity_projects.endswith("capacity_projects.yaml")
    assert config.regime.destocking_export_yoy == 15.0
    assert config.history.min_episode_months == 2


def test_load_config_missing_file_uses_defaults(tmp_path: Path) -> None:
    config = load_tio2_config(tmp_path / "missing.yaml")
    assert isinstance(config, Tio2Config)
    assert config.artifact_root == "data/analytics/tio2"
    assert config.title != ""
