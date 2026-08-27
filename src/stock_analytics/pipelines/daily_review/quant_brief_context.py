"""每日复盘中的量化风控与极端状态上下文装配。

复用已验证的 quant_brief 产物（brief_report.json），将 L1-L4
"风控裁剪 → 极端状态 → 档位纪律 → 方向约束" 执行链需要的字段投影为
复盘渲染上下文；只在产物缺失时回退运行一次 quant_brief。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from stock_analytics.pipelines.artifacts import (
    ArtifactUnavailableError,
    resolve_artifact_run,
)
from stock_analytics.pipelines.quant_brief import run_quant_brief
from stock_core.utils.logger import logger

_DEFAULT_ANALYTICS_BASE = Path("data/analytics")


def resolve_quant_brief_context(
    as_of_date: date,
    *,
    analytics_base: Path | str = _DEFAULT_ANALYTICS_BASE,
    storage_dir: Path | str | None = None,
    refresh_upstream: bool = False,
) -> dict[str, Any] | None:
    """返回量化简报的 L1-L4 投影上下文；产物缺失时回退运行一次。"""
    analytics_root = Path(analytics_base)
    quant_brief_root = analytics_root / "quant_brief"
    brief = _load_brief_report(as_of_date, quant_brief_root=quant_brief_root)
    if brief is None and refresh_upstream is False:
        logger.warning("quant_brief 产物缺失，回退运行一次（as_of={}）", as_of_date)
    if brief is None:
        brief = _run_brief(as_of_date, analytics_root, storage_dir=storage_dir)
    if brief is None:
        logger.warning(
            "quant_brief 回退运行仍不可用，复盘跳过 L1-L4 执行链（as_of={}）", as_of_date
        )
        return None
    return _project_brief(brief)


def _load_brief_report(
    as_of_date: date,
    *,
    quant_brief_root: Path,
) -> dict[str, Any] | None:
    """读取已验证的 quant_brief 产物，避免手工触碰 latest/。"""
    try:
        run = resolve_artifact_run(
            quant_brief_root,
            as_of_date=as_of_date,
            expected_artifact_type="quant_brief",
        )
    except ArtifactUnavailableError as exc:
        logger.debug("quant_brief 缓存产物不可用: {}", exc)
        return None
    return run.read_json("brief_report.json")


def _run_brief(
    as_of_date: date,
    analytics_base: Path,
    *,
    storage_dir: Path | str | None,
) -> dict[str, Any] | None:
    """回退运行一次 quant_brief，读取并返回最新 brief_report.json。"""
    try:
        result = run_quant_brief(
            target_date=as_of_date,
            storage_dir=storage_dir,
            market_temperature_root=analytics_base / "market_temperature",
            industry_structure_root=analytics_base / "industry_structure",
        )
    except Exception as exc:
        logger.warning("quant_brief 回退运行失败: {}", exc)
        return None
    return result.brief_json


def _project_brief(brief: dict[str, Any]) -> dict[str, Any]:
    """投影每日复盘模板需要的最小字段集。"""
    manifest = brief.get("manifest") or {}
    sector = brief.get("sector") or {}
    cross_cycle = brief.get("cross_cycle") or {}
    return {
        "as_of_date": manifest.get("as_of_date"),
        "run_id": manifest.get("run_id"),
        "rules_version": {
            "cross_cycle": cross_cycle.get("rules_version"),
            "extreme_state": (brief.get("extreme_state") or {}).get("rules_version"),
        },
        "risk_gates": brief.get("risk_gates") or {},
        "veto": brief.get("veto") or {},
        "extreme_state": brief.get("extreme_state") or {},
        "position_policy": brief.get("position_policy") or {},
        "cross_cycle": _project_cross_cycle(cross_cycle),
        "sector_priority": _industry_rows(sector.get("priority") or []),
        "sector_avoid": _industry_names(sector.get("avoid") or []),
        "data_quality_notes": brief.get("data_quality_notes") or [],
    }


def _project_cross_cycle(cross_cycle: dict[str, Any]) -> dict[str, Any]:
    """保留跨周期矩阵的关键展示字段。"""
    return {
        "win_level": cross_cycle.get("win_level"),
        "win_score": cross_cycle.get("win_score"),
        "odds_level": cross_cycle.get("odds_level"),
        "odds_score": cross_cycle.get("odds_score"),
        "quadrature": cross_cycle.get("quadrature"),
        "quadrature_label": cross_cycle.get("quadrature_label"),
        "position_adjustment_pp": cross_cycle.get("position_adjustment_pp"),
        "adjustment_note": cross_cycle.get("adjustment_note"),
        "table": cross_cycle.get("table") or {},
        "trajectory": cross_cycle.get("trajectory") or {},
        "upgrade_triggers": cross_cycle.get("upgrade_triggers") or [],
    }


def _industry_rows(items: list[Any]) -> list[dict[str, Any]]:
    """行业方向行：只保留复盘需要展示的字段。"""
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "industry_name": item.get("industry_name"),
                "tags": item.get("tags"),
                "reason": item.get("reason"),
                "structure_score": item.get("structure_score"),
                "crowding_temperature": item.get("crowding_temperature"),
            }
        )
    return rows


def _industry_names(items: list[Any]) -> list[str]:
    names: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("industry_name"):
            names.append(str(item["industry_name"]))
    return names


__all__ = ["resolve_quant_brief_context"]
