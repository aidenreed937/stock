"""宏观风控 IC 稳定性复审单元测试。

覆盖：
- 稳定/漂移/样本不足三种判定；
- 与上次快照对比的新漂移标记；
- ``build_stability_review`` 产出报告与快照。
"""

from __future__ import annotations

import polars as pl

from stock_strategy.macro.ic_review import (
    StabilityThresholds,
    build_stability_review,
    compare_with_previous,
    compute_sign_stability,
    load_snapshot,
    report_new_drift,
)

_YEARLY_SCHEMA = {
    "year": pl.Int64,
    "factor": pl.String,
    "horizon": pl.Int64,
    "ic": pl.Float64,
    "n": pl.Int64,
}


def _yearly_frame(factor_signs: dict[str, list[float | None]]) -> pl.DataFrame:
    """由 {因子: 逐年 IC} 构造 ic_yearly 长表。"""
    rows: list[dict] = []
    for factor, ics in factor_signs.items():
        for year, ic in enumerate(ics, start=2015):
            rows.append({"year": year, "factor": factor, "horizon": 60, "ic": ic, "n": 100})
    return pl.DataFrame(rows, schema=_YEARLY_SCHEMA)


def test_compute_sign_stability_stable_negative() -> None:
    """12 年全负、无翻转 → 稳定。"""
    frame = _yearly_frame({"f_stable": [-0.1] * 12})
    res = compute_sign_stability(frame, ("f_stable",), StabilityThresholds(horizon=60))
    row = res.to_dicts()[0]
    assert row["stable"] is True
    assert row["dominant"] == "neg"
    assert row["positive"] == 0 and row["negative"] == 12


def test_compute_sign_stability_drifting() -> None:
    """符号交替（+-+-）→ 不稳定。"""
    frame = _yearly_frame({"f_drift": [0.1, -0.1] * 6})
    res = compute_sign_stability(frame, ("f_drift",), StabilityThresholds(horizon=60))
    row = res.to_dicts()[0]
    assert row["stable"] is False
    assert row["flips"] >= 8


def test_compute_sign_stability_insufficient_years() -> None:
    """可用年份 < 3 → 标记 insufficient、不判稳定。"""
    frame = _yearly_frame({"f_few": [0.1, None, None]})
    res = compute_sign_stability(frame, ("f_few",), StabilityThresholds(horizon=60))
    row = res.to_dicts()[0]
    assert row["dominant"] == "insufficient"
    assert row["stable"] is False


def test_compare_with_previous_flags_new_drift() -> None:
    """新出现漂移（上次 stable、本次 false）→ new_stable_drift=True。"""
    new = pl.DataFrame(
        {
            "factor": ["f1", "f2"],
            "years": [12, 12],
            "positive": [6, 6],
            "negative": [6, 6],
            "flips": [8, 8],
            "dominant": ["neg", "neg"],
            "stable": [False, False],
        }
    )
    prev = pl.DataFrame(
        {
            "factor": ["f1", "f2"],
            "years": [12, 12],
            "positive": [12, 0],
            "negative": [0, 12],
            "flips": [0, 0],
            "dominant": ["pos", "neg"],
            "stable": [True, True],
        }
    )
    res = compare_with_previous(new, prev)
    d = {r["factor"]: r["new_stable_drift"] for r in res.to_dicts()}
    assert d == {"f1": True, "f2": True}


def test_compare_with_previous_no_previous() -> None:
    """无上次快照 → 全部 new_stable_drift=False（首次基线）。"""
    new = pl.DataFrame(
        {
            "factor": ["f1"],
            "years": [12],
            "positive": [0],
            "negative": [12],
            "flips": [0],
            "dominant": ["neg"],
            "stable": [True],
        }
    )
    res = compare_with_previous(new, None)
    assert res["new_stable_drift"].to_list() == [False]


def test_build_stability_review_writes_artifacts(tmp_path) -> None:
    """复审产出报告、CSV 与 JSON 快照。"""
    import json

    ic_dir = tmp_path / "ic"
    ic_dir.mkdir()
    yearly = _yearly_frame(
        {
            "overheat_index": [-0.1] * 12,
            "dim_flow": [0.1, -0.1] * 6,
        }
    )
    yearly.write_csv(ic_dir / "ic_yearly.csv")
    single = _yearly_frame(
        {
            "copper_gold_score": [-0.2] * 12,
            "main_ratio_score": [0.1, -0.1] * 6,
        }
    )
    single.write_csv(ic_dir / "ic_single_yearly.csv")

    out = tmp_path / "review"
    res = build_stability_review(
        ic_dir=ic_dir,
        output_dir=out,
        thresholds=StabilityThresholds(horizon=60),
    )
    assert set(res) == {"agg_stability", "single_stability"}
    assert res["agg_stability"].height == 2
    assert res["single_stability"].height == 2

    assert (out / "ic_stability_review.md").exists()
    assert (out / "agg_sign_stability.csv").exists()
    assert (out / "sign_stability_snapshot.json").exists()
    snapshot = json.loads((out / "sign_stability_snapshot.json").read_text(encoding="utf-8"))
    assert "generated_at" in snapshot
    assert "thresholds" in snapshot
    assert len(snapshot["agg"]) == 2


def test_build_stability_review_missing_inputs(tmp_path) -> None:
    """IC 产物缺失时复审不抛异常，报告标注缺输入。"""
    out = tmp_path / "review"
    res = build_stability_review(
        ic_dir=tmp_path / "missing",
        output_dir=out,
        thresholds=StabilityThresholds(horizon=60),
    )
    assert res["agg_stability"].is_empty()
    assert (out / "ic_stability_review.md").exists()


def test_load_snapshot_missing_returns_none(tmp_path) -> None:
    """快照文件缺失 → 返回 (None, None)。"""
    agg, single = load_snapshot(tmp_path / "nope.json")
    assert agg is None and single is None


def test_load_snapshot_roundtrip(tmp_path) -> None:
    """快照 JSON 可读回 (agg, single) 表。"""
    import json

    path = tmp_path / "snap.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-09-01T00:00:00+08:00",
                "agg": [{"factor": "overheat_index", "stable": True}],
                "single": [{"factor": "erp_score", "stable": False}],
            }
        ),
        encoding="utf-8",
    )
    agg, single = load_snapshot(path)
    assert agg is not None and agg["stable"].to_list() == [True]
    assert single is not None and single["stable"].to_list() == [False]


def test_report_new_drift_lists_factors() -> None:
    """新漂移汇总：返回此前稳定、本次不稳的因子清单。"""
    new = pl.DataFrame(
        {
            "factor": ["f1", "f2", "f3"],
            "years": [12, 12, 12],
            "positive": [6, 0, 12],
            "negative": [6, 12, 0],
            "flips": [8, 0, 0],
            "dominant": ["neg", "neg", "pos"],
            "stable": [False, True, True],
        }
    )
    prev = pl.DataFrame(
        {
            "factor": ["f1", "f2", "f3"],
            "years": [12, 12, 12],
            "positive": [12, 0, 12],
            "negative": [0, 12, 0],
            "flips": [0, 0, 0],
            "dominant": ["pos", "neg", "pos"],
            "stable": [True, True, True],
        }
    )
    drift = report_new_drift(agg=new, single=new, prev_agg=prev, prev_single=prev)
    # f1 从稳定变不稳 → 新漂移；f2/f3 保持稳定
    assert drift["agg"] == ["f1"]
    assert drift["single"] == ["f1"]
