"""TSMC 产能利用率历史基线 loader / 补齐逻辑单元测试。

覆盖：受版本管理基线文件本身的契约、loader 的全部校验分支、补齐语义
（只补缺失、不覆盖官方值、不外推基线外季度、幂等），以及接入 RAW 构建链路后的行为。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest
import yaml

from stock_data.fetcher.industry.semiconductor.baseline import (
    LEGACY_BASELINE_STATUS,
    TsmcUtilizationBaseline,
    apply_tsmc_utilization_baseline,
    load_tsmc_utilization_baseline,
    parse_utilization_raw,
    resolve_tsmc_utilization_baseline_path,
)
from stock_data.fetcher.industry.semiconductor.transforms import build_foundry_raw_frame

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BASELINE_PATH = (
    _REPO_ROOT / "config" / "industry" / "semiconductor" / "tsmc_utilization_baseline.yaml"
)
_LIVE_RAW = (
    _REPO_ROOT
    / "data"
    / "raw"
    / "industry"
    / "semiconductor"
    / "capacity"
    / "foundry_capacity_utilization.parquet"
)


def _write_baseline(
    tmp_path: Path,
    values: list[dict[str, object]],
    *,
    coverage: dict[str, object] | None = None,
    provenance: object = None,
    schema_version: object = 1,
) -> Path:
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "provenance": {"status": "verified_official"} if provenance is None else provenance,
        "coverage": coverage
        if coverage is not None
        else {
            "first_quarter": values[0]["report_quarter"],
            "last_quarter": values[-1]["report_quarter"],
            "quarter_count": len(values),
        },
        "values": values,
    }
    path = tmp_path / "tsmc_utilization_baseline.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path


def _raw_frame(rows: list[tuple[str, str | None, str]]) -> pl.DataFrame:
    """构造只含基线相关列的 RAW 片段。"""
    return pl.DataFrame(
        {
            "report_quarter": [row[0] for row in rows],
            "tsmc_utilization_raw": pl.Series(
                "tsmc_utilization_raw", [row[1] for row in rows], dtype=pl.String
            ),
            "tsmc_utilization_status": pl.Series(
                "tsmc_utilization_status", [row[2] for row in rows], dtype=pl.String
            ),
        }
    )


def _mini_baseline() -> TsmcUtilizationBaseline:
    return TsmcUtilizationBaseline(
        raw_by_quarter={"2016Q1": "94.0%", "2016Q2": "96.0%"},
        provenance_status="verified_official",
        source_path=Path("memory://mini"),
    )


# ---------------------------------------------------------------------------
# 随仓库发布的基线文件本身
# ---------------------------------------------------------------------------


def test_shipped_baseline_covers_declared_range() -> None:
    baseline = load_tsmc_utilization_baseline(_BASELINE_PATH)

    assert len(baseline.quarters) == 41
    assert baseline.quarters[0] == "2016Q1"
    assert baseline.quarters[-1] == "2026Q1"
    assert baseline.raw_for("2016Q1") == "94.0%"
    assert baseline.raw_for("2021Q3") == "101.0%"
    assert baseline.raw_for("2026Q1") == "96.5%"
    # 2026Q2 官方不再披露，基线必须不覆盖，否则就是伪造披露
    assert baseline.raw_for("2026Q2") is None
    assert baseline.utilization_pct_for("2016Q1") == 94.0


def test_shipped_baseline_declares_unverified_provenance() -> None:
    """来源未确权时必须如实声明，避免下游把带外注入值当官方披露引用。"""
    baseline = load_tsmc_utilization_baseline(_BASELINE_PATH)

    assert baseline.provenance_status == "unverified_upstream_injection"


def test_shipped_baseline_reproduces_live_raw_baseline_rows() -> None:
    """基线必须与线上 RAW 的 legacy_baseline 行逐值一致，否则重放会引入假差异。"""
    if not _LIVE_RAW.exists():
        pytest.skip("本地无 foundry RAW 快照，跳过线上对拍")

    live = pl.read_parquet(_LIVE_RAW).filter(
        pl.col("tsmc_utilization_status") == LEGACY_BASELINE_STATUS
    )
    live_map = {
        row["report_quarter"]: row["tsmc_utilization_raw"]
        for row in live.select(["report_quarter", "tsmc_utilization_raw"]).iter_rows(named=True)
    }

    assert live_map == load_tsmc_utilization_baseline(_BASELINE_PATH).raw_by_quarter


# ---------------------------------------------------------------------------
# loader 校验分支
# ---------------------------------------------------------------------------


def test_load_rejects_duplicate_quarter(tmp_path: Path) -> None:
    path = _write_baseline(
        tmp_path,
        [
            {"report_quarter": "2016Q1", "utilization_raw": "94.0%"},
            {"report_quarter": "2016Q1", "utilization_raw": "95.0%"},
        ],
    )

    with pytest.raises(ValueError, match="重复"):
        load_tsmc_utilization_baseline(path)


def test_load_rejects_malformed_quarter(tmp_path: Path) -> None:
    path = _write_baseline(tmp_path, [{"report_quarter": "2016-Q1", "utilization_raw": "94.0%"}])

    with pytest.raises(ValueError, match="report_quarter 非法"):
        load_tsmc_utilization_baseline(path)


def test_load_rejects_non_string_utilization_raw(tmp_path: Path) -> None:
    """utilization_raw 必须是原始披露字符串，浮点会破坏 RAW 逐字节复现。"""
    path = _write_baseline(tmp_path, [{"report_quarter": "2016Q1", "utilization_raw": 94.0}])

    with pytest.raises(ValueError, match="必须是保留原始"):
        load_tsmc_utilization_baseline(path)


def test_load_rejects_out_of_range_value(tmp_path: Path) -> None:
    path = _write_baseline(tmp_path, [{"report_quarter": "2016Q1", "utilization_raw": "0.0%"}])

    with pytest.raises(ValueError, match="越界"):
        load_tsmc_utilization_baseline(path)


def test_load_rejects_coverage_mismatch(tmp_path: Path) -> None:
    """coverage 声明与实际条目不一致说明改数后没同步声明，必须拦下。"""
    path = _write_baseline(
        tmp_path,
        [
            {"report_quarter": "2016Q1", "utilization_raw": "94.0%"},
            {"report_quarter": "2016Q2", "utilization_raw": "96.0%"},
        ],
        coverage={"first_quarter": "2016Q1", "last_quarter": "2016Q2", "quarter_count": 41},
    )

    with pytest.raises(ValueError, match=r"coverage\.quarter_count"):
        load_tsmc_utilization_baseline(path)


def test_load_rejects_missing_provenance(tmp_path: Path) -> None:
    path = _write_baseline(
        tmp_path,
        [{"report_quarter": "2016Q1", "utilization_raw": "94.0%"}],
        provenance={"note": "no status"},
    )

    with pytest.raises(ValueError, match=r"provenance\.status"):
        load_tsmc_utilization_baseline(path)


def test_load_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    path = _write_baseline(
        tmp_path, [{"report_quarter": "2016Q1", "utilization_raw": "94.0%"}], schema_version=99
    )

    with pytest.raises(ValueError, match="schema_version"):
        load_tsmc_utilization_baseline(path)


def test_resolve_raises_when_explicit_path_missing(tmp_path: Path) -> None:
    """缺基线必须显式报错，而不是静默跳过补齐（那正是本次要修的病）。"""
    with pytest.raises(FileNotFoundError, match="TSMC 利用率基线"):
        resolve_tsmc_utilization_baseline_path(tmp_path / "nope.yaml")


def test_parse_utilization_raw_accepts_official_three_digit_percent() -> None:
    assert parse_utilization_raw("101.0%") == 101.0
    assert parse_utilization_raw(" 96.5% ") == 96.5
    with pytest.raises(ValueError, match="无法解析"):
        parse_utilization_raw("94.0")


# ---------------------------------------------------------------------------
# 补齐语义
# ---------------------------------------------------------------------------


def test_apply_fills_missing_and_labels_legacy_baseline() -> None:
    frame = _raw_frame(
        [
            ("2016Q1", None, "unavailable"),
            ("2016Q2", "", "unavailable"),
        ]
    )

    filled = apply_tsmc_utilization_baseline(frame, _mini_baseline())

    assert filled["tsmc_utilization_raw"].to_list() == ["94.0%", "96.0%"]
    assert filled["tsmc_utilization_status"].to_list() == [
        LEGACY_BASELINE_STATUS,
        LEGACY_BASELINE_STATUS,
    ]


def test_apply_keeps_official_value_and_status_untouched() -> None:
    frame = _raw_frame([("2016Q1", "99.9%", "reported")])

    filled = apply_tsmc_utilization_baseline(frame, _mini_baseline())

    assert filled["tsmc_utilization_raw"].to_list() == ["99.9%"]
    assert filled["tsmc_utilization_status"].to_list() == ["reported"]
    assert filled.equals(frame)


def test_apply_never_invents_quarters_outside_baseline() -> None:
    """基线不覆盖的季度保持 NULL，不得外推或复用邻期值。"""
    frame = _raw_frame([("2026Q2", None, "unavailable")])

    filled = apply_tsmc_utilization_baseline(frame, _mini_baseline())

    assert filled["tsmc_utilization_raw"].to_list() == [None]
    assert filled["tsmc_utilization_status"].to_list() == ["unavailable"]


def test_apply_is_idempotent() -> None:
    frame = _raw_frame([("2016Q1", None, "unavailable")])

    once = apply_tsmc_utilization_baseline(frame, _mini_baseline())
    twice = apply_tsmc_utilization_baseline(once, _mini_baseline())

    assert once.equals(twice)


def test_apply_returns_frame_unchanged_when_nothing_to_fill() -> None:
    frame = _raw_frame([("2016Q1", "94.0%", LEGACY_BASELINE_STATUS)])

    assert apply_tsmc_utilization_baseline(frame, _mini_baseline()).equals(frame)


def test_apply_handles_empty_frame_without_touching_baseline() -> None:
    empty = pl.DataFrame(schema={"report_quarter": pl.String, "tsmc_utilization_raw": pl.String})

    assert apply_tsmc_utilization_baseline(empty, _mini_baseline()).height == 0


# ---------------------------------------------------------------------------
# 接入 RAW 构建链路
# ---------------------------------------------------------------------------


def _foundry_items(quarter: str, tsmc_raw: str | None) -> list[dict[str, object]]:
    return [
        {
            "report_quarter": quarter,
            "trade_date": date(2016, 3, 31),
            "tsmc_utilization_raw": tsmc_raw,
            "smic_utilization_raw": "98.8%",
            "smic_monthly_capacity_raw": "302.5千片",
            "smic_wafer_shipment_raw": "875.8千片",
            "release_date": date(2016, 4, 25),
        }
    ]


def test_build_foundry_raw_frame_fills_baseline_at_raw_stage() -> None:
    """官方值缺失时，RAW 构建阶段就应补齐并标注，使 live 与重放同源。"""
    raw_df = build_foundry_raw_frame(_foundry_items("2016Q1", None))

    assert raw_df["tsmc_utilization_raw"][0] == "94.0%"
    assert raw_df["tsmc_utilization_status"][0] == LEGACY_BASELINE_STATUS


def test_build_foundry_raw_frame_keeps_official_utilization() -> None:
    raw_df = build_foundry_raw_frame(_foundry_items("2016Q1", "93.3%"))

    assert raw_df["tsmc_utilization_raw"][0] == "93.3%"
    assert raw_df["tsmc_utilization_status"][0] != LEGACY_BASELINE_STATUS
