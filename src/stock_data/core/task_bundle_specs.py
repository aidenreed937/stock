"""正式任务包定义。"""

from __future__ import annotations

from stock_data.core.alphavantage_bundle_specs import ALPHAVANTAGE_TASK_BUNDLE_TASKS
from stock_data.core.fred_bundle_specs import FRED_TASK_BUNDLE_TASKS
from stock_data.core.industry_bundle_specs import build_industry_task_bundles
from stock_data.core.lixinger_bundle_specs import LIXINGER_TASK_BUNDLE_TASKS
from stock_data.core.task_bundle_types import TaskBundle
from stock_data.core.tushare_bundle_specs import TUSHARE_TASK_BUNDLE_TASKS
from stock_data.core.yfinance_bundle_specs import YFINANCE_TASK_BUNDLE_TASKS

TASK_BUNDLE_TASKS: dict[str, dict[str, tuple[str, ...]]] = {
    "tushare": TUSHARE_TASK_BUNDLE_TASKS,
    "lixinger": LIXINGER_TASK_BUNDLE_TASKS,
    "yfinance": YFINANCE_TASK_BUNDLE_TASKS,
    "fred": FRED_TASK_BUNDLE_TASKS,
    "alphavantage": ALPHAVANTAGE_TASK_BUNDLE_TASKS,
    "industry": build_industry_task_bundles(),
}

TASK_BUNDLES: dict[tuple[str, str], TaskBundle] = {
    (provider, bundle_name): TaskBundle(bundle_name, provider, tasks)
    for provider, bundles in TASK_BUNDLE_TASKS.items()
    for bundle_name, tasks in bundles.items()
}


__all__ = ["TASK_BUNDLES", "TASK_BUNDLE_TASKS"]
