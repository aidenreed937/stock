"""动态 H8 公司层出口交易信号管线（customs_company_h8）。

输入 fina_mainbz 动态映射的``customs_company_h8_exposure.parquet``（公司×月份×H8，
无人工 CSV），聚合公司×产品×月份面板并合成三层信号
（出口前瞻 × 资金确认 × 财报真扩张，评级 A/B/C/D/回避-顶背离）。
产物使用 ``customs_company_h8_*`` 命名；产品映射由报告期主营构成动态生成。
"""

from stock_analytics.pipelines.customs_company_h8.panel import (
    PANEL_FILE,
    PANEL_LATEST_FILE,
    build_company_h8_product_panel,
    save_company_h8_product_panel,
)
from stock_analytics.pipelines.customs_company_h8.pipeline import (
    MANIFEST_FILE,
    SIGNAL_LATEST_FILE,
    SIGNAL_PANEL_FILE,
    run_customs_company_h8_pipeline,
)

__all__ = [
    "MANIFEST_FILE",
    "PANEL_FILE",
    "PANEL_LATEST_FILE",
    "SIGNAL_LATEST_FILE",
    "SIGNAL_PANEL_FILE",
    "build_company_h8_product_panel",
    "run_customs_company_h8_pipeline",
    "save_company_h8_product_panel",
]
