"""市场温度综合/快慢合成诊断基线（Phase 0）。

对历史 market_temperature 运行产物（runs/as_of=*/run_*/report.json）计算：
1. 每日快温度（资金/情绪/技术）、慢温度（估值/基本面/宏观流动性）、综合温度、背离；
2. 各序列统计（均值/std/min/max/range）；
3. 综合温度与快/慢温度的相关系数、快-慢背离极值；
4. 宏观流动性维度内"外盘环境温度"的贡献占比（名义错位核查）。

只读已落盘产物，不重跑管线；每次运行选择 as_of 日期下最新 run。
输出：控制台表格 + 可选 JSON 文件（默认 data/analytics/diagnostics/）。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 确保从任意工作目录运行时，stock_core 等包可导入（脚本通常在项目根下运行）
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_DEFAULT_RUNS_ROOT = _PROJECT_ROOT / "data/analytics/market_temperature/runs"
_DEFAULT_OUTPUT = _PROJECT_ROOT / "data/analytics/diagnostics/temperature_composite_baseline.json"

# 快/慢分组（与修复计划 Phase 1 的输出口径一致：按维度配置权重归一）
FAST_DIMENSIONS = {"fund_flow": 0.20, "sentiment": 0.15, "technical": 0.15}
SLOW_DIMENSIONS = {"valuation": 0.20, "fundamental": 0.15, "macro_liquidity": 0.15}

# 宏观流动性维度名义错位核查目标指标
MACRO_EXTERNAL_ENVIRONMENT_METRIC = "macro_external_environment_temperature"
MACRO_DIMENSION_ID = "macro_liquidity"


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


def _dimension_temperature(scores: dict, dimension_id: str) -> float | None:
    for item in scores.get("dimensions", []):
        if item.get("dimension_id") == dimension_id:
            value = item.get("temperature")
            return float(value) if value is not None else None
    return None


def _short_term_temperature(scores: dict, window: int) -> float | None:
    for item in scores.get("short_term", []):
        if item.get("window") == window:
            value = item.get("temperature")
            return float(value) if value is not None else None
    return None


def _macro_external_share(report: dict, macro_weights: dict[str, float]) -> float | None:
    """外盘环境温度在宏观流动性维度内的加权贡献占比（%）。

    权重来自当前 config/analytics/market_temperature.yaml（与管线同源），
    数值来自运行产物 metric_values；贡献占比 = 外盘加权值 / 维度加权和。
    """
    values: dict[str, float] = {}
    for metric in report.get("fact_summary", {}).get("metric_values", []):
        value = metric.get("value_float")
        if value is not None:
            values[str(metric.get("metric_id", ""))] = float(value)
    weighted_sum = 0.0
    for metric_id, weight in macro_weights.items():
        value = values.get(metric_id)
        if value is None or weight <= 0:
            continue
        weighted_sum += value * weight
    external_value = values.get(MACRO_EXTERNAL_ENVIRONMENT_METRIC)
    external_weight = macro_weights.get(MACRO_EXTERNAL_ENVIRONMENT_METRIC, 0.0)
    if weighted_sum <= 0 or external_value is None or external_weight <= 0:
        return None
    return (external_value * external_weight) / weighted_sum * 100.0


def collect_macro_weights() -> dict[str, float]:
    """从当前配置读取宏观流动性维度 enabled 且 weight>0 的指标权重。"""
    try:
        from stock_core.config.analytics_market_temperature import load_market_temperature_config
    except ImportError:
        return {}
    config = load_market_temperature_config()
    for dimension in config.dimensions:
        if dimension.id != MACRO_DIMENSION_ID:
            continue
        return {
            metric.metric_id: metric.weight
            for metric in dimension.metrics
            if metric.enabled and metric.weight > 0
        }
    return {}


def _weighted_group_temperature(
    temps: dict[str, float | None], weights: dict[str, float]
) -> float | None:
    """按维度配置权重归一化合成组温度（快组/慢组）。"""
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


def collect_runs(
    runs_root: Path, macro_weights: dict[str, float]
) -> list[dict]:
    rows = []
    for as_of_dir in sorted(runs_root.glob("as_of=*")):
        date_str = as_of_dir.name.split("=", 1)[1]
        report = _latest_report(as_of_dir)
        scores = report.get("scores", {})
        composite = scores.get("composite", {}).get("temperature")
        if composite is None:
            continue
        all_dimensions = tuple(FAST_DIMENSIONS) + tuple(SLOW_DIMENSIONS)
        temps = {d: _dimension_temperature(scores, d) for d in all_dimensions}
        if any(value is None for value in temps.values()):
            continue
        fast = _weighted_group_temperature(temps, FAST_DIMENSIONS)
        slow = _weighted_group_temperature(temps, SLOW_DIMENSIONS)
        if fast is None or slow is None:
            continue
        rows.append(
            {
                "date": date_str,
                "composite": float(composite),
                "fast": fast,
                "slow": slow,
                "divergence": fast - slow,
                "st5": _short_term_temperature(scores, 5),
                "st10": _short_term_temperature(scores, 10),
                "macro_external_share": _macro_external_share(report, macro_weights),
            }
        )
    return rows


def _correlation(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 2:
        return float("nan")
    a, b = a[:n], b[:n]
    ma, mb = statistics.mean(a), statistics.mean(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / n
    denom = statistics.pstdev(a) * statistics.pstdev(b)
    return cov / denom if denom else float("nan")


def _stats(values: list[float]) -> dict:
    return {
        "mean": round(statistics.mean(values), 2),
        "std": round(statistics.pstdev(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "range": round(max(values) - min(values), 2),
    }


def build_diagnosis(rows: list[dict]) -> dict:
    composite = [r["composite"] for r in rows]
    fast = [r["fast"] for r in rows]
    slow = [r["slow"] for r in rows]
    st5 = [r["st5"] for r in rows if r["st5"] is not None]
    st10 = [r["st10"] for r in rows if r["st10"] is not None]
    external_shares = [r["macro_external_share"] for r in rows if r["macro_external_share"] is not None]
    divergences = sorted(rows, key=lambda r: abs(r["divergence"]), reverse=True)
    return {
        "sample_count": len(rows),
        "series_stats": {k: _stats(v) for k, v in {
            "composite": composite,
            "fast": fast,
            "slow": slow,
            "st5": st5,
            "st10": st10,
        }.items()},
        "correlations": {
            "composite_vs_fast": round(_correlation(composite, fast), 3),
            "composite_vs_slow": round(_correlation(composite, slow), 3),
            "fast_vs_slow": round(_correlation(fast, slow), 3),
            "st5_vs_fast": round(_correlation(st5, fast), 3),
            "st10_vs_slow": round(_correlation(st10, slow), 3),
        },
        "macro_external_share": (
            _stats(external_shares) if external_shares else None
        ),
        "divergence_tops": [
            {"date": r["date"], "fast": round(r["fast"], 1), "slow": round(r["slow"], 1),
             "divergence": round(r["divergence"], 1)}
            for r in divergences[:8]
        ]
        if math.isfinite(divergences[0]["divergence"]) else [],
        "latest": {
            "date": rows[-1]["date"],
            "composite": round(rows[-1]["composite"], 1),
            "fast": round(rows[-1]["fast"], 1),
            "slow": round(rows[-1]["slow"], 1),
            "divergence": round(rows[-1]["divergence"], 1),
        },
    }


def print_report(diag: dict) -> None:
    print(f"样本天数: {diag['sample_count']}")
    print("\n序列统计 (mean/std/min/max/range):")
    for name, s in diag["series_stats"].items():
        print(f"  {name:<12} {s['mean']:>7.1f} {s['std']:>6.1f} {s['min']:>7.1f} {s['max']:>7.1f} {s['range']:>7.1f}")
    print("\n相关性:")
    for name, value in diag["correlations"].items():
        print(f"  {name:<20} {value:+.3f}")
    share = diag.get("macro_external_share")
    if share:
        print(
            f"\n宏观流动性-外盘环境贡献占比: 均值 {share['mean']}% "
            f"(min {share['min']}% / max {share['max']}%)"
        )
    print("\n背离极值 (|fast-slow| top8):")
    for item in diag["divergence_tops"]:
        print(f"  {item['date']}  fast={item['fast']:>5.1f} slow={item['slow']:>5.1f} 差={item['divergence']:+.1f}")
    latest = diag["latest"]
    print(f"\n最新(修复基线): {latest['date']} 综合={latest['composite']} 快={latest['fast']} 慢={latest['slow']} 差={latest['divergence']:+.1f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=_DEFAULT_RUNS_ROOT)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument("--no-write", action="store_true", help="只打印，不写 JSON")
    args = parser.parse_args()

    if not args.runs_root.exists():
        print(f"运行目录不存在: {args.runs_root}", file=sys.stderr)
        return 1

    rows = collect_runs(args.runs_root, collect_macro_weights())
    if not rows:
        print("未收集到可用运行（全部缺少综合温度或六维）", file=sys.stderr)
        return 1

    diag = build_diagnosis(rows)
    print_report(diag)

    if not args.no_write:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n诊断 JSON 已写入: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
