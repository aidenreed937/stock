"""量化投研简报产物管线编排。"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.pipelines.artifact_contracts import RunClass
from stock_analytics.pipelines.manifest import build_manifest_base
from stock_analytics.pipelines.quant_brief.artifacts import (
    QuantBriefArtifactPayload,
    QuantBriefRunPaths,
    build_run_paths,
    write_artifacts,
)
from stock_reporting.interpretation.quant_brief.config import (
    DEFAULT_CONFIG_PATH,
    QuantBriefConfig,
    load_quant_brief_config,
)


@dataclass(frozen=True, slots=True)
class QuantBriefRunResult:
    """量化投研简报一次运行结果。"""

    as_of_date: date
    paths: QuantBriefRunPaths
    manifest: dict[str, Any]
    brief_markdown: str
    brief_json: dict[str, Any]


def run_quant_brief(
    *,
    target_date: date | None = None,
    market_run_id: str | None = None,
    industry_run_id: str | None = None,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    output_root: Path | str | None = None,
    storage_dir: Path | str | None = None,
    market_temperature_root: Path | str | None = None,
    industry_structure_root: Path | str | None = None,
    run_class: RunClass = "official",
    update_latest: bool = True,
) -> QuantBriefRunResult:
    """读取市场温度和行业结构产物，生成量化投研简报。"""
    _validate_upstream_selection(target_date, market_run_id, industry_run_id)
    config = load_quant_brief_config(config_path).with_artifact_root(output_root)
    if market_temperature_root is not None:
        config = replace(config, market_temperature_root=Path(market_temperature_root))
    if industry_structure_root is not None:
        config = replace(config, industry_structure_root=Path(industry_structure_root))
    resolved_date = target_date or _resolve_latest_common_date(
        config.market_temperature_root,
        config.industry_structure_root,
    )
    market = _load_market_artifacts(config, resolved_date, run_id=market_run_id)
    industry = _load_industry_artifacts(config, resolved_date, run_id=industry_run_id)
    as_of_date = _resolve_as_of_date(market["manifest"], industry["manifest"])
    paths = build_run_paths(
        as_of_date,
        config.artifact_root,
        latest_root=config.latest_root,
        run_class=run_class,
    )
    margin_series = _load_margin_series(as_of_date, storage_dir=storage_dir)
    manifest = _build_manifest(
        config,
        as_of_date,
        paths,
        market=market,
        industry=industry,
        config_path=config_path,
    )

    from stock_reporting.templates.quant_brief import (
        build_quant_brief_json,
        render_quant_brief_markdown,
    )

    brief_json = build_quant_brief_json(
        config=config,
        manifest=manifest,
        market_scores=market["scores"],
        industry_scores=industry["scores"],
        industry_panel=industry["industry_panel"],
        market_facts=market["facts"],
        margin_series=margin_series,
    )
    brief_markdown = render_quant_brief_markdown(brief_json)
    write_artifacts(
        paths,
        QuantBriefArtifactPayload(
            manifest=manifest,
            brief_markdown=brief_markdown,
            brief_json=brief_json,
        ),
        update_latest=update_latest,
    )
    return QuantBriefRunResult(
        as_of_date=as_of_date,
        paths=paths,
        manifest=manifest,
        brief_markdown=brief_markdown,
        brief_json=brief_json,
    )


def _load_market_artifacts(
    config: QuantBriefConfig,
    target_date: date,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    artifact_dir = _resolve_artifact_dir(config.market_temperature_root, target_date, run_id=run_id)
    manifest = _read_json(artifact_dir / "manifest.json")
    _validate_upstream_manifest(
        manifest,
        artifact_dir=artifact_dir,
        target_date=target_date,
        artifact_type="market_temperature",
        expected_run_id=run_id,
    )
    facts_path = artifact_dir / "facts.parquet"
    return {
        "artifact_dir": artifact_dir,
        "manifest": manifest,
        "scores": _read_json(artifact_dir / "scores.json"),
        "facts": pl.read_parquet(facts_path) if facts_path.exists() else pl.DataFrame(),
    }


def _load_margin_series(
    as_of_date: date,
    *,
    storage_dir: Path | str | None = None,
) -> pl.DataFrame | None:
    """从本地 Curated margin 表读取两融日频序列，失败时返回 None。"""
    try:
        from datetime import timedelta

        from stock_data.catalog import DataCatalog

        catalog = DataCatalog(data_source="tushare", storage_dir=storage_dir)
        frame = catalog.load_dataset(
            "margin",
            start_date=as_of_date - timedelta(days=200),
            end_date=as_of_date,
        )
        if frame.is_empty():
            return None
        balance_col = next(
            (col for col in ("rzrqye", "margin_balance", "total_balance") if col in frame.columns),
            None,
        )
        if balance_col is None:
            return None
        return (
            frame.select("trade_date", balance_col)
            .drop_nulls()
            .group_by("trade_date")
            .agg(pl.col(balance_col).sum().alias("margin_balance"))
            .sort("trade_date")
        )
    except Exception:
        return None


def _load_industry_artifacts(
    config: QuantBriefConfig,
    target_date: date,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    artifact_dir = _resolve_artifact_dir(config.industry_structure_root, target_date, run_id=run_id)
    manifest = _read_json(artifact_dir / "manifest.json")
    _validate_upstream_manifest(
        manifest,
        artifact_dir=artifact_dir,
        target_date=target_date,
        artifact_type="industry_structure",
        expected_run_id=run_id,
    )
    return {
        "artifact_dir": artifact_dir,
        "manifest": manifest,
        "scores": _read_json(artifact_dir / "scores.json"),
        "industry_panel": pl.read_parquet(artifact_dir / "industry_panel.parquet"),
    }


def _resolve_latest_common_date(market_root: Path, industry_root: Path) -> date:
    """返回两个上游产物共同拥有的最新观测日期。"""
    common_dates = _available_run_dates(market_root) & _available_run_dates(industry_root)
    if not common_dates:
        raise FileNotFoundError(
            "市场温度和行业结构没有共同的已落盘观测日期，请先生成同一 DATE 的上游产物"
        )
    return max(common_dates)


def _available_run_dates(root: Path) -> set[date]:
    run_root = root / "runs"
    if not run_root.exists():
        return set()
    dates: set[date] = set()
    for path in run_root.glob("as_of=*"):
        if not path.is_dir() or not any(child.is_dir() for child in path.glob("run_*")):
            continue
        try:
            dates.add(date.fromisoformat(path.name.removeprefix("as_of=")))
        except ValueError:
            continue
    return dates


def _resolve_artifact_dir(root: Path, target_date: date, *, run_id: str | None = None) -> Path:
    run_root = root / "runs" / f"as_of={target_date.isoformat()}"
    if run_id is not None:
        _validate_run_id(run_id)
        artifact_dir = run_root / run_id
        if not artifact_dir.is_dir():
            raise FileNotFoundError(f"未找到指定运行 ID 的产物目录: {artifact_dir}")
        return artifact_dir
    run_dirs = sorted(path for path in run_root.glob("run_*") if path.is_dir())
    if not run_dirs:
        raise FileNotFoundError(f"未找到基准日 {target_date.isoformat()} 的产物目录: {run_root}")
    return run_dirs[-1]


def _validate_upstream_selection(
    target_date: date | None,
    market_run_id: str | None,
    industry_run_id: str | None,
) -> None:
    if (market_run_id is None) != (industry_run_id is None):
        raise ValueError("market_run_id 和 industry_run_id 必须同时提供")
    if target_date is None and market_run_id is not None:
        raise ValueError("指定上游 run_id 时必须同时提供 target_date")


def _validate_upstream_manifest(
    manifest: dict[str, Any],
    *,
    artifact_dir: Path,
    target_date: date,
    artifact_type: str,
    expected_run_id: str | None,
) -> None:
    actual_run_id = manifest.get("run_id")
    if actual_run_id is not None and actual_run_id != artifact_dir.name:
        raise ValueError(
            f"上游 Manifest run_id 与目录不一致: manifest={actual_run_id!r}, "
            f"directory={artifact_dir.name!r}"
        )
    actual_artifact_type = manifest.get("artifact_type")
    if actual_artifact_type is not None and actual_artifact_type != artifact_type:
        raise ValueError(
            f"上游 Manifest artifact_type 不一致: {actual_artifact_type!r}, "
            f"expected={artifact_type!r}"
        )
    if expected_run_id is not None:
        if actual_run_id != expected_run_id:
            raise ValueError(
                f"上游 Manifest run_id 与指定值不一致: manifest={actual_run_id!r}, "
                f"expected={expected_run_id!r}"
            )
    manifest_date = manifest.get("as_of_date")
    if manifest_date is not None and manifest_date != target_date.isoformat():
        raise ValueError(
            f"上游 Manifest as_of_date 与目标日期不一致: manifest={manifest_date!r}, "
            f"expected={target_date.isoformat()!r}"
        )


def _validate_run_id(run_id: str) -> None:
    path = Path(run_id)
    if not run_id or path.is_absolute() or path.name != run_id or ".." in path.parts:
        raise ValueError(f"run_id 必须是单段相对目录名: {run_id!r}")


def _resolve_as_of_date(market_manifest: dict[str, Any], industry_manifest: dict[str, Any]) -> date:
    market_date = str(market_manifest.get("as_of_date") or "")
    industry_date = str(industry_manifest.get("as_of_date") or "")
    if not market_date or not industry_date:
        raise ValueError("上游产物缺少 as_of_date")
    if market_date != industry_date:
        raise ValueError(f"上游产物基准日不一致: market={market_date}, industry={industry_date}")
    return date.fromisoformat(market_date)


def _build_manifest(
    config: QuantBriefConfig,
    as_of_date: date,
    paths: QuantBriefRunPaths,
    *,
    market: dict[str, Any],
    industry: dict[str, Any],
    config_path: Path | str | None = None,
) -> dict[str, Any]:
    drivers = market["scores"].get("drivers")
    comparison = {}
    if isinstance(drivers, dict) and drivers.get("status") == "ok":
        comparison["previous_as_of_date"] = drivers.get("comparison_as_of")
    inputs = {
        "market_temperature": _input_manifest(market),
        "industry_structure": _input_manifest(industry),
    }
    parents = {
        name: {
            "as_of_date": value.get("as_of_date"),
            "run_id": value.get("run_id"),
            "run_class": value.get("run_class", "official"),
        }
        for name, value in inputs.items()
    }
    manifest = build_manifest_base(
        artifact_type="quant_brief",
        schema_version=config.schema_version,
        title=config.title,
        run_id=paths.run_dir.name,
        as_of_date=as_of_date,
        artifact_root=paths.root,
        config_path=config_path,
        inputs=inputs,
        parents=parents,
    )
    manifest.update(
        {
            "comparison": comparison or None,
            "files": {
                "manifest": paths.manifest.name,
                "brief_report_md": paths.brief_md.name,
                "brief_report_json": paths.brief_json.name,
            },
        }
    )
    return manifest


def _input_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    manifest = payload["manifest"]
    return {
        "as_of_date": manifest.get("as_of_date"),
        "run_id": manifest.get("run_id"),
        "run_class": manifest.get("run_class", "official"),
        "artifact_dir": str(payload["artifact_dir"]),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"缺少产物文件: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"产物不是 JSON 对象: {path}")
    return payload


__all__ = ["QuantBriefRunResult", "run_quant_brief"]
