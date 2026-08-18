"""数据集别名与存储文件识别兼容规则。"""

from __future__ import annotations

from pathlib import Path

from stock_data.core.task_registry import resolve_task


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
            except Exception:
                pass
        return tuple(dict.fromkeys(aliases))

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
