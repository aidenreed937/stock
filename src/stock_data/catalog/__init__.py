"""数据目录服务 (DataCatalog) 与 Curated 黄金表只读查询接口。"""

from stock_data.catalog.service import DataCatalog, load_dataset_compat

__all__ = [
    "DataCatalog",
    "load_dataset_compat",
]
