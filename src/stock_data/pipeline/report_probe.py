"""低频财报探测的持久化冷却状态。"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_YFINANCE_FINANCIAL_PROBE_INTERVAL_DAYS = 7
YFINANCE_FINANCIAL_ENDPOINTS = frozenset({"financials", "balance_sheet", "cashflow"})
YFINANCE_FINANCIAL_PROBE_EPOCH = date(1970, 1, 1)
_LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class ReportProbeDecision:
    """判断某个报告期是否需要再次向上游探测。"""

    due: bool
    next_probe_at: datetime | None = None


def _as_utc(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_LOCAL_TIMEZONE)
    return current.astimezone(UTC)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _as_utc(parsed)


class YFinanceFinancialProbeStore:
    """记录 yfinance 财报无新报告结果，避免按日重复请求。"""

    def __init__(
        self,
        cache_root: Path | str,
        interval_days: int = DEFAULT_YFINANCE_FINANCIAL_PROBE_INTERVAL_DAYS,
    ) -> None:
        self.path = Path(cache_root) / "sync" / "yfinance_financial_reports.json"
        self.interval_days = max(1, int(interval_days))

    @staticmethod
    def _key(endpoint: str, symbol: str) -> str:
        return f"{endpoint.strip()}::{symbol.strip()}"

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): value for key, value in payload.items() if isinstance(value, dict)}

    def _save(self, state: Mapping[str, Mapping[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(dict(state), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def decide(
        self,
        endpoint: str,
        symbol: str,
        report_period: date | None,
        current_datetime: datetime | None = None,
    ) -> ReportProbeDecision:
        """判断指定报告期是否已经处于无新报告冷却期。"""
        state = self._load().get(self._key(endpoint, symbol))
        expected_period = report_period.isoformat() if report_period is not None else None
        if not state or state.get("report_period") != expected_period:
            return ReportProbeDecision(due=True)

        last_checked_at = _parse_datetime(state.get("last_checked_at"))
        if last_checked_at is None:
            return ReportProbeDecision(due=True)

        next_probe_at = last_checked_at + timedelta(days=self.interval_days)
        if _as_utc(current_datetime) < next_probe_at:
            return ReportProbeDecision(due=False, next_probe_at=next_probe_at)
        return ReportProbeDecision(due=True)

    def record_results(
        self,
        results: Iterable[Any],
        *,
        latest_watermarks: Mapping[tuple[str, str], date | None] | None = None,
        probe_targets: Mapping[tuple[str, str], date | None] | None = None,
        current_datetime: datetime | None = None,
    ) -> None:
        """根据本次同步结果记录无新报告探测或清除过期状态。"""
        checked_at = _as_utc(current_datetime)
        state = self._load()
        changed = False
        latest = latest_watermarks or {}
        targets = probe_targets or {}
        for result in results:
            endpoint = str(getattr(result, "endpoint", ""))
            symbol = str(getattr(result, "symbol", ""))
            if (
                getattr(result, "data_source", "") != "yfinance"
                or endpoint not in YFINANCE_FINANCIAL_ENDPOINTS
                or not symbol
            ):
                continue

            key = self._key(endpoint, symbol)
            current_watermark = latest.get((endpoint, symbol))
            probe_target = targets.get((endpoint, symbol), result.end_date)
            status = getattr(result, "status", "")
            if status in {"NO_DATA_SOURCE", "SUCCESS"}:
                report_period = probe_target
                if current_watermark is not None and (
                    report_period is None or current_watermark > report_period
                ):
                    report_period = current_watermark
                state[key] = {
                    "report_period": report_period.isoformat() if report_period else None,
                    "last_checked_at": checked_at.isoformat(),
                }
                changed = True

        if changed:
            self._save(state)


__all__ = [
    "DEFAULT_YFINANCE_FINANCIAL_PROBE_INTERVAL_DAYS",
    "YFINANCE_FINANCIAL_ENDPOINTS",
    "YFINANCE_FINANCIAL_PROBE_EPOCH",
    "ReportProbeDecision",
    "YFinanceFinancialProbeStore",
]
