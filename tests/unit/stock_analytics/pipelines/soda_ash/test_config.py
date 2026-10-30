"""纯碱全景管线配置加载测试。"""

from __future__ import annotations

from stock_analytics.pipelines.soda_ash.config import (
    SodaAshConfig,
    load_soda_ash_config,
)


def test_load_config_from_yaml() -> None:
    config = load_soda_ash_config("config/analytics/soda_ash.yaml")
    assert isinstance(config, SodaAshConfig)
    assert config.schema_version == 1
    assert config.artifact_root == "data/analytics/soda_ash"
    assert (
        config.inputs.capacity_projects
        == "config/industry/chemicals/soda_ash/capacity_projects.yaml"
    )
    assert config.inputs.trading_gates == "config/industry/chemicals/soda_ash/trading_gates.yaml"
    assert config.inputs.cost_models == "config/industry/chemicals/soda_ash/cost_models.yaml"
    assert config.inputs.nbs_soda_ash_csv.endswith("nbs_soda_ash_monthly.csv")
    assert config.regime.basis_speculative_cny == -40.0
    assert config.history.min_episode_months == 2


def test_load_config_missing_file_uses_defaults(tmp_path) -> None:
    config = load_soda_ash_config(tmp_path / "missing.yaml")
    assert isinstance(config, SodaAshConfig)
    assert config.artifact_root == "data/analytics/soda_ash"
    assert config.title != ""
