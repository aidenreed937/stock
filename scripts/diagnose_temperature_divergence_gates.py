"""Phase 4 回归验证：快慢背离风控闸门的触发率与前向验证。

输入: 市场温度运行产物（runs/as_of=*/run_*/report.json，取每日最新 run）。
验证内容:
  1. 背离闸门触发率（61 天样本）：
     - 派发红旗: divergence >= 15 且 fast >= 60（scoring_risk._DIVERGENCE_HOT_FAST）
     - 冰点缓冲: divergence <= -15 且 fast <= 35（scoring_risk._DIVERGENCE_ICE_FAST）
  2. 前向验证（机制推断的证据化）：触发组 vs 非触发组的未来 1/3/5 交易日
     综合温度变化（均值、正收益占比）。
  3. 背离分布与极值日清单。

说明: 综合温度是"风险偏好温度"序列，不是价格收益；前向验证只检验温度惯性
方向，属于样本内机制证据，不构成收益预测。

输出: 控制台表格 + 可选 JSON（默认 data/analytics/diagnostics/temperature_divergence_gates.json）。
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
_DEFAULT_OUTPUT = _PROJECT_ROOT / "data/analytics/diagnostics/temperature_divergence_gates.json"

DIVERGENCE_EXTREME = 15.0
HOT_FAST = 60.0
ICE_FAST = 35.0
FORWARD_WINDOWS = (1, 3, 5)


def _latest_report(path: Path) -> dict:
    best: tuple[str, dict | None] = ("", None)
    for report in path.glob("run_*/report.json"):
        match = re.search(r"run_(\d{8}T\d{6})", str(report))
        run_id = match.group(1) if match else ""
        if run_id > best[0]:
            best = (run_id, json.loads(report.read_text(encoding="utf-8")))
    if best[1] is None:
        raise FileNotFoundError(f"目录 {path} 下没有 run_*/report.json")
    return best[1]


def _collect_rows(runs_root: Path) -> list[dict]:
    rows: list[dict] = []
    for as_of_dir in sorted(runs_root.glob("as_of=*")):
        report = _latest_report(as_of_dir)
        scores = report.get("scores", {})
        fast_slow = scores.get("fast_slow") if isinstance(scores.get("fast_slow"), dict) else {}
        composite = scores.get("composite", {})
        fast = fast_slow.get("fast_temperature")
        slow = fast_slow.get("slow_temperature")
        divergence = fast_slow.get("divergence")
        if fast is None or slow is None or divergence is None:
            continue
        rows.append(
            {
                "date": as_of_dir.name.split("=", 1)[1],
                "fast": float(fast),
                "slow": float(slow),
                "divergence": float(divergence),
                "composite": (
                    float(composite["temperature"])
                    if composite.get("temperature") is not None
                    else None
                ),
            }
        )
    return rows


def _forward_composite_changes(rows: list[dict]) -> dict[str, dict[int, float | None]]:
    result: dict[str, dict[int, float | None]] = {}
    for i, row in enumerate(rows):
        result[row["date"]] = {}
        for window in FORWARD_WINDOWS:
            target = i + window
            if target >= len(rows) or row["composite"] is None or rows[target]["composite"] is None:
                result[row["date"]][window] = None
            else:
                result[row["date"]][window] = rows[target]["composite"] - row["composite"]
    return result


def _group_stats(values: list[float]) -> dict:
    return {
        "count": len(values),
        "mean": round(statistics.mean(values), 2) if values else None,
        "positive_share": round(sum(1 for v in values if v > 0) / len(values), 3)
        if values
        else None,
        "min": round(min(values), 2) if values else None,
        "max": round(max(values), 2) if values else None,
    }


def build_report(rows: list[dict]) -> dict:
    forward = _forward_composite_changes(rows)
    for row in rows:
        if row["divergence"] >= DIVERGENCE_EXTREME and row["fast"] >= HOT_FAST:
            row["gate"] = "hot_distribution_risk"
        elif row["divergence"] <= -DIVERGENCE_EXTREME and row["fast"] <= ICE_FAST:
            row["gate"] = "ice_bottom_window"
        else:
            row["gate"] = "none"
        row["forward"] = forward[row["date"]]

    group_rows = {
        "hot_distribution_risk": [r for r in rows if r["gate"] == "hot_distribution_risk"],
        "ice_bottom_window": [r for r in rows if r["gate"] == "ice_bottom_window"],
        "none": [r for r in rows if r["gate"] == "none"],
    }
    forward_stats: dict[str, dict] = {}
    for name, group in group_rows.items():
        forward_stats[name] = {
            str(window): _group_stats(
                [r["forward"][window] for r in group if r["forward"][window] is not None]
            )
            for window in FORWARD_WINDOWS
        }
    extremes = sorted(rows, key=lambda r: abs(r["divergence"]), reverse=True)[:10]
    return {
        "sample_count": len(rows),
        "thresholds": {
            "divergence_extreme": DIVERGENCE_EXTREME,
            "hot_fast": HOT_FAST,
            "ice_fast": ICE_FAST,
        },
        "gate_counts": {name: len(group) for name, group in group_rows.items()},
        "divergence_series_stats": {
            "mean": round(statistics.mean(r["divergence"] for r in rows), 2),
            "std": round(statistics.pstdev(r["divergence"] for r in rows), 2),
            "min": round(min(r["divergence"] for r in rows), 2),
            "max": round(max(r["divergence"] for r in rows), 2),
        },
        "forward_composite_change": forward_stats,
        "ice_days": [
            {
                "date": r["date"],
                "fast": r["fast"],
                "slow": r["slow"],
                "divergence": r["divergence"],
                "composite": r["composite"],
                "fwd5_composite_change": r["forward"][5],
            }
            for r in group_rows["ice_bottom_window"]
        ],
        "divergence_extremes": [
            {
                "date": r["date"],
                "fast": r["fast"],
                "slow": r["slow"],
                "divergence": r["divergence"],
                "gate": r["gate"],
            }
            for r in extremes
        ],
    }


def print_report(report: dict) -> None:
    print(f"样本天数: {report['sample_count']}")
    print("\n闸门触发率（61 天样本）:")
    for name, count in report["gate_counts"].items():
        label = {
            "hot_distribution_risk": "派发红旗(背离>=15 且 快>=60)",
            "ice_bottom_window": "冰点缓冲(背离<=-15 且 快<=35)",
            "none": "未触发",
        }[name]
        print(f"  {label:<28} {count:>3} 天 ({count / report['sample_count']:.0%})")
    print(
        "\n背离序列: 均值 {mean} std {std} 区间 [{min}, {max}]".format(
            **report["divergence_series_stats"]
        )
    )
    print("\n前向综合温度变化（触发组 vs 未触发组）:")
    header = "  {:<22} " + " ".join(f"fwd{w:>9}" for w in FORWARD_WINDOWS)
    print(header.format("组"))
    for name in ("hot_distribution_risk", "ice_bottom_window", "none"):
        stats = report["forward_composite_change"][name]
        parts = []
        for w in FORWARD_WINDOWS:
            s = stats[str(w)]
            if s["mean"] is None:
                parts.append(f"{'n/a':>10}")
            else:
                parts.append(f"{s['mean']:+9.2f} ({s['positive_share']:.0%})")
        print(f"  {name:<22} " + " ".join(parts))
    print("\n冰点窗口日清单（含后 5 日综合温度变化）:")
    for item in report["ice_days"][:12]:
        fwd = item["fwd5_composite_change"]
        fwd_text = f"{fwd:+.2f}" if fwd is not None else "n/a"
        print(
            f"  {item['date']}  快={item['fast']:5.1f} 慢={item['slow']:5.1f} "
            f"背离={item['divergence']:+6.1f} 综合={item['composite']:5.1f} 后5日={fwd_text}"
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
    rows = _collect_rows(args.runs_root)
    if not rows:
        print("未收集到带 fast_slow 的运行产物", file=sys.stderr)
        return 1
    report = build_report(rows)
    print_report(report)

    if not args.no_write:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n诊断 JSON 已写入: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
