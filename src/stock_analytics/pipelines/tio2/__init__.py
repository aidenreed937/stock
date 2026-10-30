"""钛白粉 (TiO2) 全景基本面对账管线。

串联核心事实源（海关出口/现货出厂价/理论利润/公司面板），产出全景事实表与数据驱动研报；
产物经 ArtifactStore 落盘 ``runs/`` + ``latest/`` + ``manifest.json``。
"""

from __future__ import annotations

from stock_analytics.pipelines.tio2.config import (
    DEFAULT_CONFIG_PATH,
    HistoryConfig,
    InputsConfig,
    RegimeThresholds,
    Tio2Config,
    load_tio2_config,
)
from stock_analytics.pipelines.tio2.gates import (
    evaluate_trading_gates,
    load_trading_gates,
)
from stock_analytics.pipelines.tio2.market_sources import (
    load_company_panel,
    load_industry_market,
    load_spreads,
)
from stock_analytics.pipelines.tio2.panorama import (
    aggregate_capacity_by_month,
    classify_flow_regime,
    detect_regime_episodes,
    merge_monthly_panorama,
)
from stock_analytics.pipelines.tio2.pipeline import (
    Tio2Pipeline,
    Tio2RunResult,
    load_latest_tio2_panorama,
    run_tio2_pipeline,
)
from stock_analytics.pipelines.tio2.report import FLOW_REGIME_CN, render_markdown
from stock_analytics.pipelines.tio2.sources import (
    DatasetReader,
    load_capacity_projects,
    load_cost_models,
    load_customs_export,
    load_spot_price,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "FLOW_REGIME_CN",
    "DatasetReader",
    "HistoryConfig",
    "InputsConfig",
    "RegimeThresholds",
    "Tio2Config",
    "Tio2Pipeline",
    "Tio2RunResult",
    "aggregate_capacity_by_month",
    "classify_flow_regime",
    "detect_regime_episodes",
    "evaluate_trading_gates",
    "load_capacity_projects",
    "load_company_panel",
    "load_cost_models",
    "load_customs_export",
    "load_industry_market",
    "load_latest_tio2_panorama",
    "load_spot_price",
    "load_spreads",
    "load_tio2_config",
    "load_trading_gates",
    "merge_monthly_panorama",
    "render_markdown",
    "run_tio2_pipeline",
]
