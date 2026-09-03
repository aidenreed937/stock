"""宏观风控因子 IC 稳定性复审（定期复核机制）。

用途：定期（建议季度）复核双轨指数/维度分/单因子对前瞻收益的 IC 方向是否
**跨周期稳定**，输出复审报告与 JSON 快照，并与上次快照对比，标记新出现的
"年度符号漂移"因子——漂移是降级/复核的候选信号（如 us_yield_curve 先例）。

口径：
- 输入为 ``build_ic_report`` 产出的 ``ic_yearly.csv``（12 信号）与
  ``ic_single_yearly.csv``（23 单因子）；
- 稳定性以**年度 IC 符号**为准（pooled IC 符号翻转 ≠ 漂移，见
  factor_selection_methodology.md §5.5——需区分"尺度效应"与"跨周期漂移"）；
- 漂移判定：稳定年份内主导符号占比 < ``stable_ratio`` 且符号翻转次数 > ``max_flips``；
  任一年度缺失（None）不算翻转，但计入可用年份。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

_DEFAULT_IC_DIR = Path("data/analytics/macro_strategy/ic")
_DEFAULT_REVIEW_DIR = Path("data/analytics/macro_strategy/ic/review")
_DEFAULT_HORIZON = 60
_DEFAULT_STABLE_RATIO = 0.7  # 主导符号占比 >= 70% 视为稳定
_DEFAULT_MAX_FLIPS = 2  # 符号翻转次数 <= 2 视为稳定（12 年中方向占比 70% 且偶发翻转仍算稳定）


@dataclass(frozen=True)
class StabilityThresholds:
    """符号稳定性判定阈值（参数化，可在 CLI 覆盖）。"""

    horizon: int = _DEFAULT_HORIZON
    stable_ratio: float = _DEFAULT_STABLE_RATIO
    max_flips: int = _DEFAULT_MAX_FLIPS


def _signs_for_factor(
    yearly: pl.DataFrame, factor: str, horizon: int
) -> tuple[list[int], list[int]]:
    """返回某因子指定窗口的 (可用年份列表, 符号列表 1/-1)。"""
    sub = yearly.filter((pl.col("factor") == factor) & (pl.col("horizon") == horizon)).sort("year")
    years: list[int] = []
    signs: list[int] = []
    for row in sub.to_dicts():
        v = row["ic"]
        if v is None:
            continue
        years.append(int(row["year"]))
        signs.append(1 if float(v) > 0 else -1)
    return years, signs


def compute_sign_stability(
    yearly: pl.DataFrame,
    factors: tuple[str, ...],
    thresholds: StabilityThresholds,
) -> pl.DataFrame:
    """计算各因子年度 IC 符号稳定性。

    Returns:
        ``{factor, years, positive, negative, flips, dominant, stable}``：
        ``stable`` 为 True 表示主导符号占比达标且翻转次数未超限。
    """
    rows: list[dict[str, Any]] = []
    for factor in factors:
        years, signs = _signs_for_factor(yearly, factor, thresholds.horizon)
        if len(years) < 3:
            rows.append(
                {
                    "factor": factor,
                    "years": len(years),
                    "positive": sum(1 for s in signs if s > 0),
                    "negative": sum(1 for s in signs if s < 0),
                    "flips": 0,
                    "dominant": "insufficient",
                    "stable": False,
                }
            )
            continue
        pos = sum(1 for s in signs if s > 0)
        neg = len(signs) - pos
        dominant = "pos" if pos > neg else "neg"
        dominant_share = max(pos, neg) / len(signs)
        flips = sum(1 for i in range(1, len(signs)) if signs[i] != signs[i - 1])
        stable = dominant_share >= thresholds.stable_ratio and flips <= thresholds.max_flips
        rows.append(
            {
                "factor": factor,
                "years": len(years),
                "positive": pos,
                "negative": neg,
                "flips": flips,
                "dominant": dominant,
                "stable": stable,
            }
        )
    return pl.DataFrame(rows)


def _read_yearly(ic_dir: Path, filename: str) -> pl.DataFrame:
    path = ic_dir / filename
    if not path.exists():
        return pl.DataFrame()
    return pl.read_csv(path)


def build_stability_review(
    *,
    ic_dir: Path | str = _DEFAULT_IC_DIR,
    output_dir: Path | str = _DEFAULT_REVIEW_DIR,
    factors_12: tuple[str, ...] | None = None,
    factors_23: tuple[str, ...] | None = None,
    thresholds: StabilityThresholds | None = None,
) -> dict[str, pl.DataFrame]:
    """运行 IC 稳定性复审，输出报告 + JSON 快照到 ``output_dir``。

    Returns:
        ``{agg_stability, single_stability}`` 两张稳定性表（已落盘）。
    """
    ic_dir = Path(ic_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    thresholds = thresholds or StabilityThresholds()

    # 12 聚合信号（双轨 + 维度）
    yearly_12 = _read_yearly(ic_dir, "ic_yearly.csv")
    if factors_12 is None:
        factors_12 = (
            tuple(yearly_12.select("factor").unique().sort("factor")["factor"].to_list())
            if not yearly_12.is_empty()
            else ()
        )
    agg_stability = compute_sign_stability(yearly_12, factors_12, thresholds)

    # 23 单因子
    yearly_23 = _read_yearly(ic_dir, "ic_single_yearly.csv")
    if factors_23 is None:
        factors_23 = (
            tuple(yearly_23.select("factor").unique().sort("factor")["factor"].to_list())
            if not yearly_23.is_empty()
            else ()
        )
    single_stability = compute_sign_stability(yearly_23, factors_23, thresholds)

    agg_stability.write_csv(out / "agg_sign_stability.csv")
    single_stability.write_csv(out / "single_sign_stability.csv")

    _write_snapshot(out, agg_stability, single_stability, thresholds)
    _render_review_markdown(out, agg_stability, single_stability, thresholds, yearly_12, yearly_23)
    return {"agg_stability": agg_stability, "single_stability": single_stability}


def _write_snapshot(
    out: Path,
    agg: pl.DataFrame,
    single: pl.DataFrame,
    thresholds: StabilityThresholds,
) -> None:
    import json
    from datetime import datetime

    snapshot = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "thresholds": {
            "horizon": thresholds.horizon,
            "stable_ratio": thresholds.stable_ratio,
            "max_flips": thresholds.max_flips,
        },
        "agg": agg.to_dicts(),
        "single": single.to_dicts(),
    }
    (out / "sign_stability_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def compare_with_previous(
    new: pl.DataFrame,
    previous: pl.DataFrame | None,
) -> pl.DataFrame:
    """与上次快照对比，标记新出现的不稳定因子（此前 stable 现为 false）。"""
    if previous is None or previous.is_empty():
        return new.with_columns(new_stable_drift=pl.lit(False))
    prev_map = {row["factor"]: bool(row["stable"]) for row in previous.to_dicts()}
    return new.with_columns(
        pl.struct(["factor", "stable"])
        .map_elements(
            lambda r: prev_map.get(r["factor"], True) and not r["stable"],
            return_dtype=pl.Boolean,
        )
        .alias("new_stable_drift")
    )


def load_snapshot(
    snapshot_path: Path | str,
) -> tuple[pl.DataFrame | None, pl.DataFrame | None]:
    """读取上次复审 JSON 快照，返回 (agg, single) 稳定性表；无快照返回 (None, None)。"""
    path = Path(snapshot_path)
    if not path.exists():
        return None, None
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    agg = pl.DataFrame(data.get("agg", []))
    single = pl.DataFrame(data.get("single", []))
    return (
        agg if not agg.is_empty() else None,
        single if not single.is_empty() else None,
    )


def report_new_drift(
    agg: pl.DataFrame,
    single: pl.DataFrame,
    prev_agg: pl.DataFrame | None,
    prev_single: pl.DataFrame | None,
) -> dict[str, list[str]]:
    """与上次快照对比，返回本次**新出现漂移**的因子清单（此前稳定、本次不稳）。"""
    agg_drift = compare_with_previous(agg, prev_agg).filter(pl.col("new_stable_drift"))
    single_drift = compare_with_previous(single, prev_single).filter(pl.col("new_stable_drift"))
    return {
        "agg": agg_drift["factor"].to_list(),
        "single": single_drift["factor"].to_list(),
    }


def _render_review_markdown(
    out: Path,
    agg: pl.DataFrame,
    single: pl.DataFrame,
    thresholds: StabilityThresholds,
    yearly_12: pl.DataFrame,
    yearly_23: pl.DataFrame,
) -> None:
    """渲染复审报告 Markdown。"""
    lines = [
        "# 宏观风控因子 IC 稳定性复审",
        "",
        f"> 窗口：{thresholds.horizon}D 年度符号；稳定判定：主导符号占比 ≥ {thresholds.stable_ratio:.0%}"
        f" 且翻转 ≤ {thresholds.max_flips} 次。",
        "",
    ]
    if yearly_12.is_empty():
        lines.append("（缺少 ic_yearly.csv，请先运行 build_ic_report）")
    else:
        lines.append(f"## 一、12 聚合信号（双轨指数 + 维度分）稳定性（{thresholds.horizon}D）")
        lines.append("")
        lines.append("| 因子 | 可用年数 | 正/负年数 | 翻转次数 | 主导方向 | 稳定 |")
        lines.append("| :-- | :--: | :--: | :--: | :--: | :--: |")
        for r in agg.to_dicts():
            lines.append(
                f"| {r['factor']} | {r['years']} | {r['positive']}/{r['negative']} | "
                f"{r['flips']} | {r['dominant']} | {'✅' if r['stable'] else '⚠️'} |"
            )
        lines.append("")
    if yearly_23.is_empty():
        lines.append("（缺少 ic_single_yearly.csv，单因子复审跳过）")
    else:
        lines.append(f"## 二、23 单因子稳定性（{thresholds.horizon}D）")
        lines.append("")
        lines.append("| 因子 | 可用年数 | 正/负年数 | 翻转次数 | 主导方向 | 稳定 |")
        lines.append("| :-- | :--: | :--: | :--: | :--: | :--: |")
        for r in single.to_dicts():
            lines.append(
                f"| {r['factor']} | {r['years']} | {r['positive']}/{r['negative']} | "
                f"{r['flips']} | {r['dominant']} | {'✅' if r['stable'] else '⚠️'} |"
            )
        lines.append("")
    lines.append("## 三、说明")
    lines.append("")
    lines.append(
        "- 符号稳定性以年度 IC 为准；pooled IC 符号翻转不等于漂移（尺度效应 vs 跨周期漂移）。"
    )
    lines.append(
        "- ⚠️ 因子为「漂移/复核候选」：主导符号占比不达标或翻转超限，建议对照"
        " `docs/research/macro/factor_selection_methodology.md` §5 评估是否降级。"
    )
    lines.append("- 与上次快照对比结果见 `sign_stability_snapshot.json`（含生成时间，可 diff）。")
    (out / "ic_stability_review.md").write_text("\n".join(lines), encoding="utf-8")


__all__ = [
    "StabilityThresholds",
    "build_stability_review",
    "compare_with_previous",
    "compute_sign_stability",
    "load_snapshot",
    "report_new_drift",
]
