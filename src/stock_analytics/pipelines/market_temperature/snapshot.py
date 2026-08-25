"""市场温度分析快照及缓存身份。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SNAPSHOT_SCHEMA_VERSION = 1
_CODE_FILES = ("pipeline.py", "scoring.py", "scoring_risk.py")


def build_market_state_snapshot(
    *,
    manifest: Mapping[str, Any],
    scores: Mapping[str, Any],
    config_path: Path | str | None,
) -> dict[str, Any]:
    """从已验证的运行产物构建面向问答的市场状态快照。"""
    dimensions = _mapping_list(scores.get("dimensions"))
    identity = build_cache_identity(manifest, config_path=config_path)
    composite = _mapping(scores.get("composite"))
    systemic_risk = _mapping(scores.get("systemic_risk"))
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "as_of_date": str(manifest.get("as_of_date") or scores.get("as_of_date") or ""),
        "run_id": str(manifest.get("run_id") or ""),
        "identity": identity,
        "composite": composite,
        "dimensions": dimensions,
        "dimension_groups": _dimension_groups(dimensions),
        "trend": {
            "d1": _daily_trend(scores),
            "d5": {"status": "pending", "reason": "等待历史索引"},
            "d20": {"status": "pending", "reason": "等待历史索引"},
        },
        "systemic_risk": systemic_risk,
        "external_risk": _mapping(scores.get("external_risk")),
        "data_quality": {
            "status": str(composite.get("status") or "pending"),
            "freshness": _mapping(scores.get("data_freshness")),
        },
        "provenance": {
            "generated_at": manifest.get("generated_at"),
            "artifact_root": manifest.get("artifact_root"),
            "parents": _mapping(manifest.get("parents")),
            "source_cutoffs": _mapping(manifest.get("source_cutoffs")),
        },
        "explanation_facts": _explanation_facts(composite, dimensions, systemic_risk),
    }


def build_cache_identity(
    manifest: Mapping[str, Any],
    *,
    config_path: Path | str | None,
) -> dict[str, Any]:
    """构建基于运行、配置、数据和代码版本的稳定缓存身份。"""
    provenance = _mapping(manifest.get("provenance"))
    config_hash = provenance.get("config_sha256") or _file_sha256(config_path)
    data_material = {
        "inputs": manifest.get("inputs", {}),
        "watermarks": manifest.get("watermarks", {}),
    }
    data_fingerprint = _stable_hash(data_material)
    code_commit = provenance.get("git_commit") or "unknown"
    code_version = f"{code_commit}:{_code_fingerprint()}"
    material = {
        "pipeline": "market_temperature",
        "as_of_date": manifest.get("as_of_date"),
        "run_id": manifest.get("run_id"),
        "config_hash": config_hash,
        "data_fingerprint": data_fingerprint,
        "code_version": code_version,
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
    }
    return {
        **material,
        "cache_key": _stable_hash(material),
    }


def _dimension_groups(dimensions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    fast: list[dict[str, Any]] = []
    slow: list[dict[str, Any]] = []
    for item in dimensions:
        dimension_id = str(item.get("dimension_id") or "")
        temperature = item.get("temperature")
        if dimension_id and temperature is not None:
            fast.append(
                {
                    "dimension_id": dimension_id,
                    "temperature": temperature,
                    "source": item.get("temperature_source"),
                }
            )
        subgroups = _mapping(item.get("subgroups"))
        slow_temperature = subgroups.get("slow")
        if dimension_id and slow_temperature is not None:
            slow.append({"dimension_id": dimension_id, "temperature": slow_temperature})
    return {"fast": fast, "slow": slow}


def _daily_trend(scores: Mapping[str, Any]) -> dict[str, Any]:
    drivers = _mapping(scores.get("drivers"))
    if not drivers:
        return {"status": "pending", "reason": "缺少跨期驱动"}
    return drivers


def _explanation_facts(
    composite: Mapping[str, Any],
    dimensions: list[dict[str, Any]],
    systemic_risk: Mapping[str, Any],
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = [
        {
            "kind": "composite_temperature",
            "temperature": composite.get("temperature"),
            "status": composite.get("status"),
        }
    ]
    facts.extend(
        {
            "kind": "dimension_temperature",
            "dimension_id": item.get("dimension_id"),
            "temperature": item.get("temperature"),
            "status": item.get("status"),
        }
        for item in dimensions
    )
    facts.append(
        {
            "kind": "systemic_risk",
            "level": systemic_risk.get("level"),
            "red_flag_count": len(systemic_risk.get("red_flags", [])),
            "warning_count": len(systemic_risk.get("warnings", [])),
        }
    )
    return facts


def _code_fingerprint() -> str:
    digest = hashlib.sha256()
    base = Path(__file__).parent
    for name in _CODE_FILES:
        path = base / name
        digest.update(name.encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"missing")
    return digest.hexdigest()


def _file_sha256(path: Path | str | None) -> str | None:
    if path is None:
        return None
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


__all__ = [
    "SNAPSHOT_SCHEMA_VERSION",
    "build_cache_identity",
    "build_market_state_snapshot",
]
