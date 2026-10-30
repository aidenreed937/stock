"""纯碱 (Soda Ash / SA) 全景基本面对账管线。

串联 8 层核心事实源（NBS 产量/产能事件/下游玻璃/海关出口/库存分层/理论利润/
资金博弈/公司面板），产出全景事实表与数据驱动研报；产物经 ArtifactStore 落盘
``runs/`` + ``latest/`` + ``manifest.json``。
"""

from __future__ import annotations

from stock_analytics.pipelines.soda_ash.config import (
    DEFAULT_CONFIG_PATH,
    HistoryConfig,
    InputsConfig,
    RegimeThresholds,
    SodaAshConfig,
    load_soda_ash_config,
)
from stock_analytics.pipelines.soda_ash.gates import evaluate_trading_gates, load_trading_gates
from stock_analytics.pipelines.soda_ash.market_sources import (
    load_company_panel,
    load_futures_daily,
    load_hold_rank,
    load_spot_benchmark,
    load_spreads,
)
from stock_analytics.pipelines.soda_ash.panorama import (
    aggregate_capacity_by_month,
    classify_flow_regime,
    detect_regime_episodes,
    merge_monthly_panorama,
)
from stock_analytics.pipelines.soda_ash.pipeline import (
    SodaAshPipeline,
    SodaAshRunResult,
    load_latest_soda_ash_panorama,
    run_soda_ash_pipeline,
)
from stock_analytics.pipelines.soda_ash.report import FLOW_REGIME_CN, render_markdown
from stock_analytics.pipelines.soda_ash.sources import (
    calculate_implied_shipment_rate,
    load_capacity_projects,
    load_customs_export,
    load_factory_inventory,
    load_nbs_plate_glass,
    load_nbs_soda_ash,
    load_warehouse_receipts,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "FLOW_REGIME_CN",
    "HistoryConfig",
    "InputsConfig",
    "RegimeThresholds",
    "SodaAshConfig",
    "SodaAshPipeline",
    "SodaAshRunResult",
    "aggregate_capacity_by_month",
    "calculate_implied_shipment_rate",
    "classify_flow_regime",
    "detect_regime_episodes",
    "evaluate_trading_gates",
    "load_capacity_projects",
    "load_company_panel",
    "load_customs_export",
    "load_factory_inventory",
    "load_futures_daily",
    "load_hold_rank",
    "load_latest_soda_ash_panorama",
    "load_nbs_plate_glass",
    "load_nbs_soda_ash",
    "load_soda_ash_config",
    "load_spot_benchmark",
    "load_spreads",
    "load_trading_gates",
    "load_warehouse_receipts",
    "merge_monthly_panorama",
    "render_markdown",
    "run_soda_ash_pipeline",
]
