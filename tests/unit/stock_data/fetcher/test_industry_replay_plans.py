"""各产业离线重放计划的契约测试。

守护点：
1. 计划条目结构完整（``loader`` / ``to_frame`` / ``curated`` / ``primary_keys``）；
2. 指标键在全部产业间唯一，且总数不低于已迁移基线（防误删）；
3. Curated 路径由该产业 registry 的 ``target_file`` 推导，**禁止硬编码漂移**；
   未登记端点（显式声明路径）必须在白名单内；
4. ``POWER_REPLAY_ORDER`` 与 power 计划一致（派生表依赖顺序不可随意调整）。
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

_PLAN_BUILDERS: dict[str, str] = {
    "agriculture": "build_agriculture_replay_plan",
    "automotive": "build_automotive_replay_plan",
    "chemicals": "build_chemicals_replay_plan",
    "cloud": "build_cloud_replay_plan",
    "coal": "build_coal_replay_plan",
    "consumer": "build_consumer_replay_plan",
    "customs": "build_customs_replay_plan",
    "electronics": "build_electronics_replay_plan",
    "machinery": "build_machinery_replay_plan",
    "metals": "build_metals_replay_plan",
    "pharma": "build_pharma_replay_plan",
    "power": "build_power_replay_plan",
    "semiconductor": "build_semiconductor_replay_plan",
    "shipping": "build_shipping_replay_plan",
}

# 未登记在 registry、路径按约定显式声明的端点（见各 replay.py 注释）
_EXPLICIT_PATH_METRICS = frozenset({"liquor_wholesale", "customs_trade"})

# 迁移完成时的指标基线（新增产业应上调此值；2026-09-10 退役 semiconductor_china_series 后 35 -> 34；
# 2026-09-16 接入 chemical_spot_price 后 34 -> 35；2026-10-20 化工指标接入后 35 -> 36）
_EXPECTED_METRIC_COUNT = 36

_POWER_ORDER = (
    "solar_capacity",
    "solar_cell_nbs",
    "solar_price_chain",
    "silicon_wafer_monthly",
    "polysilicon_supply_monthly",
    "polysilicon_inventory_monthly",
    "pv_wafer_monthly",
    "polysilicon_balance",
    "solar_supply_demand",
)


def _builder(package: str) -> Callable[[], dict[str, dict[str, Any]]]:
    module = importlib.import_module(f"stock_data.fetcher.industry.{package}.replay")
    return getattr(module, _PLAN_BUILDERS[package])


def _all_plans() -> dict[str, dict[str, Any]]:
    plans: dict[str, dict[str, Any]] = {}
    for package in _PLAN_BUILDERS:
        plans.update(_builder(package)())
    return plans


def _registry_specs() -> dict[str, Any]:
    """全部产业 (含半导体) 的端点名 -> spec 映射（同名端点全局唯一）。"""
    specs: dict[str, Any] = {}
    for package in _PLAN_BUILDERS:
        module = importlib.import_module(f"stock_data.fetcher.industry.{package}.registry")
        for spec in getattr(module, "ENDPOINT_SPECS", ()):  # noqa: B009
            specs.setdefault(spec.endpoint, spec)
    return specs


@pytest.mark.parametrize("package", sorted(_PLAN_BUILDERS))
def test_each_industry_plan_is_well_formed(package: str) -> None:
    plan = _builder(package)()
    assert plan, f"{package} 的重放计划为空"
    for metric, entry in plan.items():
        assert callable(entry["loader"]), f"{metric} 缺少可调用的 loader"
        assert callable(entry["to_frame"]), f"{metric} 缺少可调用的 to_frame"
        assert isinstance(entry["curated"], str) and entry["curated"].endswith(".parquet"), (
            f"{metric} 的 curated 目标不是 parquet 相对路径: {entry['curated']!r}"
        )
        assert not entry["curated"].startswith("/"), f"{metric} 的 curated 目标不得为绝对路径"
        assert "primary_keys" in entry, f"{metric} 缺少 primary_keys 声明"


def test_metric_keys_are_unique_across_industries() -> None:
    seen: dict[str, str] = {}
    for package in _PLAN_BUILDERS:
        for metric in _builder(package)():
            assert metric not in seen, f"指标 [{metric}] 同时出现在 {seen.get(metric)} 与 {package}"
            seen[metric] = package
    assert len(seen) == _EXPECTED_METRIC_COUNT


def test_curated_paths_come_from_registry_not_hardcoded() -> None:
    """除白名单外，Curated 路径必须等于该端点 registry 声明的 target_file。"""
    specs = _registry_specs()
    checked = 0
    for metric, entry in _all_plans().items():
        if metric in _EXPLICIT_PATH_METRICS:
            spec = specs.get(metric)
            assert spec is None or not spec.target_file, (
                f"{metric} 已在 registry 声明 target_file，应改用 registry 推导而非显式路径"
            )
            continue
        spec = specs.get(metric)
        assert spec is not None, f"{metric} 既不在 registry 也不在显式路径白名单内"
        assert entry["curated"] == spec.target_file, (
            f"{metric} 的 curated 与 registry target_file 不一致: "
            f"{entry['curated']} != {spec.target_file}"
        )
        assert entry.get("raw_subdir", "") == (spec.raw_subdir or ""), (
            f"{metric} 的 raw_subdir 与 registry 声明不一致"
        )
        checked += 1
    assert checked >= 30, f"仅校验到 {checked} 条 registry 推导路径，疑似大量走白名单"


def test_power_replay_order_matches_power_plan() -> None:
    from stock_data.fetcher.industry.power.replay import POWER_REPLAY_ORDER

    plan = _builder("power")()
    assert tuple(POWER_REPLAY_ORDER) == _POWER_ORDER
    assert set(_POWER_ORDER) <= set(plan)
    derived = set(_POWER_ORDER) - {
        "solar_capacity",
        "solar_cell_nbs",
        "solar_price_chain",
        "silicon_wafer_monthly",
    }
    for metric in derived:
        assert plan[metric].get("loader_uses_curated"), f"{metric} 应由 Curated 主表重建"


def test_coal_replay_loader_uses_canonical_raw_path(tmp_path: Path) -> None:
    """煤炭重放只使用 coal/ canonical RAW 底表。"""
    from datetime import date

    from stock_data.fetcher.industry.coal.models import CoalMarketRecord
    from stock_data.fetcher.industry.coal.parsers import save_coal_raw_csv
    from stock_data.fetcher.industry.coal.replay import build_coal_replay_plan

    canonical_record = CoalMarketRecord(
        report_date="2020-01-03",
        trade_date=date(2020, 1, 3),
        q5500_fob_price_cny=558.0,
    )
    save_coal_raw_csv(tmp_path / "coal" / "coal_market_weekly.csv", [canonical_record])

    loader = build_coal_replay_plan()["coal_market"]["loader"]
    records = loader(tmp_path)

    assert [record.report_date for record in records] == ["2020-01-03"]
