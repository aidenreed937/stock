"""光伏设备（630500）周期状态与防守信号特征面板管线。

本层（stock_analytics）产出的是**特征（feature / 状态）**——回测/决策的输入，
不是已验证的有效因子；有效性由 stock_strategy 验证层确认。
注意：光伏供需剪刀差腿已证伪，本管线不生产化失效的剪刀差腿，只生产化验证通过的
**产能周期状态 + 财报 TTM 防守 + 价格回撤补丁**特征。
"""

from __future__ import annotations

from stock_analytics.pipelines.photovoltaic.config import (
    DEFAULT_CONFIG_PATH,
    CycleStateConfig,
    DefenseWeightConfig,
    FinDefenseConfig,
    PhotovoltaicLegsConfig,
    PricePatchConfig,
    load_photovoltaic_legs_config,
)
from stock_analytics.pipelines.photovoltaic.legs import (
    build_cycle_state,
    build_fin_defense,
    build_photovoltaic_legs_panel,
    build_price_drawdown,
    load_calendar,
)
from stock_analytics.pipelines.photovoltaic.pipeline import (
    PhotovoltaicLegsPipeline,
    PhotovoltaicLegsRunResult,
    load_latest_photovoltaic_legs,
    run_photovoltaic_legs,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "CycleStateConfig",
    "DefenseWeightConfig",
    "FinDefenseConfig",
    "PhotovoltaicLegsConfig",
    "PhotovoltaicLegsPipeline",
    "PhotovoltaicLegsRunResult",
    "PricePatchConfig",
    "build_cycle_state",
    "build_fin_defense",
    "build_photovoltaic_legs_panel",
    "build_price_drawdown",
    "load_calendar",
    "load_latest_photovoltaic_legs",
    "load_photovoltaic_legs_config",
    "run_photovoltaic_legs",
]
