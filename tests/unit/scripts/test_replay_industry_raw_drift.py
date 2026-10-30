"""replay_industry_raw.py 重放回归护栏（ReplayDriftError）单元测试。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from runpy import run_path

import polars as pl
import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "replay_industry_raw.py"
_mod = run_path(str(_SCRIPT_PATH))
_regression_report = _mod["_regression_report"]
_format_drift = _mod["_format_drift"]
replay_metric = _mod["replay_metric"]
ReplayDriftError = _mod["ReplayDriftError"]

_KEYS = ["report_quarter", "symbol"]


def _frame(**columns: object) -> pl.DataFrame:
    return pl.DataFrame(columns)


def test_regression_report_flags_non_null_to_null() -> None:
    """上游带外补充的基线值被抹掉时，必须计入「非空→空」。"""
    existing = _frame(
        report_quarter=["2026Q1", "2026Q2"],
        symbol=["TSMC", "TSMC"],
        tsmc_utilization_pct=[94.0, 95.0],
    )
    incoming = _frame(
        report_quarter=["2026Q1", "2026Q2"],
        symbol=["TSMC", "TSMC"],
        tsmc_utilization_pct=pl.Series("tsmc_utilization_pct", [None, 95.0], dtype=pl.Float64),
    )

    to_null, changed = _regression_report(existing, incoming, _KEYS)

    assert to_null == {"tsmc_utilization_pct": 1}
    assert changed == {}


def test_regression_report_flags_value_change() -> None:
    """同一主键上取值的改写也要报告（例如被污染的口径被修正）。"""
    existing = _frame(
        report_quarter=["2026Q1"],
        symbol=["TSMC"],
        tsmc_utilization_status=["legacy_baseline"],
    )
    incoming = _frame(
        report_quarter=["2026Q1"],
        symbol=["TSMC"],
        tsmc_utilization_status=["unavailable"],
    )

    to_null, changed = _regression_report(existing, incoming, _KEYS)

    assert to_null == {}
    assert changed == {"tsmc_utilization_status": 1}


def test_regression_report_ignores_write_metadata() -> None:
    """每次重放都会刷新的行级元数据不参与改写判定。"""
    existing = _frame(
        report_quarter=["2026Q1"],
        symbol=["TSMC"],
        collected_at=["2026-09-09T08:10:18+00:00"],
        tsmc_utilization_pct=[94.0],
    )
    incoming = _frame(
        report_quarter=["2026Q1"],
        symbol=["TSMC"],
        collected_at=["2026-09-10T08:10:18+00:00"],
        tsmc_utilization_pct=[94.0],
    )

    assert _regression_report(existing, incoming, _KEYS) == ({}, {})


def test_regression_report_ignores_added_rows() -> None:
    """新增行不属于「改写既有事实」。"""
    existing = _frame(
        report_quarter=["2026Q1"],
        symbol=["TSMC"],
        tsmc_utilization_pct=[94.0],
    )
    incoming = _frame(
        report_quarter=["2026Q1", "2026Q2"],
        symbol=["TSMC", "TSMC"],
        tsmc_utilization_pct=[94.0, 95.0],
    )

    assert _regression_report(existing, incoming, _KEYS) == ({}, {})


def test_regression_report_falls_back_to_natural_key() -> None:
    """未声明主键的表回退到 report_month 对齐。"""
    existing = _frame(report_month=["2025-01"], source_url=["data/raw/a.html.gz"])
    incoming = _frame(report_month=["2025-01"], source_url=["other_root/raw/a.html.gz"])

    to_null, changed = _regression_report(existing, incoming, None)

    assert to_null == {}
    assert changed == {"source_url": 1}


def test_format_drift_lists_columns_and_gives_guidance() -> None:
    message = _format_drift("foundry_capacity_utilization", {"regime": 41}, {"proxy_method": 41})

    assert "foundry_capacity_utilization" in message
    assert "非空→空: regime=41" in message
    assert "值变化: proxy_method=41" in message
    assert "RAW" in message


def test_replay_metric_raises_when_strict_drift(tmp_path: Path) -> None:
    """落盘前命中改写且开启 --strict-drift 时必须中止，不静默覆盖。"""
    curated_root = tmp_path / "curated"
    target = curated_root / "semiconductor" / "capacity" / "demo.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "report_quarter": ["2026Q1"],
            "tsmc_utilization_pct": [94.0],
        }
    ).write_parquet(target)

    incoming = pl.DataFrame(
        {
            "report_quarter": ["2026Q1"],
            "trade_date": [date(2026, 3, 31)],
            "tsmc_utilization_pct": [None],
        }
    )
    plan = {
        "loader": lambda _raw_root: [{"ok": True}],
        "to_frame": lambda _records: incoming,
        "curated": "semiconductor/capacity/demo.parquet",
        "primary_keys": ["report_quarter"],
    }

    with pytest.raises(ReplayDriftError):
        replay_metric(
            "demo",
            plan,
            tmp_path / "raw",
            curated_root,
            dry_run=False,
            strict_drift=True,
        )

    preserved = pl.read_parquet(target)
    assert preserved["tsmc_utilization_pct"][0] == 94.0


def test_replay_metric_warns_without_strict_drift(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """未开启 --strict-drift 时只告警，仍按原语义落盘。"""
    curated_root = tmp_path / "curated"
    target = curated_root / "semiconductor" / "capacity" / "demo.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "report_quarter": ["2026Q1"],
            "tsmc_utilization_pct": [94.0],
        }
    ).write_parquet(target)

    incoming = pl.DataFrame(
        {
            "report_quarter": ["2026Q1"],
            "trade_date": [date(2026, 3, 31)],
            "tsmc_utilization_pct": [None],
        }
    )
    plan = {
        "loader": lambda _raw_root: [{"ok": True}],
        "to_frame": lambda _records: incoming,
        "curated": "semiconductor/capacity/demo.parquet",
        "primary_keys": ["report_quarter"],
    }

    with caplog.at_level("WARNING"):
        replay_metric("demo", plan, tmp_path / "raw", curated_root)

    assert "重放将改写既有 Curated 事实" in caplog.text
