"""分析产物的数据口径与质量报告。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import polars as pl

DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def is_dataset_lagging(
    latest: date, as_of_date: date, *, required: bool, max_lag_days: int
) -> bool:
    """判断数据集最新日期是否超过其质量配置允许的滞后。"""
    return (required or max_lag_days > 0) and latest < as_of_date - timedelta(days=max_lag_days)


@dataclass(frozen=True, slots=True)
class DatasetQualitySpec:
    """从分析配置抽取的数据集质量约束。"""

    data_source: str
    dataset: str
    dimension: str
    required: bool
    date_column: str
    max_lag_days: int
    static: bool
    cadence: str
    quality_tier: str
    note: str
    in_score: bool

    @classmethod
    def from_config(cls, item: Any) -> DatasetQualitySpec:
        """从市场温度计或行业结构 DatasetConfig 构造质量约束。"""
        return cls(
            data_source=str(item.data_source),
            dataset=str(item.dataset),
            dimension=str(getattr(item, "dimension", "")),
            required=bool(getattr(item, "required", False)),
            date_column=str(getattr(item, "date_column", "")),
            max_lag_days=int(getattr(item, "max_lag_days", 0)),
            static=bool(getattr(item, "static", False)),
            cadence=str(getattr(item, "cadence", "unspecified") or "unspecified"),
            quality_tier=str(getattr(item, "quality_tier", "optional") or "optional"),
            note=str(getattr(item, "note", "")),
            in_score=bool(getattr(item, "in_score", False)),
        )

    @property
    def key(self) -> tuple[str, str]:
        """返回数据源和数据集组成的稳定键。"""
        return (self.data_source, self.dataset)


def build_quality_report(  # noqa: PLR0913
    *,
    title: str,
    manifest: dict[str, Any],
    facts: pl.DataFrame,
    datasets: tuple[Any, ...],
    primary_data_source: str,
    primary_dataset: str,
    main_window: int,
    short_windows: tuple[int, ...] = (),
    medium_windows: tuple[int, ...] = (),
    period_note: str = "",
) -> dict[str, Any]:
    """基于配置、manifest 和 facts 构造机器可读质量报告。"""
    as_of_date = _parse_iso_date(str(manifest["as_of_date"]))
    specs = tuple(DatasetQualitySpec.from_config(item) for item in datasets)
    fact_rows = facts.to_dicts() if not facts.is_empty() else []
    windows = _analysis_windows(fact_rows)
    watermarks = _dataset_watermarks(
        as_of_date=as_of_date,
        fact_rows=fact_rows,
        specs=specs,
    )
    issues = _quality_issues(
        as_of_date=as_of_date,
        fact_rows=fact_rows,
        windows=windows,
        watermarks=watermarks,
        specs=specs,
        main_window=main_window,
    )
    status = _overall_status(issues)
    return {
        "schema_version": 1,
        "title": f"{title}口径与质量报告",
        "status": status,
        "as_of_date": as_of_date.isoformat(),
        "period_policy": {
            "primary_data_source": primary_data_source,
            "primary_dataset": primary_dataset,
            "main_window": main_window,
            "short_windows": list(short_windows),
            "medium_windows": list(medium_windows),
            "window_unit": "已落盘交易日",
            "period_note": period_note,
        },
        "constraints": [
            {
                "id": "as_of_date",
                "level": "hard",
                "rule": "所有报告标题、manifest、事实表基准日必须一致。",
            },
            {
                "id": "main_window",
                "level": "hard",
                "rule": "主窗口必须覆盖配置要求的已落盘交易日数量。",
            },
            {
                "id": "no_future_metric",
                "level": "hard",
                "rule": "非水位事实中的实际指标日期不得晚于基准日。",
            },
            {
                "id": "required_dataset_lag",
                "level": "hard",
                "rule": "必需数据集必须可用，并满足配置的最大滞后天数。",
            },
            {
                "id": "optional_dataset_lag",
                "level": "soft",
                "rule": "可选数据集若配置最大滞后天数，超限时只作为质量警告。",
            },
            {
                "id": "in_score_dataset_staleness",
                "level": "soft",
                "rule": "进入评分的可选数据集若超过滞后阈值，标记陈旧影响，"
                "对应维度分数可能偏向陈旧状态。",
            },
        ],
        "windows": windows,
        "watermarks": watermarks,
        "issues": issues,
        "summary": {
            "dataset_count": len(watermarks),
            "required_dataset_count": sum(1 for item in specs if item.required),
            "error_count": sum(1 for item in issues if item["severity"] == "error"),
            "warning_count": sum(1 for item in issues if item["severity"] == "warning"),
        },
    }


def _analysis_windows(fact_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [row for row in fact_rows if row.get("category") == "analysis_window"]
    rows.sort(key=lambda row: int(row.get("window") or 0))
    return [
        {
            "window": int(row.get("window") or 0),
            "period": str(row.get("value_text") or ""),
            "sample_size": int(row.get("sample_size") or 0),
            "status": str(row.get("status") or ""),
            "source": str(row.get("source") or ""),
            "note": str(row.get("note") or ""),
        }
        for row in rows
    ]


def _dataset_watermarks(
    *,
    as_of_date: date,
    fact_rows: list[dict[str, Any]],
    specs: tuple[DatasetQualitySpec, ...],
) -> list[dict[str, Any]]:
    facts_by_key = {
        (str(row.get("data_source") or ""), str(row.get("dataset") or "")): row
        for row in fact_rows
        if row.get("category") == "data_watermark"
    }
    rows: list[dict[str, Any]] = []
    for spec in specs:
        fact = facts_by_key.get(spec.key, {})
        latest_text = str(fact.get("value_text") or "")
        latest_date = None if latest_text == "static" else _maybe_parse_iso_date(latest_text)
        lag_days = (as_of_date - latest_date).days if latest_date is not None else None
        rows.append(
            {
                "data_source": spec.data_source,
                "dataset": spec.dataset,
                "dimension": spec.dimension,
                "required": spec.required,
                "cadence": spec.cadence,
                "quality_tier": spec.quality_tier,
                "date_column": spec.date_column or "trade_date",
                "max_lag_days": spec.max_lag_days,
                "static": spec.static,
                "in_score": spec.in_score,
                "latest": latest_text,
                "lag_days": lag_days,
                "status": str(fact.get("status") or "missing_fact"),
                "sample_size": fact.get("sample_size"),
                "note": spec.note,
            }
        )
    return rows


def _quality_issues(  # noqa: PLR0913
    *,
    as_of_date: date,
    fact_rows: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    watermarks: list[dict[str, Any]],
    specs: tuple[DatasetQualitySpec, ...],
    main_window: int,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    main_window_rows = [row for row in windows if row["window"] == main_window]
    if not main_window_rows:
        issues.append(_issue("error", "main_window_missing", f"缺少 {main_window} 日主窗口事实。"))
    else:
        row = main_window_rows[0]
        if row["status"] != "ok" or int(row["sample_size"]) < main_window:
            issues.append(
                _issue(
                    "error",
                    "main_window_insufficient",
                    f"{main_window} 日主窗口样本不足: {row['sample_size']}。",
                )
            )

    issues.extend(_fact_as_of_issues(as_of_date, fact_rows))

    required_keys = {spec.key for spec in specs if spec.required}
    for row in watermarks:
        key = (str(row["data_source"]), str(row["dataset"]))
        required = key in required_keys
        status = str(row["status"])
        if status in {"missing", "error", "missing_fact"}:
            severity = "error" if required else "warning"
            issues.append(
                _issue(severity, "dataset_unavailable", f"{_dataset_name(row)} 状态为 {status}。")
            )
            continue
        if status == "unavailable":
            issues.append(
                _issue("warning", "dataset_optional_unavailable", f"{_dataset_name(row)} 不可用。")
            )
        if status == "future":
            issues.append(
                _issue(
                    "warning",
                    "dataset_watermark_after_as_of",
                    f"{_dataset_name(row)} 全表水位晚于基准日；"
                    "历史回看时需确认计算已按基准日过滤。",
                )
            )
        if status == "lagging":
            severity = "error" if required else "warning"
            issues.append(
                _issue(
                    severity,
                    _lag_issue_id(row, fallback="dataset_lagging"),
                    f"{_dataset_name(row)} 超过配置滞后阈值。{_lag_issue_suffix(row)}",
                )
            )
        lag_days = row.get("lag_days")
        max_lag_days = int(row.get("max_lag_days") or 0)
        has_lag_rule = required or max_lag_days > 0
        if (
            has_lag_rule
            and lag_days is not None
            and int(lag_days) > max_lag_days
            and status not in {"lagging", "missing", "error"}
        ):
            severity = "error" if required else "warning"
            issues.append(
                _issue(
                    severity,
                    _lag_issue_id(row, fallback="dataset_lag_exceeded"),
                    f"{_dataset_name(row)} 滞后 {lag_days} 天，阈值 {max_lag_days} 天。"
                    f"{_lag_issue_suffix(row)}",
                )
            )

    issues.extend(_future_metric_issues(as_of_date, fact_rows))
    return issues


def _fact_as_of_issues(as_of_date: date, fact_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for row in fact_rows:
        fact_as_of = _parse_date_object(row.get("as_of_date"))
        if fact_as_of is None:
            issues.append(
                _issue(
                    "error",
                    "fact_as_of_missing",
                    f"{row.get('fact_id')} 缺少 as_of_date。",
                )
            )
        elif fact_as_of != as_of_date:
            issues.append(
                _issue(
                    "error",
                    "fact_as_of_mismatch",
                    f"{row.get('fact_id')} as_of_date={fact_as_of.isoformat()}，"
                    f"与基准日 {as_of_date.isoformat()} 不一致。",
                )
            )
    return issues


def _future_metric_issues(
    as_of_date: date,
    fact_rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for row in fact_rows:
        if row.get("category") == "data_watermark":
            continue
        text = f"{row.get('value_text') or ''}; {row.get('note') or ''}"
        for value in _dates_in_text(text):
            if value > as_of_date:
                issues.append(
                    _issue(
                        "error",
                        "future_metric_date",
                        f"{row.get('fact_id')} 使用了晚于基准日的日期 {value.isoformat()}。",
                    )
                )
    return issues


def _lag_issue_id(row: dict[str, Any], *, fallback: str) -> str:
    if bool(row.get("in_score")) and not bool(row.get("required")):
        return "dataset_stale_in_score"
    return fallback


def _lag_issue_suffix(row: dict[str, Any]) -> str:
    if bool(row.get("in_score")) and not bool(row.get("required")):
        return "该数据集已进入评分，陈旧值会影响对应维度温度。"
    return ""


def _issue(severity: str, issue_id: str, message: str) -> dict[str, str]:
    return {"severity": severity, "id": issue_id, "message": message}


def _overall_status(issues: list[dict[str, str]]) -> str:
    if any(item["severity"] == "error" for item in issues):
        return "failed"
    if any(item["severity"] == "warning" for item in issues):
        return "passed_with_warnings"
    return "passed"


def _dataset_name(row: dict[str, Any]) -> str:
    return f"{row['data_source']}.{row['dataset']}"


def _dates_in_text(text: str) -> list[date]:
    return [_parse_iso_date(value) for value in DATE_PATTERN.findall(text)]


def _maybe_parse_iso_date(value: str) -> date | None:
    try:
        return _parse_iso_date(value)
    except ValueError:
        return None


def _parse_date_object(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return _maybe_parse_iso_date(value)
    return None


def _parse_iso_date(value: str) -> date:
    return date.fromisoformat(value[:10])
