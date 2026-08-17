"""融资融券无量纲数值质量规则。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import exp, isfinite, log
from statistics import median

import polars as pl

from stock_data.cleaner.date_utils import parse_mixed_date

MARGIN_NUMERIC_COLUMNS: tuple[str, ...] = (
    "rzye",
    "rzmre",
    "rzche",
    "rqye",
    "rqmcl",
    "rzrqye",
    "rqyl",
)
MARGIN_BALANCE_COLUMNS: tuple[str, ...] = ("rzye", "rqye", "rzrqye")
_BALANCE_RESIDUAL_TOLERANCE = 1e-6
_COMMON_SCALE_MIN_FIELDS = 3
_COMMON_SCALE_MIN_FACTOR = 10.0
_TEMPORAL_MIN_FACTOR = 2.0
_TEMPORAL_MIN_OBSERVATIONS = 8
_MAX_WARNINGS = 50


@dataclass(frozen=True)
class MarginQualityReport:
    """两融质量检查结果；errors 阻断落盘，warnings 仅供审计观察。"""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        """返回硬校验是否全部通过。"""
        return not self.errors


def margin_quality_issues(frame: pl.DataFrame) -> list[str]:
    """返回帧内硬质量问题；空列表表示数值检查通过。"""
    if frame.is_empty():
        return []

    issues: list[str] = []
    numeric_values: dict[str, pl.Series] = {}
    for column in MARGIN_NUMERIC_COLUMNS:
        if column not in frame.columns:
            continue
        raw = frame.get_column(column)
        values = raw.cast(pl.Float64, strict=False)
        numeric_values[column] = values

        finite = values.is_finite().fill_null(value=False)
        invalid_count = int(((~raw.is_null()) & (values.is_null() | ~finite)).sum())
        if invalid_count:
            issues.append(f"字段 [{column}] 存在 {invalid_count} 条非数值或非有限值")

        negative_count = int(((values < 0) & finite).sum())
        if negative_count:
            issues.append(f"字段 [{column}] 存在 {negative_count} 条负值")

    if set(MARGIN_BALANCE_COLUMNS).issubset(numeric_values):
        issues.extend(_balance_identity_issues(frame, numeric_values))

    return issues


def margin_quality_report(
    frame: pl.DataFrame,
    *,
    previous: pl.DataFrame | None = None,
    temporal_z_threshold: float = 6.0,
) -> MarginQualityReport:
    """运行硬校验和无量纲时间序列告警。"""
    return MarginQualityReport(
        errors=tuple(margin_quality_issues(frame)),
        warnings=(
            *_margin_null_warnings(frame),
            *margin_temporal_warnings(
                frame, previous=previous, temporal_z_threshold=temporal_z_threshold
            ),
        ),
    )


def margin_temporal_warnings(
    frame: pl.DataFrame,
    *,
    previous: pl.DataFrame | None = None,
    temporal_z_threshold: float = 6.0,
) -> list[str]:
    """用对数变化、MAD 和统一倍率检测时间序列异常。"""
    combined = _combine_history(frame, previous)
    if combined.is_empty():
        return []

    numeric_columns = [column for column in MARGIN_NUMERIC_COLUMNS if column in combined.columns]
    if not numeric_columns or not {"_margin_date", "_margin_exchange"}.issubset(combined.columns):
        return []

    transitions = _margin_transitions(combined, numeric_columns)

    if not transitions:
        return []

    warnings: list[str] = []
    warnings.extend(_common_scale_warnings(transitions))

    warnings.extend(_robust_temporal_warnings(transitions, numeric_columns, temporal_z_threshold))
    return warnings[:_MAX_WARNINGS]


def _margin_transitions(
    frame: pl.DataFrame, numeric_columns: list[str]
) -> list[tuple[date, str, dict[str, float]]]:
    transitions: list[tuple[date, str, dict[str, float]]] = []
    grouped = frame.sort(["_margin_exchange", "_margin_date"]).partition_by(
        "_margin_exchange", as_dict=True
    )
    for exchange, exchange_frame in grouped.items():
        transitions.extend(
            _exchange_transitions(_exchange_label(exchange), exchange_frame, numeric_columns)
        )
    return transitions


def _exchange_transitions(
    exchange: str, frame: pl.DataFrame, numeric_columns: list[str]
) -> list[tuple[date, str, dict[str, float]]]:
    transitions: list[tuple[date, str, dict[str, float]]] = []
    previous_row: dict[str, object] | None = None
    for current_row in frame.iter_rows(named=True):
        if previous_row is not None:
            changes = _row_log_changes(previous_row, current_row, numeric_columns)
            current_date = _as_date(current_row.get("_margin_date"))
            if changes and current_date is not None:
                transitions.append((current_date, exchange, changes))
        previous_row = current_row
    return transitions


def _row_log_changes(
    previous_row: dict[str, object],
    current_row: dict[str, object],
    numeric_columns: list[str],
) -> dict[str, float]:
    changes: dict[str, float] = {}
    for column in numeric_columns:
        previous_value = _finite_positive(previous_row.get(column))
        current_value = _finite_positive(current_row.get(column))
        if previous_value is None or current_value is None:
            continue
        changes[column] = log(current_value / previous_value)
    return changes


def _robust_temporal_warnings(
    transitions: list[tuple[date, str, dict[str, float]]],
    numeric_columns: list[str],
    temporal_z_threshold: float,
) -> list[str]:
    warnings: list[str] = []
    for column in numeric_columns:
        observations = [
            (target_date, exchange, changes[column])
            for target_date, exchange, changes in transitions
            if column in changes
        ]
        if len(observations) < _TEMPORAL_MIN_OBSERVATIONS:
            continue
        for target_date, exchange, value in _temporal_outliers(observations, temporal_z_threshold):
            warnings.append(
                f"{target_date}/{exchange}: 字段 [{column}] 日变化 {exp(value):.4g} 倍，"
                f"超过 robust z 阈值 {temporal_z_threshold:g}"
            )
            if len(warnings) >= _MAX_WARNINGS:
                return warnings[:_MAX_WARNINGS]
    return warnings


def _temporal_outliers(
    observations: list[tuple[date, str, float]], temporal_z_threshold: float
) -> list[tuple[date, str, float]]:
    center = median(value for _, _, value in observations)
    mad = median(abs(value - center) for _, _, value in observations)
    if mad > 1e-12:
        return [
            (target_date, exchange, value)
            for target_date, exchange, value in observations
            if (
                0.6745 * abs(value - center) / mad > temporal_z_threshold
                and abs(value - center) >= log(_TEMPORAL_MIN_FACTOR)
            )
        ]
    return [
        (target_date, exchange, value)
        for target_date, exchange, value in observations
        if abs(value - center) >= log(_COMMON_SCALE_MIN_FACTOR)
    ]


def _balance_identity_issues(
    frame: pl.DataFrame, numeric_values: dict[str, pl.Series]
) -> list[str]:
    issues: list[str] = []
    selected = frame.select(
        [
            "trade_date" if "trade_date" in frame.columns else pl.lit(None).alias("trade_date"),
            "exchange_id" if "exchange_id" in frame.columns else pl.lit(None).alias("exchange_id"),
            *[numeric_values[column].alias(column) for column in MARGIN_BALANCE_COLUMNS],
        ]
    )
    for row in selected.iter_rows(named=True):
        rzye = _finite_value(row.get("rzye"))
        rqye = _finite_value(row.get("rqye"))
        rzrqye = _finite_value(row.get("rzrqye"))
        if rzye is None or rqye is None or rzrqye is None:
            continue
        denominator = max(abs(rzrqye), abs(rzye + rqye), 1.0)
        residual = abs(rzrqye - rzye - rqye) / denominator
        if residual > _BALANCE_RESIDUAL_TOLERANCE:
            label = f"{row.get('trade_date', '?')}/{row.get('exchange_id', '?')}"
            issues.append(f"{label}: rzrqye 与 rzye+rqye 相对残差 {residual:.4g}")
        if rzrqye > 0:
            for column, value in (("rzye", rzye), ("rqye", rqye)):
                share = value / rzrqye
                if not -_BALANCE_RESIDUAL_TOLERANCE <= share <= 1 + _BALANCE_RESIDUAL_TOLERANCE:
                    label = f"{row.get('trade_date', '?')}/{row.get('exchange_id', '?')}"
                    issues.append(f"{label}: {column}/rzrqye 比例越界 {share:.4g}")
    return issues


def _margin_null_warnings(frame: pl.DataFrame) -> list[str]:
    warnings: list[str] = []
    for column in MARGIN_NUMERIC_COLUMNS:
        if column not in frame.columns:
            continue
        null_count = frame.get_column(column).null_count()
        if null_count:
            warnings.append(f"字段 [{column}] 存在 {null_count} 条空值")
    return warnings


def _combine_history(frame: pl.DataFrame, previous: pl.DataFrame | None) -> pl.DataFrame:
    frames = [
        candidate
        for candidate in (previous, frame)
        if candidate is not None and not candidate.is_empty()
    ]
    if not frames:
        return pl.DataFrame()
    combined = pl.concat(frames, how="diagonal_relaxed")
    required = {"trade_date", "exchange_id"}
    if not required.issubset(combined.columns):
        return pl.DataFrame()
    combined = combined.with_columns(
        [
            parse_mixed_date("trade_date").alias("_margin_date"),
            pl.col("exchange_id")
            .cast(pl.Utf8, strict=False)
            .str.strip_chars()
            .str.to_uppercase()
            .alias("_margin_exchange"),
        ]
    ).drop_nulls(["_margin_date", "_margin_exchange"])
    return combined.unique(subset=["_margin_date", "_margin_exchange"], keep="last")


def _common_scale_warnings(transitions: list[tuple[date, str, dict[str, float]]]) -> list[str]:
    warnings: list[str] = []
    minimum_log_factor = log(_COMMON_SCALE_MIN_FACTOR)
    for target_date, exchange, changes in transitions:
        if len(changes) < _COMMON_SCALE_MIN_FIELDS:
            continue
        center = median(changes.values())
        dispersion = median(abs(value - center) for value in changes.values())
        if abs(center) >= minimum_log_factor and dispersion <= 0.15:
            warnings.append(
                f"{target_date}/{exchange}: 多个字段同步变化，疑似统一倍率变化 "
                f"约 {exp(center):.4g} 倍"
            )
    return warnings


def _exchange_label(value: object) -> str:
    if isinstance(value, tuple) and len(value) == 1:
        return str(value[0])
    return str(value)


def _finite_value(value: object) -> float | None:
    try:
        parsed = float(str(value)) if value is not None else None
    except (TypeError, ValueError):
        return None
    return parsed if parsed is not None and isfinite(parsed) else None


def _finite_positive(value: object) -> float | None:
    parsed = _finite_value(value)
    return parsed if parsed is not None and parsed > 0 else None


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None
