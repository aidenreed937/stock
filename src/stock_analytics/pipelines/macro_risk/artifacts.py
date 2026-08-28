"""宏观风险产物读取门面。

``stock_strategy`` 侧经 2-dot 包门面消费 ``macro_risk`` latest 产物，
避免外部消费者直连 analytics 实现模块 (见 docs/architecture/analytics-boundaries.md)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.pipelines.artifacts import resolve_artifact_run

_RISK_FACTORS_FILENAME = "risk_factors.parquet"
_DEFAULT_RISK_ROOT = "data/analytics/macro_risk"


def load_latest_risk_factors(
    artifact_root: Path | str = _DEFAULT_RISK_ROOT,
) -> tuple[Path, pl.DataFrame, dict[str, Any]]:
    """读取 ``macro_risk`` latest 双轨制风险因子面板。

    Args:
        artifact_root: 宏观风险产物根目录，默认 ``data/analytics/macro_risk``。

    Returns:
        ``(run_dir, frame, manifest)``：风险因子面板
        （至少含 ``trade_date`` / ``overheat_index`` / ``panic_index``）
        与产物 Manifest。

    Raises:
        ArtifactUnavailableError: latest 产物缺失或校验失败。
    """
    run = resolve_artifact_run(artifact_root, expected_artifact_type="macro_risk")
    frame = pl.read_parquet(run.path(_RISK_FACTORS_FILENAME))
    return run.run_dir, frame, run.manifest


__all__ = ["load_latest_risk_factors"]
