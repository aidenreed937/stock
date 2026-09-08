"""公司层出口交易信号管线（customs_company）。

把行业层出口景气下沉到受益公司（暴露度 × 税号段级序列），合成三层信号
（出口前瞻 × 资金确认 × 财报真扩张）评级 A/B/C/D/回避-顶背离
（METHODOLOGY_COMPANY_FINAL.md 定稿口径）。产物保持既有契约路径
``data/analytics/industry/customs_company_*`` 供抓机会手册消费。
"""

from stock_analytics.pipelines.customs_company.config import (
    DEFAULT_CONFIG_PATH,
    CustomsCompanyConfig,
    load_customs_company_config,
)
from stock_analytics.pipelines.customs_company.exposure_panel import (
    build_exposure_panel,
    build_segment_key_map,
    load_catalog_hs_codes,
    save_exposure_panel,
)
from stock_analytics.pipelines.customs_company.pipeline import (
    run_customs_company_pipeline,
)
from stock_analytics.pipelines.customs_company.signal import (
    build_company_signal,
    export_leg_state,
    fin_leg_state,
    fund_leg_state,
    load_fina_latest,
    load_margin_change,
    load_moneyflow_strength,
    rate,
    save_company_signal,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "CustomsCompanyConfig",
    "build_company_signal",
    "build_exposure_panel",
    "build_segment_key_map",
    "export_leg_state",
    "fin_leg_state",
    "fund_leg_state",
    "load_catalog_hs_codes",
    "load_customs_company_config",
    "load_fina_latest",
    "load_margin_change",
    "load_moneyflow_strength",
    "rate",
    "run_customs_company_pipeline",
    "save_company_signal",
    "save_exposure_panel",
]
