"""光伏景气前瞻仪表盘 (pv_outlook) 管线。

不等财报（滞后确认），用产业数据前瞻景气方向：周度价格链价差（毛利空间）+
月度装机/库存/供需水位 + 数据缺口矩阵（明示可补充）+ 外部核验事实（强制信源日期）。
产物落盘 ``data/analytics/pv_outlook/``（ArtifactStore run 目录 + latest + manifest）。
"""

from stock_analytics.pipelines.pv_outlook.config import (
    DEFAULT_CONFIG_PATH,
    PvOutlookConfig,
    load_pv_outlook_config,
)
from stock_analytics.pipelines.pv_outlook.pipeline import (
    PvOutlookPipeline,
    PvOutlookRunResult,
    run_pv_outlook,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "PvOutlookConfig",
    "PvOutlookPipeline",
    "PvOutlookRunResult",
    "load_pv_outlook_config",
    "run_pv_outlook",
]
