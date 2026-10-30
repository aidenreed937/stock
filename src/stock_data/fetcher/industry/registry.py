"""垂直产业端点注册聚合。"""

from collections.abc import Iterable
from importlib import import_module
from typing import Any, cast

from stock_data.fetcher.industry.contracts import IndustryEndpointSpec

DOMAIN_REGISTRY_MODULES: tuple[str, ...] = (
    "stock_data.fetcher.industry.agriculture.registry",
    "stock_data.fetcher.industry.automotive.registry",
    "stock_data.fetcher.industry.chemicals.registry",
    "stock_data.fetcher.industry.cloud.registry",
    "stock_data.fetcher.industry.coal.registry",
    "stock_data.fetcher.industry.consumer.registry",
    "stock_data.fetcher.industry.customs.registry",
    "stock_data.fetcher.industry.electronics.registry",
    "stock_data.fetcher.industry.machinery.registry",
    "stock_data.fetcher.industry.metals.registry",
    "stock_data.fetcher.industry.pharma.registry",
    "stock_data.fetcher.industry.power.registry",
    "stock_data.fetcher.industry.semiconductor.registry",
    "stock_data.fetcher.industry.shipping.registry",
)

_ENDPOINT_SPEC_CACHE: dict[str, IndustryEndpointSpec] | None = None


def get_endpoint_specs() -> dict[str, IndustryEndpointSpec]:
    """返回全部产业端点规格。"""
    global _ENDPOINT_SPEC_CACHE
    if _ENDPOINT_SPEC_CACHE is None:
        _ENDPOINT_SPEC_CACHE = _load_endpoint_specs()
    return dict(_ENDPOINT_SPEC_CACHE)


def get_endpoint_spec(endpoint: str) -> IndustryEndpointSpec:
    """按 endpoint 读取产业端点规格。"""
    specs = get_endpoint_specs()
    try:
        return specs[endpoint]
    except KeyError as exc:
        raise KeyError(f"未知的垂直产业任务端点: {endpoint}") from exc


def _load_endpoint_specs() -> dict[str, IndustryEndpointSpec]:
    specs: dict[str, IndustryEndpointSpec] = {}
    for module_name in DOMAIN_REGISTRY_MODULES:
        for spec in _load_domain_specs(module_name):
            if spec.endpoint in specs:
                raise ValueError(f"垂直产业端点重复注册: {spec.endpoint}")
            specs[spec.endpoint] = spec
    return specs


def _load_domain_specs(module_name: str) -> Iterable[IndustryEndpointSpec]:
    module: Any = import_module(module_name)
    return cast("Iterable[IndustryEndpointSpec]", module.ENDPOINT_SPECS)
