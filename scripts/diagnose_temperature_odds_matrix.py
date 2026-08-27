"""方案 A 回归验证：跨周期胜率/赔率矩阵的象限分布与前向验证。

输入: 市场温度历史索引（index/history.parquet）+ 61 天市场温度 run（scores.json/facts.parquet）
      + 61 天行业结构 run（report.json）。仅读取，不修改任何产物。
验证内容:
  1. S/O 档位与象限分布（61 天），检查是否锁死（任一档位占比 >= 70% 视为区分度不足）。
  2. 每个象限的前向 1/3/5 交易日综合温度变化（均值、正变化占比）。
  3. 轨迹事件统计：extreme->synchronized 收敛 / synchronized->extreme 恶化 的出现次数与前向表现。
  4. 输入缺失导致的 degraded 天数与缺失日期清单。

说明: 综合温度是"风险偏好温度"序列，不是价格收益；前向验证只检验温度惯性方向，
属于样本内机制证据，不构成收益预测。校准规则见跨周期矩阵设计文档第 7 节。

输出: 控制台表格 + 可选 JSON（默认 data/analytics/diagnostics/temperature_odds_matrix.json）。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import polars as pl

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from stock_reporting.interpretation.quant_brief.config import load_quant_brief_config  # noqa: E402
from stock_reporting.interpretation.quant_brief.cross_cycle import (  # noqa: E402
    evaluate_cross_cycle,
)
from stock_reporting.interpretation.quant_brief.extreme_state import (  # noqa: E402
    evaluate_extreme_state,
)

_DEFAULT_MARKET_ROOT = _PROJECT_ROOT / "data/analytics/market_temperature"
_DEFAULT_INDUSTRY_ROOT = _PROJECT_ROOT / "data/analytics/industry_structure"
_DEFAULT_OUTPUT = _PROJECT_ROOT / "data/analytics/diagnostics/temperature_odds_matrix.json"
FORWARD_WINDOWS = (1, 3, 5)
_QUADRATURE_LABELS = {
    "core": "O高S高 核心",
    "left": "O高S低 左侧",
    "band": "O低S高 波段",
    "avoid": "O低S低 回避",
    "standard": "标准",
}
_FACT_COLUMNS = ("category", "metric_id", "value_float", "metric_date")


def _latest_run_dir(as_of_dir: Path) -> Path | None:
    runs = sorted(as_of_dir.glob("run_*"), reverse=True)
    return runs[0] if runs else None


def _market_inputs(run_dir: Path) -> dict:
    scores = json.loads((run_dir / "scores.json").read_text(encoding="utf-8"))
    inputs = {
        "as_of_date": scores.get("as_of_date"),
        "composite": scores.get("composite"),
        "dimensions": scores.get("dimensions"),
        "fast_slow": scores.get("fast_slow"),
        "short_term": scores.get("short_term"),
        "external_risk": scores.get("external_risk"),
    }
    facts = pl.DataFrame()
    facts_path = run_dir / "facts.parquet"
    if facts_path.exists():
        try:
            facts = (
                pl.scan_parquet(facts_path)
                .select([col for col in _FACT_COLUMNS if col != "metric_date"])
                .collect()
            )
        except Exception:
            facts = pl.DataFrame()
    return inputs, facts


def _industry_inputs(run_dir: Path) -> dict:
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    scores = report.get("scores", {}) if isinstance(report.get("scores"), dict) else {}
    panel = pl.DataFrame()
    panel_path = run_dir / "industry_panel.parquet"
    if panel_path.exists():
        try:
            panel = pl.read_parquet(panel_path)
        except Exception:
            panel = pl.DataFrame()
    return {
        "trend_diagnostics": scores.get("trend_diagnostics"),
        "structure_health": scores.get("structure_health"),
        "panel": panel,
    }


def _load_history(market_root: Path) -> pl.DataFrame:
    path = market_root / "index" / "history.parquet"
    if not path.exists():
        return pl.DataFrame()
    return pl.read_parquet(path)


def _fwd_stats(
    rows: list[dict],
    *,
    composite_by_date: dict[str, float],
    window: int,
    key: str,
) -> dict:
    dates = sorted(composite_by_date)
    index = {day: i for i, day in enumerate(dates)}
    deltas: list[float] = []
    for row in rows:
        day = str(row["date"])
        if day not in index:
            continue
        target = index[day] + window
        if target >= len(dates):
            continue
        deltas.append(composite_by_date[dates[target]] - composite_by_date[day])
    if not deltas:
        return {"key": key, "window": window, "n": 0, "mean": None, "pos_ratio": None}
    return {
        "key": key,
        "window": window,
        "n": len(deltas),
        "mean": round(statistics.mean(deltas), 2),
        "pos_ratio": round(sum(1 for value in deltas if value > 0) / len(deltas), 3),
    }


def _print_stats(title: str, stats: list[dict]) -> None:
    print(f"\n{title}")
    print(f"{'分组':<14}{'窗口':>4}{'样本':>6}{'均值':>10}{'正占比':>10}")
    for item in stats:
        mean = "-" if item["mean"] is None else f"{item['mean']:+.2f}"
        pos = "-" if item["pos_ratio"] is None else f"{item['pos_ratio']:.0%}"
        print(f"{item['key']:<14}{item['window']:>4}{item['n']:>6}{mean:>10}{pos:>10}")


def run_diagnose(
    market_root: Path,
    industry_root: Path,
    *,
    start: str,
    end: str,
    output: Path,
) -> dict:
    config = load_quant_brief_config()
    history = _load_history(market_root)
    dates = sorted(
        day.name.split("=", 1)[1]
        for day in market_root.joinpath("runs").glob("as_of=*")
        if start <= day.name.split("=", 1)[1] <= end and _latest_run_dir(day) is not None
    )

    rows: list[dict] = []
    missing_dates: list[str] = []
    degraded_dates: list[str] = []
    for day in dates:
        market_run = _latest_run_dir(market_root.joinpath("runs", f"as_of={day}"))
        industry_run = _latest_run_dir(industry_root.joinpath("runs", f"as_of={day}"))
        if market_run is None or industry_run is None:
            missing_dates.append(day)
            continue
        market_scores, facts = _market_inputs(market_run)
        industry_scores = _industry_inputs(industry_run)
        result = evaluate_cross_cycle(
            config,
            market_scores,
            industry_scores,
            market_facts=facts,
            history=history,
        )
        extreme = evaluate_extreme_state(
            config,
            market_scores,
            industry_scores.get("panel"),
        )
        trajectory = result.get("trajectory") or {}
        composite = None
        if isinstance(market_scores.get("composite"), dict):
            composite = market_scores["composite"].get("temperature")
        rows.append(
            {
                "date": day,
                "win_score": result["win_score"],
                "win_level": result["win_level"],
                "odds_score": result["odds_score"],
                "odds_level": result["odds_level"],
                "quadrature": result["quadrature"],
                "adjustment_pp": result["position_adjustment_pp"],
                "transition": trajectory.get("divergence_transition", ""),
                "extreme_rank": extreme.get("composite_window_rank"),
                "extreme_windows": list(extreme.get("windows") or []),
                "extreme_bias_pp": extreme.get("position_bias_pp"),
                "composite": composite,
                "degraded": result["status"] == "degraded",
            }
        )
        if result["status"] == "degraded":
            degraded_dates.append(day)

    composite_by_date = {
        str(row["date"]): float(row["composite"])
        for row in rows
        if row.get("composite") is not None
    }

    def _group_stats(group_key: str) -> list[dict]:
        return [
            _fwd_stats(
                [row for row in rows if row[group_key] == key],
                composite_by_date=composite_by_date,
                window=window,
                key=key,
            )
            for key in sorted({row[group_key] for row in rows})
            for window in FORWARD_WINDOWS
        ]

    quadrature_counts = {
        key: sum(1 for row in rows if row["quadrature"] == key) for key in _QUADRATURE_LABELS
    }
    level_counts = {
        level: sum(1 for row in rows if row["win_level"] == level) for level in ("高", "中", "低")
    }
    odds_level_counts = {
        level: sum(1 for row in rows if row["odds_level"] == level) for level in ("高", "中", "低")
    }
    transitions = {}
    for row in rows:
        transition = row["transition"] or "-"
        transitions[transition] = transitions.get(transition, 0) + 1

    convergence_rows = [row for row in rows if "收敛确认" in row["transition"]]
    deterioration_rows = [row for row in rows if "恶化" in row["transition"]]

    print(
        f"跨周期胜率/赔率矩阵 61 天回归（{dates[0] if dates else '-'} .. {dates[-1] if dates else '-'}）"
    )
    print(f"有效天数: {len(rows)}；缺失: {len(missing_dates)} {missing_dates[:5]}")
    print(f"degraded 天数: {len(degraded_dates)} {degraded_dates[:5]}")

    print("\n象限分布（阈值参考：任一象限 >= 70% 视为区分度不足）")
    for key, label in _QUADRATURE_LABELS.items():
        count = quadrature_counts.get(key, 0)
        print(f"  {label:<10} {count:>3} 天 {count / len(rows):>8.0%}" if rows else f"  {label}: -")

    print(f"\nS 档位分布: {level_counts}；O 档位分布: {odds_level_counts}")

    _print_stats("各象限前向综合温度变化", _group_stats("quadrature"))
    for label, rows_subset in (
        ("收敛确认", convergence_rows),
        ("恶化", deterioration_rows),
    ):
        stats = [
            _fwd_stats(
                rows_subset,
                composite_by_date=composite_by_date,
                window=window,
                key=label,
            )
            for window in FORWARD_WINDOWS
        ]
        _print_stats(f"轨迹事件（{label}）", stats)

    extreme_ranks = {}
    for row in rows:
        rank = row.get("extreme_rank") or "missing"
        extreme_ranks[rank] = extreme_ranks.get(rank, 0) + 1
    print("\n极端状态窗口分布（61 天）")
    for rank, count in sorted(extreme_ranks.items()):
        print(f"  {rank:<14} {count:>3} 天")
    hot_rows = [row for row in rows if "hot_window" in (row.get("extreme_windows") or [])]
    frozen_rows = [row for row in rows if "frozen_window" in (row.get("extreme_windows") or [])]
    conflict_rows = [row for row in hot_rows if row.get("adjustment_pp", 0) > 0]
    print(f"\n冲突检查（hot 日不得出现仓位上调）: {len(conflict_rows)} / {len(hot_rows)} 天")
    _print_stats(
        "高温窗口前向综合温度变化",
        [
            _fwd_stats(
                hot_rows, composite_by_date=composite_by_date, window=window, key="hot_window"
            )
            for window in FORWARD_WINDOWS
        ],
    )
    _print_stats(
        "冰点窗口前向综合温度变化",
        [
            _fwd_stats(
                frozen_rows, composite_by_date=composite_by_date, window=window, key="frozen_window"
            )
            for window in FORWARD_WINDOWS
        ],
    )

    print("\n轨迹事件分布（61 天）")
    for transition, count in sorted(transitions.items()):
        print(f"  {transition:<48} {count:>3} 天")

    result_payload = {
        "sample_range": [dates[0], dates[-1]] if dates else [],
        "sample_size": len(rows),
        "missing_dates": missing_dates,
        "degraded_dates": degraded_dates,
        "quadrature_counts": quadrature_counts,
        "win_level_counts": level_counts,
        "odds_level_counts": odds_level_counts,
        "quadrature_fwd": _group_stats("quadrature"),
        "extreme_window_rank_counts": extreme_ranks,
        "extreme_hot_fwd": [
            _fwd_stats(hot_rows, composite_by_date=composite_by_date, window=window, key="hot")
            for window in FORWARD_WINDOWS
        ],
        "extreme_frozen_fwd": [
            _fwd_stats(
                frozen_rows, composite_by_date=composite_by_date, window=window, key="frozen"
            )
            for window in FORWARD_WINDOWS
        ],
        "extreme_conflict_days": [row["date"] for row in conflict_rows],
        "transition_counts": transitions,
        "convergence_fwd": [
            _fwd_stats(
                convergence_rows,
                composite_by_date=composite_by_date,
                window=window,
                key="convergence",
            )
            for window in FORWARD_WINDOWS
        ],
        "deterioration_fwd": [
            _fwd_stats(
                deterioration_rows,
                composite_by_date=composite_by_date,
                window=window,
                key="deterioration",
            )
            for window in FORWARD_WINDOWS
        ],
        "daily_rows": rows,
        "rules_version": config.cross_cycle.rules_version,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result_payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nJSON 已写入: {output}")
    return result_payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="跨周期胜率/赔率矩阵 61 天回归验证")
    parser.add_argument("--market-root", type=Path, default=_DEFAULT_MARKET_ROOT)
    parser.add_argument("--industry-root", type=Path, default=_DEFAULT_INDUSTRY_ROOT)
    parser.add_argument("--start", default="2026-06-01")
    parser.add_argument("--end", default="2026-08-25")
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_diagnose(
        args.market_root,
        args.industry_root,
        start=args.start,
        end=args.end,
        output=args.output,
    )
