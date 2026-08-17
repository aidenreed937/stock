"""全系统特征元数据注册中心 (FeatureRegistry)。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from stock_analytics.features.builtin_specs import get_all_builtin_specs

if TYPE_CHECKING:
    from stock_analytics.features.spec import (
        EntityType,
        FeatureKind,
        FeatureSpec,
    )


class FeatureRegistry:
    """集中管理 FeatureSpec 注册与查询。"""

    _registry: ClassVar[dict[str, dict[str, FeatureSpec]]] = {}
    _current_versions: ClassVar[dict[str, str]] = {}

    @classmethod
    def register(cls, spec: FeatureSpec) -> None:
        """注册特征元数据定义。"""
        versions = cls._registry.setdefault(spec.feature_id, {})
        existing = versions.get(spec.definition_version)
        if existing is not None and existing != spec:
            raise ValueError(
                f"特征定义已存在且内容不一致: {spec.feature_id}@{spec.definition_version}"
            )
        versions[spec.definition_version] = spec
        cls._current_versions[spec.feature_id] = spec.definition_version

    @classmethod
    def get(cls, feature_id: str, definition_version: str | None = None) -> FeatureSpec:
        """根据特征 ID 获取元数据，不存在时抛出 KeyError。"""
        if feature_id not in cls._registry:
            raise KeyError(f"未注册的特征 ID: {feature_id}")
        versions = cls._registry[feature_id]
        version = definition_version or cls._current_versions[feature_id]
        if version not in versions:
            raise KeyError(f"未注册的特征版本: {feature_id}@{version}")
        return versions[version]

    @classmethod
    def get_or_none(
        cls, feature_id: str, definition_version: str | None = None
    ) -> FeatureSpec | None:
        """根据特征 ID 获取元数据，不存在时返回 None。"""
        try:
            return cls.get(feature_id, definition_version)
        except KeyError:
            return None

    @classmethod
    def list_all(cls) -> list[FeatureSpec]:
        """返回每个特征当前生效的定义。"""
        return [cls.get(feature_id) for feature_id in cls._registry]

    @classmethod
    def list_versions(cls, feature_id: str) -> list[FeatureSpec]:
        """返回指定特征的全部定义版本。"""
        if feature_id not in cls._registry:
            return []
        return list(cls._registry[feature_id].values())

    @classmethod
    def list_by_kind(cls, kind: FeatureKind) -> list[FeatureSpec]:
        """按特征语义类别筛选特征列表。"""
        return [spec for spec in cls.list_all() if spec.kind == kind]

    @classmethod
    def list_by_entity_type(cls, entity_type: EntityType) -> list[FeatureSpec]:
        """按实体粒度筛选特征列表。"""
        return [spec for spec in cls.list_all() if spec.entity_type == entity_type]

    @classmethod
    def clear(cls) -> None:
        """测试用清理注册表。"""
        cls._registry.clear()
        cls._current_versions.clear()

    @classmethod
    def register_builtins(cls) -> None:
        """注册全套内置特征元数据规范。"""
        for spec in get_all_builtin_specs():
            cls.register(spec)


# 初始化加载内置特征元数据
FeatureRegistry.register_builtins()
