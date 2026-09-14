"""TSMC 产能利用率历史基线的显式加载与缺失补齐。

背景：台积电季度管理报告自 2020 年代起不再给出产能利用率数字（只留文字描述），
而历史季度是带数字披露的。这份历史数字此前只存在于线上 RAW 表里、由仓库外脚本
带外注入，导致 RAW 无法离线重放——全量重放会把 41 个季度的利用率与产能相态清零。

本模块把这份基线变成**受版本管理、可校验、可离线重放**的一等输入：

1. 唯一信任源是 ``config/industry/semiconductor/tsmc_utilization_baseline.yaml``；
2. :func:`load_tsmc_utilization_baseline` 做 schema / 季度格式 / 唯一性 / 取值域 /
   coverage 声明一致性全套校验，任何异常直接抛错而不静默降级；
3. :func:`apply_tsmc_utilization_baseline` 只在**官方值缺失**时补齐，并显式标注
   ``tsmc_utilization_status='legacy_baseline'``；官方值存在时一律不动。

它补的是历史已披露事实，不是对未来的推算：基线缺省的季度保持 NULL。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl
import yaml

logger = logging.getLogger(__name__)

LEGACY_BASELINE_STATUS = "legacy_baseline"
TSMC_UTILIZATION_BASELINE_PATH = (
    Path("config") / "industry" / "semiconductor" / "tsmc_utilization_baseline.yaml"
)
_SUPPORTED_SCHEMA_VERSION = 1
_QUARTER_PATTERN = re.compile(r"\d{4}Q[1-4]")
_UTILIZATION_RAW_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_MIN_UTILIZATION_PCT = 0.0
_MAX_UTILIZATION_PCT = 120.0
_MODULE_FALLBACK_LEVELS = 5


@dataclass(frozen=True)
class TsmcUtilizationBaseline:
    """受版本管理的台积电历史产能利用率基线。"""

    raw_by_quarter: dict[str, str] = field(default_factory=dict)
    provenance_status: str = "unknown"
    source_path: Path = TSMC_UTILIZATION_BASELINE_PATH

    @property
    def quarters(self) -> tuple[str, ...]:
        return tuple(self.raw_by_quarter)

    def raw_for(self, quarter: str) -> str | None:
        """返回该报告期的原始披露字符串（如 ``"94.0%"``）。"""
        return self.raw_by_quarter.get(quarter)

    def utilization_pct_for(self, quarter: str) -> float | None:
        raw = self.raw_for(quarter)
        return None if raw is None else parse_utilization_raw(raw)


def parse_utilization_raw(raw: str) -> float:
    """把原始披露字符串解析为百分数，并做物理区间校验。"""
    match = _UTILIZATION_RAW_PATTERN.fullmatch(raw.strip())
    if match is None:
        raise ValueError(f"TSMC 利用率基线取值无法解析: {raw!r}")
    value = float(match.group(1))
    if not _MIN_UTILIZATION_PCT < value <= _MAX_UTILIZATION_PCT:
        raise ValueError(f"TSMC 利用率基线取值越界 (0, {_MAX_UTILIZATION_PCT}]: {raw!r}")
    return value


def resolve_tsmc_utilization_baseline_path(path: Path | str | None = None) -> Path:
    """解析基线文件路径：显式路径优先，其次工作目录，最后回落到仓库根。"""
    if path is not None:
        candidate = Path(path)
        if not candidate.exists():
            raise FileNotFoundError(f"未找到 TSMC 利用率基线文件: {candidate}")
        return candidate
    for candidate in (TSMC_UTILIZATION_BASELINE_PATH, _module_relative_default_path()):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"未找到 TSMC 利用率基线文件，已尝试 {TSMC_UTILIZATION_BASELINE_PATH} 与仓库根相对路径。"
        "该文件是 foundry 产能利用率 RAW 的必需输入：缺省会让 TSMC 侧信号在重放时静默清零。"
    )


def load_tsmc_utilization_baseline(
    path: Path | str | None = None,
) -> TsmcUtilizationBaseline:
    """加载并校验受版本管理的 TSMC 历史产能利用率基线。"""
    resolved = resolve_tsmc_utilization_baseline_path(path)
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"TSMC 利用率基线 {resolved} 顶层必须是映射")
    version = payload.get("schema_version")
    if version != _SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            f"TSMC 利用率基线 {resolved} 的 schema_version={version!r}，"
            f"仅支持 {_SUPPORTED_SCHEMA_VERSION}"
        )
    entries = payload.get("values")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"TSMC 利用率基线 {resolved} 的 values 必须是非空列表")
    raw_by_quarter = _parse_entries(entries, path=resolved)
    _validate_coverage(payload.get("coverage"), raw_by_quarter, path=resolved)
    provenance_status = _parse_provenance(payload.get("provenance"), path=resolved)
    if provenance_status != "verified_official":
        logger.warning(
            "TSMC 利用率基线 %s 的来源状态为 %s：数值尚未与官方披露逐条核对，"
            "对外引用前必须先完成确权",
            resolved,
            provenance_status,
        )
    return TsmcUtilizationBaseline(
        raw_by_quarter=raw_by_quarter,
        provenance_status=provenance_status,
        source_path=resolved,
    )


def apply_tsmc_utilization_baseline(
    df_raw: pl.DataFrame,
    baseline: TsmcUtilizationBaseline | None = None,
) -> pl.DataFrame:
    """官方利用率缺失时按报告期补齐历史基线，并显式标注 ``legacy_baseline``。

    只在 ``tsmc_utilization_raw`` 为空时补齐；官方值存在时一行都不动。基线未覆盖的
    季度（如 2026Q2 起官方不再披露）保持 NULL，不得用基线伪装成已披露。
    """
    if df_raw.height == 0 or "report_quarter" not in df_raw.columns:
        return df_raw
    resolved = baseline or load_tsmc_utilization_baseline()
    if not resolved.raw_by_quarter:
        return df_raw
    df_work = _with_baseline_columns(df_raw)
    fill_values = pl.col("report_quarter").replace_strict(
        resolved.raw_by_quarter, default=None, return_dtype=pl.String
    )
    missing = pl.col("tsmc_utilization_raw").is_null() | (
        pl.col("tsmc_utilization_raw").cast(pl.String).str.strip_chars() == ""
    )
    fill_mask = missing & fill_values.is_not_null()
    filled_count = int(df_work.select(fill_mask.sum()).item() or 0)
    if filled_count == 0:
        return df_raw
    df_filled = df_work.with_columns(
        pl.when(fill_mask)
        .then(fill_values)
        .otherwise(pl.col("tsmc_utilization_raw").cast(pl.String))
        .alias("tsmc_utilization_raw"),
        pl.when(fill_mask)
        .then(pl.lit(LEGACY_BASELINE_STATUS))
        .otherwise(pl.col("tsmc_utilization_status").cast(pl.String))
        .alias("tsmc_utilization_status"),
    )
    logger.info(
        "foundry TSMC 利用率基线补齐 %d 行（status=%s，来源=%s）",
        filled_count,
        LEGACY_BASELINE_STATUS,
        resolved.source_path,
    )
    return df_filled


def _module_relative_default_path() -> Path:
    return (
        Path(__file__).resolve().parents[_MODULE_FALLBACK_LEVELS] / TSMC_UTILIZATION_BASELINE_PATH
    )


def _with_baseline_columns(df: pl.DataFrame) -> pl.DataFrame:
    additions = []
    if "tsmc_utilization_raw" not in df.columns:
        additions.append(pl.lit(None, dtype=pl.String).alias("tsmc_utilization_raw"))
    if "tsmc_utilization_status" not in df.columns:
        additions.append(pl.lit(None, dtype=pl.String).alias("tsmc_utilization_status"))
    return df.with_columns(additions) if additions else df


def _parse_entries(entries: list[Any], *, path: Path) -> dict[str, str]:
    raw_by_quarter: dict[str, str] = {}
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"TSMC 利用率基线 {path} 第 {index} 条 values 必须是映射")
        quarter = entry.get("report_quarter")
        if not isinstance(quarter, str) or _QUARTER_PATTERN.fullmatch(quarter) is None:
            raise ValueError(
                f"TSMC 利用率基线 {path} 第 {index} 条的 report_quarter 非法: {quarter!r}"
            )
        raw = entry.get("utilization_raw")
        if not isinstance(raw, str):
            raise ValueError(
                f"TSMC 利用率基线 {path} {quarter} 的 utilization_raw 必须是保留原始"
                f"披露的字符串，当前为 {raw!r}"
            )
        parse_utilization_raw(raw)
        if quarter in raw_by_quarter:
            raise ValueError(f"TSMC 利用率基线 {path} 存在重复 report_quarter: {quarter}")
        raw_by_quarter[quarter] = raw.strip()
    return dict(sorted(raw_by_quarter.items()))


def _validate_coverage(coverage: object, raw_by_quarter: dict[str, str], *, path: Path) -> None:
    if not isinstance(coverage, dict):
        raise ValueError(f"TSMC 利用率基线 {path} 缺少 coverage 声明")
    quarters = sorted(raw_by_quarter)
    expected = {
        "first_quarter": quarters[0],
        "last_quarter": quarters[-1],
        "quarter_count": len(quarters),
    }
    for name, actual in expected.items():
        declared = coverage.get(name)
        if declared != actual:
            raise ValueError(
                f"TSMC 利用率基线 {path} 的 coverage.{name} 声明 {declared!r} "
                f"与实际 {actual!r} 不一致（请同步更新 coverage）"
            )


def _parse_provenance(provenance: object, *, path: Path) -> str:
    if not isinstance(provenance, dict):
        raise ValueError(f"TSMC 利用率基线 {path} 缺少 provenance 声明")
    status = provenance.get("status")
    if not isinstance(status, str) or not status.strip():
        raise ValueError(f"TSMC 利用率基线 {path} 缺少 provenance.status")
    return status.strip()


__all__ = [
    "LEGACY_BASELINE_STATUS",
    "TSMC_UTILIZATION_BASELINE_PATH",
    "TsmcUtilizationBaseline",
    "apply_tsmc_utilization_baseline",
    "load_tsmc_utilization_baseline",
    "parse_utilization_raw",
    "resolve_tsmc_utilization_baseline_path",
]
