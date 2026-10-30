"""两融无量纲数据质量规则测试。"""

from datetime import date, timedelta

import polars as pl

from stock_data.governance.quality.margin_quality import (
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


def _regime_frame(
    start: date,
    *,
    days: int = 20,
    jump_at: int = 8,
    factor: float = 12.0,
    exchange: str = "SSE",
) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for index in range(days):
        scale = factor if index >= jump_at else 1.0
        rzye = 100.0 * scale
        rqye = 20.0 * scale
        rows.append(
            {
                "trade_date": start + timedelta(days=index),
                "exchange_id": exchange,
                "rzye": rzye,
                "rzmre": 10.0 * scale,
                "rzche": 5.0 * scale,
                "rqye": rqye,
                "rqmcl": 30.0 * scale,
                "rzrqye": rzye + rqye,
                "rqyl": 40.0 * scale,
            }
        )
    return pl.DataFrame(rows)


def test_margin_temporal_warnings_suppress_known_regime_break() -> None:
    """2010 年两融试点开闸的余额跳升属制度性断点，不应作为数据异常告警。"""
    frame = _regime_frame(date(2010, 3, 25))

    assert margin_temporal_warnings(frame) == []


def test_margin_temporal_warnings_keep_jump_outside_regime_break() -> None:
    """非制度性断点区间的同等跳变仍需照常告警。"""
    frame = _regime_frame(date(2015, 5, 20))

    warnings = margin_temporal_warnings(frame)

    assert any("2015-05-28" in warning for warning in warnings)


def test_is_known_regime_break_covers_bse_relaunch_window() -> None:
    from stock_data.governance.quality.margin_quality import is_known_regime_break

    assert is_known_regime_break("BSE", date(2023, 6, 20)) is True
    assert is_known_regime_break("bse", date(2024, 6, 20)) is False
    assert is_known_regime_break("SSE", date(2023, 6, 20)) is False


def _margin_row(exchange: str, trade_date: date, rzche: float | None) -> dict[str, object]:
    rzye = 100.0
    rqye = 20.0
    return {
        "trade_date": trade_date,
        "exchange_id": exchange,
        "rzye": rzye,
        "rzmre": 10.0,
        "rzche": rzche,
        "rqye": rqye,
        "rqmcl": 30.0,
        "rzrqye": rzye + rqye,
        "rqyl": 40.0,
    }


def test_margin_null_warnings_annotate_known_quarantine() -> None:
    """BSE 2023-06~09 的 rzche 空值来自上游负值隔离，告警需自带可审计说明。"""
    frame = pl.DataFrame(
        [
            _margin_row("BSE", date(2023, 6, 20), None),
            _margin_row("BSE", date(2023, 6, 21), None),
        ]
    )

    warnings = margin_quality_report(frame).warnings
    rzche_warning = next(warning for warning in warnings if "rzche" in warning)

    assert "审计隔离" in rzche_warning
    assert "history_repair" in rzche_warning


def test_margin_null_warnings_stay_plain_outside_known_window() -> None:
    """窗口外的空值不能被标注为已知隔离。"""
    frame = pl.DataFrame([_margin_row("BSE", date(2024, 1, 2), None)])

    warnings = margin_quality_report(frame).warnings
    rzche_warning = next(warning for warning in warnings if "rzche" in warning)

    assert "审计隔离" not in rzche_warning
