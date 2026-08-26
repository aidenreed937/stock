"""Phase 2 宏观流动性修复的影响回归诊断（修复前 vs 修复后，同数据隔离公式效应）。

修复内容: 宏观流动性维度由"全指标 flat 权重"（外盘环境 0.40 直接占比）改为
"国内子口径主导 + 外部子口径 25% 上限混合"（config subgroup_external_cap）。

方法: 对每个日期的*最新*运行产物, 用其自身的 metric_values 重建两种口径:
  - old_macro   = Σ(value * weight) / Σweight（全部 weight>0 指标, 修复前公式）
  - new_macro   = scores.dimensions[macro_liquidity].temperature（修复后产物值）
  - old_composite = new_composite - (new_macro - old_macro) * macro_dim_weight
同一次运行的 metric_values 相同, 因此差值纯粹来自公式切换, 不受底层数据增量影响。

输出: 控制台表格 + 可选 JSON（默认 data/analytics/diagnostics/temperature_phase2_impact.json）。
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_DEFAULT_RUNS_ROOT = _PROJECT_ROOT / "data/analytics/market_temperature/runs"
_DEFAULT_OUTPUT = _PROJECT_ROOT / "data/analytics/diagnostics/temperature_phase2_impact.json"

MACRO_DIMENSION_ID = "macro_liquidity"

# 快/慢分组（与 Phase 1/2 输出口径一致：按维度配置权重归一）
FAST_DIMENSIONS = {"fund_flow": 0.20, "sentiment": 0.15, "technical": 0.15}
SLOW_DIMENSIONS = {"valuation": 0.20, "fundamental": 0.15, "macro_liquidity": 0.15}

# quant_brief.yaml temperature_bands 上界（按顺序）
QUANT_BANDS = (20.0, 40.0, 60.0, 80.0)


def _latest_report(path: Path) -> dict:
    """选择 as_of 日期下运行序号（run_YYYYMMDDTHHMMSS...）最大的 report.json。"""
    best: tuple[str, dict | None] = ("", None)
    for report in path.glob("run_*/report.json"):
        match = re.search(r"run_(\d{8}T\d{6})", str(report))
        run_id = match.group(1) if match else ""
        if run_id > best[0]:
            best = (run_id, json.loads(report.read_text(encoding="utf-8")))
    if best[1] is None:
        raise FileNotFoundError(f"目录 {path} 下没有 run_*/report.json")
    return best[1]


def _macro_metric_weights() -> dict[str, tuple[float, str]]:
    """返回宏观流动性维度 weight>0 指标的 (weight, subgroup)。"""
    from stock_core.config.analytics_market_temperature import load_market_temperature_config

    config = load_market_temperature_config()
    for dimension in config.dimensions:
        if dimension.id != MACRO_DIMENSION_ID:
            continue
        return {
            metric.metric_id: (metric.weight, metric.subgroup)
            for metric in dimension.metrics
            if metric.enabled and metric.weight > 0
        }
    return {}


def _metric_values(report: dict) -> dict[str, float]:
    values: dict[str, float] = {}
    for metric in report.get("fact_summary", {}).get("metric_values", []):
        value = metric.get("value_float")
        if value is not None:
            values[str(metric.get("metric_id", ""))] = float(value)
    return values


def _weighted_avg(values: dict[str, float], weights: dict[str, float]) -> float | None:
    weighted_sum = 0.0
    weight_sum = 0.0
    for metric_id, weight in weights.items():
        value = values.get(metric_id)
        if value is None or weight <= 0:
            continue
        weighted_sum += value * weight
        weight_sum += weight
    if weight_sum == 0:
        return None
    return weighted_sum / weight_sum


def _dimension_temperature(scores: dict, dimension_id: str) -> float | None:
    for item in scores.get("dimensions", []):
        if item.get("dimension_id") == dimension_id:
            value = item.get("temperature")
            return float(value) if value is not None else None
    return None


def _group_temperature(temps: dict[str, float | None], weights: dict[str, float]) -> float | None:
    weighted_sum = 0.0
    weight_sum = 0.0
    for dimension_id, weight in weights.items():
        value = temps.get(dimension_id)
        if value is None or weight <= 0:
            continue
        weighted_sum += value * weight
        weight_sum += weight
    if weight_sum == 0:
        return None
    return weighted_sum / weight_sum


def _composite_temperature(
    temps: dict[str, float | None], weights: dict[str, float]
) -> float | None:
    weighted_sum = 0.0
    weight_sum = 0.0
    for dimension_id, weight in weights.items():
        value = temps.get(dimension_id)
        if value is None or weight <= 0:
            continue
        weighted_sum += value * weight
        weight_sum += weight
    if weight_sum == 0:
        return None
    return weighted_sum / weight_sum


DIMENSION_WEIGHTS = {
    "valuation": 0.20,
    "fund_flow": 0.20,
    "sentiment": 0.15,
    "technical": 0.15,
    "fundamental": 0.15,
    "macro_liquidity": 0.15,
}


def build_impact(runs_root: Path) -> dict:
    metric_weights = _macro_metric_weights()
    all_weights = {mid: w for mid, (w, _subgroup) in metric_weights.items()}
    rows: list[dict] = []
    for as_of_dir in sorted(runs_root.glob("as_of=*")):
        report = _latest_report(as_of_dir)
        scores = report.get("scores", {})
        new_composite = scores.get("composite", {}).get("temperature")
        new_macro = _dimension_temperature(scores, MACRO_DIMENSION_ID)
        if new_composite is None or new_macro is None:
            continue
        dim_temps = {d: _dimension_temperature(scores, d) for d in DIMENSION_WEIGHTS}
        if any(value is None for value in dim_temps.values()):
            continue
        values = _metric_values(report)
        old_macro = _weighted_avg(values, all_weights)
        if old_macro is None:
            continue
        old_composite = _composite_temperature(
            {**dim_temps, "macro_liquidity": old_macro}, DIMENSION_WEIGHTS
        )
        if old_composite is None:
            continue
        fast = _group_temperature(dim_temps, FAST_DIMENSIONS)
        slow_old = _group_temperature({**dim_temps, "macro_liquidity": old_macro}, SLOW_DIMENSIONS)
        slow_new = _group_temperature(dim_temps, SLOW_DIMENSIONS)
        rows.append(
            {
                "date": as_of_dir.name.split("=", 1)[1],
                "macro_old": round(old_macro, 2),
                "macro_new": round(new_macro, 2),
                "macro_delta": round(new_macro - old_macro, 2),
                "composite_old": round(old_composite, 2),
                "composite_new": round(new_composite, 2),
                "composite_delta": round(new_composite - old_composite, 2),
                "fast": round(fast, 2) if fast is not None else None,
                "slow_old": round(slow_old, 2) if slow_old is not None else None,
                "slow_new": round(slow_new, 2) if slow_new is not None else None,
                "divergence_old": round(fast - slow_old, 2)
                if fast is not None and slow_old is not None
                else None,
                "divergence_new": round(fast - slow_new, 2)
                if fast is not None and slow_new is not None
                else None,
            }
        )

    def _stats(key: str) -> dict:
        values = [row[key] for row in rows if row[key] is not None]
        return {
            "mean": round(statistics.mean(values), 2),
            "std": round(statistics.pstdev(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
        }

    def _band_index(value: float) -> int:
        index = 0
        for bound in QUANT_BANDS:
            if value >= bound:
                index += 1
        return index

    band_crossings = []
    for row in rows:
        old_band = _band_index(row["composite_old"])
        new_band = _band_index(row["composite_new"])
        if old_band != new_band:
            band_crossings.append(
                {
                    "date": row["date"],
                    "band_old": old_band,
                    "band_new": new_band,
                    "composite_old": row["composite_old"],
                    "composite_new": row["composite_new"],
                }
            )

    divergence_levels_old = _divergence_counts([row["divergence_old"] for row in rows])
    divergence_levels_new = _divergence_counts([row["divergence_new"] for row in rows])

    return {
        "sample_count": len(rows),
        "macro": {"old": _stats("macro_old"), "new": _stats("macro_new")},
        "composite": {"old": _stats("composite_old"), "new": _stats("composite_new")},
        "macro_delta": _stats("macro_delta"),
        "composite_delta": _stats("composite_delta"),
        "max_abs_composite_delta": round(
            max((abs(row["composite_delta"]) for row in rows), default=0.0), 2
        ),
        "quant_brief_band_crossings": band_crossings,
        "divergence_levels": {"old": divergence_levels_old, "new": divergence_levels_new},
        "top_macro_shifts": sorted(rows, key=lambda r: abs(r["macro_delta"]), reverse=True)[:8],
        "latest": rows[-1] if rows else None,
    }


def _divergence_counts(divergences: list[float | None]) -> dict[str, int]:
    counts = {"synchronized": 0, "divergent": 0, "extreme": 0}
    for value in divergences:
        if value is None:
            continue
        if abs(value) < 8:
            counts["synchronized"] += 1
        elif abs(value) < 15:
            counts["divergent"] += 1
        else:
            counts["extreme"] += 1
    return counts


def print_report(impact: dict) -> None:
    print(f"样本天数: {impact['sample_count']}")
    print("\n宏观流动性维度 (mean/std/min/max):")
    for side in ("old", "new"):
        s = impact["macro"][side]
        print(f"  {side:<6} {s['mean']:>7.1f} {s['std']:>6.1f} {s['min']:>7.1f} {s['max']:>7.1f}")
    print("\n综合温度 (mean/std/min/max):")
    for side in ("old", "new"):
        s = impact["composite"][side]
        print(f"  {side:<6} {s['mean']:>7.1f} {s['std']:>6.1f} {s['min']:>7.1f} {s['max']:>7.1f}")
    print(
        f"\n宏观维度 delta: 均值 {impact['macro_delta']['mean']:+.2f} "
        f"std {impact['macro_delta']['std']:.2f} "
        f"min {impact['macro_delta']['min']:+.2f} max {impact['macro_delta']['max']:+.2f}"
    )
    print(
        f"综合温度 delta: 均值 {impact['composite_delta']['mean']:+.2f} "
        f"std {impact['composite_delta']['std']:.2f} "
        f"max|delta| {impact['max_abs_composite_delta']:.2f}"
    )
    print("\n背离分布 (快慢同步/分歧观察/深度背离):")
    print(f"  old: {impact['divergence_levels']['old']}")
    print(f"  new: {impact['divergence_levels']['new']}")
    if impact["quant_brief_band_crossings"]:
        print(f"\nquant_brief 温度分档跨档 {len(impact['quant_brief_band_crossings'])} 天:")
        for item in impact["quant_brief_band_crossings"]:
            print(
                f"  {item['date']} band {item['band_old']}->{item['band_new']} "
                f"({item['composite_old']} -> {item['composite_new']})"
            )
    else:
        print("\nquant_brief 温度分档无跨档天数")
    print("\n宏观维度最大位移 top8:")
    for row in impact["top_macro_shifts"]:
        print(
            f"  {row['date']} 旧={row['macro_old']:>6.2f} 新={row['macro_new']:>6.2f} "
            f"差={row['macro_delta']:+.2f}"
        )
    latest = impact["latest"]
    if latest:
        print(
            f"\n最新: {latest['date']} 宏观 {latest['macro_old']}->{latest['macro_new']} "
            f"综合 {latest['composite_old']}->{latest['composite_new']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=_DEFAULT_RUNS_ROOT)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--no-write", action="store_true", help="只打印，不写 JSON")
    args = parser.parse_args()

    if not args.runs_root.exists():
        print(f"运行目录不存在: {args.runs_root}", file=sys.stderr)
        return 1

    impact = build_impact(args.runs_root)
    if impact["sample_count"] == 0:
        print("未收集到可用运行", file=sys.stderr)
        return 1
    print_report(impact)

    if not args.no_write:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(impact, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n诊断 JSON 已写入: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
