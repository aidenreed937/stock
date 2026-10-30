"""数据集别名与存储文件识别兼容规则。"""

from __future__ import annotations

from pathlib import Path

from stock_data.core.task_resolution import resolve_task

# industry 数据源下按业务子目录存储、但仍需按文件名独立寻址的数据集快捷别名。
# 未登记的多级目录可由 DataCatalog 直接使用安全相对路径寻址。
INDUSTRY_SUBDIR_DATASETS: frozenset[str] = frozenset(
    {
        "energy_cross_source_audit",
        "global_energy_macro_baseline",
        "global_oil_gas_balance",
        "global_power_generation",
        "global_renewable_capacity",
    }
)

# industry 数据源下半导体按 5 大产研业务子目录存储的黄金事实表映射表。
SEMICONDUCTOR_SUBDIR_DATASETS: dict[str, str] = {
    # sales (销售与产出)
    "semiconductor_sales": "semiconductor/sales/semiconductor_sales",
    "semiconductor_lead": "semiconductor/sales/semiconductor_lead",
    # inventory (库存与出清)
    "semiconductor_inventory_days": "semiconductor/inventory/semiconductor_inventory_days",
    "semiconductor_channel_inventory": "semiconductor/inventory/semiconductor_channel_inventory",
    # equipment (设备与资本开支)
    "semiconductor_equipment": "semiconductor/equipment/semiconductor_equipment",
    "semiconductor_equipment_semi": "semiconductor/equipment/semiconductor_equipment_semi",
    "semiconductor_equipment_gm": "semiconductor/equipment/semiconductor_equipment_gm",
    "semiconductor_equipment_gm_multi": "semiconductor/equipment/semiconductor_equipment_gm_multi",
    "tel_gm_quarterly": "semiconductor/equipment/tel_gm_quarterly",
    # capacity (供给约束与晶圆制造/先进封装)
    "foundry_capacity_utilization": "semiconductor/capacity/foundry_capacity_utilization",
    "chip_lead_time": "semiconductor/capacity/chip_lead_time",
    "tsmc_advanced_packaging_revenue": "semiconductor/capacity/tsmc_advanced_packaging_revenue",
    "tsmc_cowos_capacity_estimates": "semiconductor/capacity/tsmc_cowos_capacity_estimates",
    # price (价格与存储基准)
    "semiconductor_memory_price": "semiconductor/price/semiconductor_memory_price",
    "semiconductor_memory_benchmark": "semiconductor/price/semiconductor_memory_benchmark",
    "semiconductor_memory_taiwan_lead": "semiconductor/price/semiconductor_memory_taiwan_lead",
}


class DatasetAliasMixin:
    """解析历史端点名、数据集别名和固定实体标识。"""

    @staticmethod
    def is_artifact_path(path: Path) -> bool:
        """跳过迁移备份、临时快照等非有效 Parquet 文件。"""
        return path.name.endswith((".bak.parquet", ".tmp.parquet", ".migration.tmp.parquet"))

    @staticmethod
    def canonical_dataset_name(endpoint: str, provider: str | None = None) -> str:
        """将历史兼容参数解析为唯一项目任务/数据集目录名。"""
        if provider is not None and provider.lower() == "fred":
            try:
                from stock_data.fetcher.fred.registry import FRED_API_REGISTRY

                if endpoint.upper() in FRED_API_REGISTRY:
                    return "macro_indicators"
            except Exception:
                pass
        if provider is not None:
            try:
                return resolve_task(provider, endpoint).dataset
            except ValueError:
                pass
        if endpoint in {"daily", "daily_bar", "history"}:
            return "stock_daily_bar"
        return endpoint

    @classmethod
    def dataset_aliases(cls, endpoint: str, provider: str | None = None) -> tuple[str, ...]:
        """返回数据集规范名及仍需读取的历史目录别名。"""
        canonical = cls.canonical_dataset_name(endpoint, provider)
        aliases = [canonical]
        if provider is not None and provider.lower() == "fred":
            try:
                from stock_data.fetcher.fred.registry import FRED_API_REGISTRY

                if endpoint.upper() in FRED_API_REGISTRY:
                    aliases.append(endpoint.lower())
                    aliases.append(endpoint.upper())
            except Exception:
                pass
        return tuple(dict.fromkeys(aliases))

    @staticmethod
    def subdir_dataset_aliases(endpoint: str, provider: str | None = None) -> tuple[str, ...]:
        """返回位于业务子目录内、需按文件名独立寻址的数据集定位别名。

        与 dataset_aliases 分离: 仅 DataCatalog 读取路径消费, 不注入对账、
        DuckDB 查询等依赖目录聚合语义的调用方。
        """
        if provider is not None and provider.lower() == "industry":
            ep = endpoint.casefold()
            if ep in INDUSTRY_SUBDIR_DATASETS:
                return (f"energy/{endpoint}",)
            if ep in SEMICONDUCTOR_SUBDIR_DATASETS:
                return (SEMICONDUCTOR_SUBDIR_DATASETS[ep],)
        return ()

    @staticmethod
    def dataset_symbol_filter(endpoint: str, provider: str | None = None) -> str | None:
        """返回聚合数据集别名对应的固定标的过滤条件。"""
        if provider is None or provider.lower() != "fred":
            return None
        try:
            from stock_data.fetcher.fred.registry import FRED_API_REGISTRY

            symbol = endpoint.upper()
            return symbol if symbol in FRED_API_REGISTRY else None
        except Exception:
            return None
