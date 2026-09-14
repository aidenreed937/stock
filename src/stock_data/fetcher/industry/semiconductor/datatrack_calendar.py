"""TrendForce DataTrack 内存基准见报日历的加载与校验。"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

DATATRACK_RELEASE_CALENDAR_PATH = (
    Path("config") / "industry" / "semiconductor" / "datatrack_release_calendar.yaml"
)
_SUPPORTED_SCHEMA_VERSION = 1
_MONTH_PATTERN = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")
_MODULE_FALLBACK_LEVELS = 5


def _module_relative_default_path() -> Path:
    anchor = Path(__file__).resolve()
    for _ in range(_MODULE_FALLBACK_LEVELS):
        anchor = anchor.parent
    return anchor / DATATRACK_RELEASE_CALENDAR_PATH


def resolve_datatrack_release_calendar_path(path: Path | str | None = None) -> Path:
    if path is not None:
        candidate = Path(path)
        if not candidate.exists():
            raise FileNotFoundError(f"未找到 DataTrack 见报日历文件: {candidate}")
        return candidate
    for candidate in (DATATRACK_RELEASE_CALENDAR_PATH, _module_relative_default_path()):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"未找到 DataTrack 见报日历文件，已尝试 {DATATRACK_RELEASE_CALENDAR_PATH}"
    )


def load_datatrack_release_calendar(
    path: Path | str | None = None,
) -> dict[str, date]:
    """加载受版本管理的 TrendForce DataTrack 见报日历。"""
    resolved = resolve_datatrack_release_calendar_path(path)
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"DataTrack 见报日历 {resolved} 顶层必须是映射")
    version = payload.get("schema_version")
    if version != _SUPPORTED_SCHEMA_VERSION:
        raise ValueError(f"不支持的 DataTrack 日历 schema_version: {version}")

    values = payload.get("values")
    if not isinstance(values, list):
        raise ValueError(f"DataTrack 见报日历 {resolved} 必须包含 values 列表")

    calendar: dict[str, date] = {}
    for entry in values:
        if not isinstance(entry, dict):
            raise ValueError(f"DataTrack 见报日历项必须是字典: {entry!r}")
        m_str = str(entry.get("report_month") or "").strip()
        d_str = str(entry.get("release_date") or "").strip()
        if not _MONTH_PATTERN.match(m_str):
            raise ValueError(f"DataTrack 见报日历月份格式非法: {m_str!r}")
        try:
            rel_date = date.fromisoformat(d_str)
        except ValueError as exc:
            raise ValueError(f"DataTrack 见报日历日期格式非法 ({m_str}): {d_str!r}") from exc
        if m_str in calendar:
            raise ValueError(f"DataTrack 见报日历存在重复月份: {m_str}")
        calendar[m_str] = rel_date

    coverage = payload.get("coverage")
    if isinstance(coverage, dict):
        expected_count = coverage.get("month_count")
        if expected_count is not None and len(calendar) != expected_count:
            raise ValueError(
                f"DataTrack 日历声明 month_count={expected_count} 但实际解析出 {len(calendar)} 个"
            )

    return calendar
