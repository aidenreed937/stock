"""海关出口景气研究管线（customs_prosperity）。

月度 SOP 四步：金额面板 → 量价分解 → 商品拐点 → 观察表
（METHODOLOGY_FINAL §8），产物保持既有契约路径
``data/analytics/industry/customs_*.parquet`` 供 three_leg 与公司层管线消费。
"""

from stock_analytics.pipelines.customs_prosperity.amount_panel import (
    build_amount_panel,
    complete_months,
    derive_amount_metrics,
    save_amount_panel,
)
from stock_analytics.pipelines.customs_prosperity.config import (
    DEFAULT_CONFIG_PATH,
    CustomsProsperityConfig,
    load_customs_prosperity_config,
)
from stock_analytics.pipelines.customs_prosperity.forward_watch import (
    build_forward_watch,
    build_level,
    load_dim,
    load_financial,
)
from stock_analytics.pipelines.customs_prosperity.pipeline import (
    run_customs_prosperity_pipeline,
)
from stock_analytics.pipelines.customs_prosperity.product_panel import (
    assign_unit_segment,
    build_product_panel,
    load_unit_segments,
    save_product_panel,
    validate_bridge,
)
from stock_analytics.pipelines.customs_prosperity.volume_price import (
    build_volume_price_panel,
    save_volume_price_panel,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "CustomsProsperityConfig",
    "assign_unit_segment",
    "build_amount_panel",
    "build_forward_watch",
    "build_level",
    "build_product_panel",
    "build_volume_price_panel",
    "complete_months",
    "derive_amount_metrics",
    "load_customs_prosperity_config",
    "load_dim",
    "load_financial",
    "load_unit_segments",
    "run_customs_prosperity_pipeline",
    "save_amount_panel",
    "save_product_panel",
    "save_volume_price_panel",
    "validate_bridge",
]
