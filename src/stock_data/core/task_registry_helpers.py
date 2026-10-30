"""任务注册兼容辅助入口。"""

from stock_data.core.derived_datasets import (
    CURATED_DERIVED_DATASETS,
    CURATED_DERIVED_NON_PARTITIONED_DATASETS,
    DerivedDatasetSpec,
    resolve_derived_dataset,
)
from stock_data.core.tushare_internal_apis import (
    TUSHARE_INTERNAL_PERIOD_TASKS,
    is_tushare_internal_api,
)

PER_PERIOD_DATASETS = TUSHARE_INTERNAL_PERIOD_TASKS


__all__ = [
    "CURATED_DERIVED_DATASETS",
    "CURATED_DERIVED_NON_PARTITIONED_DATASETS",
    "PER_PERIOD_DATASETS",
    "DerivedDatasetSpec",
    "is_tushare_internal_api",
    "resolve_derived_dataset",
]
