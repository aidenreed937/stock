"""两融无量纲数据质量规则测试。"""

from datetime import date, timedelta

import polars as pl

from stock.data.quality.margin_quality import (
    margin_quality_issues,
    margin_quality_report,
    margin_temporal_warnings,
)


def _margin_frame(days: int = 1, scale: list[float] | None = None) -> pl.DataFrame:
    factors = scale or [1.0] * days
    rows: list[dict[str, object]] = []
    for index, factor in enumerate(factors):
        rzye = 100.0 * factor
        rqye = 20.0 * factor
        rows.append(
            {
                "trade_date": date(2026, 1, 1) + timedelta(days=index),
                "exchange_id": "SSE",
                "rzye": rzye,
                "rzmre": 10.0 * factor,
                "rzche": 5.0 * factor,
                "rqye": rqye,
                "rqmcl": 30.0 * factor,
                "rzrqye": rzye + rqye,
                "rqyl": 40.0 * factor,
            }
        )
    return pl.DataFrame(rows)


def test_margin_quality_accepts_nonnegative_balanced_data() -> None:
    assert margin_quality_issues(_margin_frame()) == []


def test_margin_quality_rejects_negative_values_and_balance_residual() -> None:
    frame = _margin_frame().with_columns(
        pl.lit(-1.0).alias("rqyl"),
        pl.lit(130.0).alias("rzrqye"),
    )

    issues = margin_quality_issues(frame)

    assert any("rqyl" in issue and "负值" in issue for issue in issues)
    assert any("rzrqye 与 rzye+rqye" in issue for issue in issues)


def test_margin_quality_reports_historical_nulls_as_warnings() -> None:
    frame = _margin_frame().with_columns(pl.lit(None).cast(pl.Float64).alias("rqyl"))

    report = margin_quality_report(frame)

    assert report.errors == ()
    assert any("rqyl" in warning and "空值" in warning for warning in report.warnings)


def test_margin_temporal_warnings_detect_common_scale_shift() -> None:
    frame = _margin_frame(days=10, scale=[1.0] * 9 + [1000.0])

    report = margin_quality_report(frame)

    assert report.errors == ()
    assert any("疑似统一倍率变化" in warning for warning in report.warnings)
    assert any("1000" in warning for warning in report.warnings)


def test_margin_temporal_warnings_compare_previous_history() -> None:
    previous = _margin_frame()
    current = _margin_frame(days=1, scale=[1000.0]).with_columns(
        pl.lit(date(2026, 1, 2)).alias("trade_date")
    )

    warnings = margin_temporal_warnings(current, previous=previous)

    assert any("疑似统一倍率变化" in warning for warning in warnings)
