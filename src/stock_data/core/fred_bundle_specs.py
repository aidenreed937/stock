"""FRED 正式任务包定义。"""

from __future__ import annotations

FRED_TASK_BUNDLE_TASKS: dict[str, tuple[str, ...]] = {
    "global_macro_daily_bundle": (
        "DFF",
        "DGS10",
        "DGS3MO",
        "T10Y2Y",
        "VIXCLS",
        "DCOILWTICO",
        "DTWEXBGS",
        "PCOPPUSDM",
    ),
    "macro_monthly_bundle": (
        "FEDFUNDS",
        "CPIAUCSL",
        "UNRATE",
        "PAYEMS",
        "MANEMP",
        "OECDLOLITOAASTSAM",
        "USALOLITOAASTSAM",
        "CHNLOLITOAASTSAM",
        "DGORDER",
        "AMTMVS",
    ),
}


__all__ = ["FRED_TASK_BUNDLE_TASKS"]
