"""从已落盘市场温度/行业结构/投资者简报产物生成跨周期复盘。"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import polars as pl

try:
    from scripts.report_consistency import ConsistencyValidator
except ModuleNotFoundError:  # pragma: no cover - 支持直接按文件路径执行
    from report_consistency import ConsistencyValidator


DIMENSION_KEYS: tuple[str, ...] = (
    "valuation",
    "fund_flow",
    "sentiment",
    "technical",
    "fundamental",
    "macro_liquidity",
)
FACT_KEYS: tuple[str, ...] = (
    "main_money_net_inflow_share",
    "margin_balance_growth_20d",
    "market_amount_percentile_1250d",
    "turnover_rate_percentile_1250d",
    "advance_share",
    "above_ma20_share",
    "above_ma60_share",
    "return_20d",
)
EXTREME_KEYS: tuple[str, ...] = (
    "composite",
    "fund_flow",
    "sentiment",
    "technical",
    "valuation",
    "positive_return_20d_count",
    "positive_return_60d_count",
    "market_amount_percentile_1250d",
    "turnover_rate_percentile_1250d",
    "margin_balance_growth_20d",
    "above_ma20_share",
    "above_ma60_share",
)


@dataclass(frozen=True, slots=True)
class ArtifactDirs:
    market: Path
    industry: Path
    brief: Path


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    analytics_root = Path(args.analytics_root)
    output_root = Path(args.output_root)
    dates = _resolve_dates(args, analytics_root)
    if not dates:
        print("没有找到可复盘的日期")
        return 1

    if not args.skip_consistency:
        consistency = ConsistencyValidator(analytics_root).validate_dates(dates)
        if consistency.status != "passed":
            print("report_consistency 未通过，停止生成跨周期复盘")
            for issue in consistency.errors[:20]:
                print(f"[ERROR] {issue.as_of_date} {issue.artifact}: {issue.message}")
            return 1

    market_rows, panel_rows = _load_rows(analytics_root, dates)
    payload = _build_payload(dates, market_rows, panel_rows)
    markdown = _render_markdown(payload)
    paths = _write_artifacts(output_root, payload, markdown, update_latest=not args.no_latest)
    print(f"market_cycle_review: passed dates={len(dates)}")
    print(f"json: {paths['json']}")
    print(f"markdown: {paths['markdown']}")
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成市场跨周期复盘产物")
    parser.add_argument("--start", required=True, help="起始基准日 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="结束基准日 YYYY-MM-DD")
    parser.add_argument("--analytics-root", default="data/analytics", help="分析产物根目录")
    parser.add_argument(
        "--output-root",
        default="data/analytics/market_cycle_review",
        help="跨周期复盘产物根目录",
    )
    parser.add_argument("--skip-consistency", action="store_true", help="跳过一致性校验")
    parser.add_argument("--no-latest", action="store_true", help="不刷新 latest")
    return parser.parse_args(argv)


def _resolve_dates(args: argparse.Namespace, analytics_root: Path) -> list[str]:
    dates = ConsistencyValidator(analytics_root).available_dates(args.start, args.end)
    return [value for value in dates if args.start <= value <= args.end]


def _load_rows(
    analytics_root: Path,
    dates: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    market_rows: list[dict[str, Any]] = []
    panel_rows: list[dict[str, Any]] = []
    for as_of_date in dates:
        dirs = _artifact_dirs(analytics_root, as_of_date)
        market_rows.append(_load_market_row(dirs, as_of_date))
        panel_rows.extend(_load_panel_rows(dirs, as_of_date))
    return market_rows, panel_rows


def _artifact_dirs(root: Path, as_of_date: str) -> ArtifactDirs:
    return ArtifactDirs(
        market=_latest_run_dir(root / "market_temperature", as_of_date),
        industry=_latest_run_dir(root / "industry_structure", as_of_date),
        brief=_latest_run_dir(root / "investor_brief", as_of_date),
    )


def _latest_run_dir(root: Path, as_of_date: str) -> Path:
    run_root = root / "runs" / f"as_of={as_of_date}"
    run_dirs = sorted(path for path in run_root.glob("run_*") if path.is_dir())
    if not run_dirs:
        raise FileNotFoundError(f"未找到产物目录: {run_root}")
    return run_dirs[-1]


def _load_market_row(dirs: ArtifactDirs, as_of_date: str) -> dict[str, Any]:
    scores = _read_json(dirs.market / "scores.json")
    industry_scores = _read_json(dirs.industry / "scores.json")
    brief = _read_json(dirs.brief / "brief_report.json")
    facts = pl.read_parquet(dirs.market / "facts.parquet")
    fact_values = {
        row["metric_id"]: row.get("value_float")
        for row in facts.to_dicts()
        if row.get("metric_id")
    }
    dimensions = {
        row["dimension_id"]: row.get("temperature")
        for row in scores.get("dimensions", [])
        if row.get("dimension_id")
    }
    health = industry_scores.get("structure_health", {})
    row: dict[str, Any] = {
        "date": as_of_date,
        "composite": scores.get("composite", {}).get("temperature"),
        "risk_level": scores.get("systemic_risk", {}).get("level"),
        "structure_health": health.get("level"),
        "positive_return_20d_count": health.get("positive_return_20d_count"),
        "positive_return_60d_count": health.get("positive_return_60d_count"),
        "crowded_industry_count": health.get("crowded_industry_count"),
        "strong_trend_count": health.get("strong_trend_count"),
        "candidate_industries": _names(brief.get("candidate_industries", [])),
        "risk_industries": _names(brief.get("risk_industries", [])),
        "lagging_industries": _names(brief.get("lagging_industries", [])),
    }
    row.update({key: dimensions.get(key) for key in DIMENSION_KEYS})
    row.update({key: fact_values.get(key) for key in FACT_KEYS})
    return row


def _load_panel_rows(dirs: ArtifactDirs, as_of_date: str) -> list[dict[str, Any]]:
    panel = pl.read_parquet(dirs.industry / "industry_panel.parquet")
    if "structure_rank" not in panel.columns:
        panel = panel.sort("structure_score", descending=True).with_row_index(
            "structure_rank",
            offset=1,
        )
    keys = (
        "industry_name",
        "structure_rank",
        "structure_score",
        "return_20d",
        "return_60d",
        "tcr",
        "crowding_temperature",
        "tags",
    )
    return [{"date": as_of_date, **{key: row.get(key) for key in keys}} for row in panel.to_dicts()]


def _build_payload(
    dates: list[str],
    market_rows: list[dict[str, Any]],
    panel_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start_date": dates[0],
        "end_date": dates[-1],
        "date_count": len(dates),
        "market_summary": _market_summary(market_rows),
        "phase_summary": _phase_summary(market_rows),
        "signal_days": _signal_days(market_rows),
        "industry_frequency": _industry_frequency(market_rows, panel_rows, dates),
        "daily_rows": market_rows,
    }


def _market_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ("composite", *DIMENSION_KEYS, "positive_return_20d_count", "positive_return_60d_count")
    summary = {key: _series_summary(rows, key) for key in keys}
    return {
        "series": summary,
        "risk_level_counts": dict(Counter(row["risk_level"] for row in rows)),
        "structure_health_counts": dict(Counter(row["structure_health"] for row in rows)),
    }


def _series_summary(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [(row["date"], _to_float(row.get(key))) for row in rows]
    finite = [(day, value) for day, value in values if math.isfinite(value)]
    if not finite:
        return {"status": "missing"}
    min_item = min(finite, key=lambda item: item[1])
    max_item = max(finite, key=lambda item: item[1])
    return {
        "start": round(finite[0][1], 4),
        "end": round(finite[-1][1], 4),
        "min": {"date": min_item[0], "value": round(min_item[1], 4)},
        "max": {"date": max_item[0], "value": round(max_item[1], 4)},
        "mean": round(sum(value for _, value in finite) / len(finite), 4),
    }


def _phase_summary(rows: list[dict[str, Any]], size: int = 10) -> list[dict[str, Any]]:
    phases: list[dict[str, Any]] = []
    for index in range(0, len(rows), size):
        chunk = rows[index : index + size]
        phases.append(
            {
                "start_date": chunk[0]["date"],
                "end_date": chunk[-1]["date"],
                "date_count": len(chunk),
                "composite": _mean(chunk, "composite"),
                "fund_flow": _mean(chunk, "fund_flow"),
                "technical": _mean(chunk, "technical"),
                "sentiment": _mean(chunk, "sentiment"),
                "positive_return_20d_count": _mean(chunk, "positive_return_20d_count"),
                "positive_return_60d_count": _mean(chunk, "positive_return_60d_count"),
            }
        )
    return phases


def _signal_days(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reasons: dict[str, list[str]] = defaultdict(list)
    _add_state_changes(rows, reasons)
    _add_extremes(rows, reasons)
    _add_threshold_crossings(rows, reasons)
    _add_daily_delta_extremes(rows, reasons)
    return [_signal_payload(row, reasons[row["date"]]) for row in rows if reasons.get(row["date"])]


def _add_state_changes(rows: list[dict[str, Any]], reasons: dict[str, list[str]]) -> None:
    previous: dict[str, Any] | None = None
    for row in rows:
        if previous is None:
            reasons[row["date"]].append("区间起点")
        elif row["risk_level"] != previous["risk_level"]:
            reasons[row["date"]].append(f"系统风险切换为 {row['risk_level']}")
        elif row["structure_health"] != previous["structure_health"]:
            reasons[row["date"]].append(f"结构健康度切换为 {row['structure_health']}")
        previous = row


def _add_extremes(rows: list[dict[str, Any]], reasons: dict[str, list[str]]) -> None:
    for key in EXTREME_KEYS:
        finite = [(row["date"], _to_float(row.get(key))) for row in rows]
        finite = [(day, value) for day, value in finite if math.isfinite(value)]
        if not finite:
            continue
        min_day, min_value = min(finite, key=lambda item: item[1])
        max_day, max_value = max(finite, key=lambda item: item[1])
        reasons[min_day].append(f"{key} 区间最低 {min_value:.2f}")
        reasons[max_day].append(f"{key} 区间最高 {max_value:.2f}")


def _add_threshold_crossings(rows: list[dict[str, Any]], reasons: dict[str, list[str]]) -> None:
    thresholds = (
        ("composite", 60.0),
        ("fund_flow", 50.0),
        ("technical", 40.0),
        ("technical", 60.0),
        ("positive_return_20d_count", 10.0),
        ("positive_return_20d_count", 20.0),
        ("positive_return_60d_count", 3.0),
    )
    for previous, current in pairwise(rows):
        for key, threshold in thresholds:
            before = _to_float(previous.get(key))
            after = _to_float(current.get(key))
            if before < threshold <= after:
                reasons[current["date"]].append(f"{key} 上穿 {threshold:g}")
            elif before >= threshold > after:
                reasons[current["date"]].append(f"{key} 下穿 {threshold:g}")


def _add_daily_delta_extremes(rows: list[dict[str, Any]], reasons: dict[str, list[str]]) -> None:
    keys = ("composite", "fund_flow", "technical", "sentiment")
    for key in keys:
        deltas = []
        for previous, current in pairwise(rows):
            delta = _to_float(current.get(key)) - _to_float(previous.get(key))
            if math.isfinite(delta):
                deltas.append((current["date"], delta))
        if not deltas:
            continue
        up_day, up_delta = max(deltas, key=lambda item: item[1])
        down_day, down_delta = min(deltas, key=lambda item: item[1])
        reasons[up_day].append(f"{key} 单日最大上行 {up_delta:.2f}")
        reasons[down_day].append(f"{key} 单日最大下行 {down_delta:.2f}")


def _signal_payload(row: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    keys = (
        "date",
        "composite",
        "risk_level",
        "fund_flow",
        "technical",
        "sentiment",
        "valuation",
        "structure_health",
        "positive_return_20d_count",
        "positive_return_60d_count",
    )
    payload = {key: row.get(key) for key in keys}
    payload["reasons"] = reasons
    return payload


def _industry_frequency(
    market_rows: list[dict[str, Any]],
    panel_rows: list[dict[str, Any]],
    dates: list[str],
) -> dict[str, Any]:
    return {
        "brief_candidate_counts": _list_counter(market_rows, "candidate_industries"),
        "brief_risk_counts": _list_counter(market_rows, "risk_industries"),
        "brief_lagging_counts": _list_counter(market_rows, "lagging_industries"),
        "top5_counts": _panel_counter(
            panel_rows,
            "structure_rank",
            lambda value: _to_float(value) <= 5,
        ),
        "top1_counts": _panel_counter(
            panel_rows,
            "structure_rank",
            lambda value: _to_float(value) == 1,
        ),
        "crowding_counts": _panel_counter(
            panel_rows,
            "crowding_temperature",
            lambda value: _to_float(value) >= 80,
        ),
        "tcr_change": _tcr_change(panel_rows, dates),
    }


def _list_counter(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter.update(row.get(key) or [])
    return [{"industry_name": name, "days": days} for name, days in counter.most_common()]


def _panel_counter(
    rows: list[dict[str, Any]],
    key: str,
    predicate: Any,
) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for row in rows:
        if predicate(row.get(key)):
            counter[str(row.get("industry_name"))] += 1
    return [{"industry_name": name, "days": days} for name, days in counter.most_common()]


def _tcr_change(rows: list[dict[str, Any]], dates: list[str]) -> list[dict[str, Any]]:
    size = max(1, len(dates) // 3)
    early_dates = set(dates[:size])
    late_dates = set(dates[-size:])
    early = _avg_by_industry(rows, early_dates, "tcr")
    late = _avg_by_industry(rows, late_dates, "tcr")
    changes = []
    for name in sorted(set(early) & set(late)):
        changes.append(
            {
                "industry_name": name,
                "early_tcr": round(early[name], 4),
                "late_tcr": round(late[name], 4),
                "delta": round(late[name] - early[name], 4),
            }
        )
    return sorted(changes, key=lambda row: row["delta"], reverse=True)


def _avg_by_industry(
    rows: list[dict[str, Any]],
    selected_dates: set[str],
    key: str,
) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = _to_float(row.get(key))
        if row.get("date") in selected_dates and math.isfinite(value):
            values[str(row.get("industry_name"))].append(value)
    return {name: sum(items) / len(items) for name, items in values.items() if items}


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# A 股市场跨周期复盘",
        "",
        f"- 起止日期: {payload['start_date']} 至 {payload['end_date']}",
        f"- 交易日数: {payload['date_count']}",
        "- 口径: 只读取已落盘市场温度、行业结构和投资者简报产物；不使用新闻、政策或模型记忆。",
        "",
        "## 市场摘要",
        "",
    ]
    lines.extend(_market_summary_lines(payload["market_summary"]))
    lines.extend(["", "## 阶段变化", ""])
    lines.extend(_phase_table(payload["phase_summary"]))
    lines.extend(["", "## 重要信号日", ""])
    lines.extend(_signal_table(payload["signal_days"]))
    lines.extend(["", "## 行业资金与结构频率", ""])
    lines.extend(_industry_frequency_lines(payload["industry_frequency"]))
    lines.extend(["", "## 使用提醒", ""])
    lines.extend(
        [
            "- 综合温度用于判断系统风险和参与环境，行业结构用于判断方向，不要混为一个分数。",
            "- 20日扩散强但60日确认弱时，优先按短线修复处理。",
            "- 资金温度、两融变化和主力净流入用于确认行情质量；价格先行不等于资金确认。",
            "- 高TCR或高拥挤温度行业可以继续交易活跃，但不应直接视为低风险配置方向。",
        ]
    )
    return "\n".join(lines) + "\n"


def _market_summary_lines(summary: dict[str, Any]) -> list[str]:
    series = summary["series"]
    return [
        f"- 综合温度: {series['composite']['start']} -> {series['composite']['end']}，"
        f"均值 {series['composite']['mean']}，区间最低 "
        f"{series['composite']['min']['date']}={series['composite']['min']['value']}，"
        f"最高 {series['composite']['max']['date']}={series['composite']['max']['value']}。",
        f"- 资金面: {series['fund_flow']['start']} -> {series['fund_flow']['end']}，"
        f"均值 {series['fund_flow']['mean']}。",
        f"- 技术面: {series['technical']['start']} -> {series['technical']['end']}，"
        f"均值 {series['technical']['mean']}。",
        f"- 20日上涨行业数: {series['positive_return_20d_count']['start']} -> "
        f"{series['positive_return_20d_count']['end']}；60日上涨行业数: "
        f"{series['positive_return_60d_count']['start']} -> "
        f"{series['positive_return_60d_count']['end']}。",
        f"- 系统风险分布: {_format_counts(summary['risk_level_counts'])}。",
        f"- 结构健康度分布: {_format_counts(summary['structure_health_counts'])}。",
    ]


def _phase_table(phases: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| 阶段 | 综合 | 资金 | 技术 | 情绪 | 20日上涨行业 | 60日上涨行业 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in phases:
        lines.append(
            f"| {row['start_date']}..{row['end_date']} | {_fmt(row['composite'])} | "
            f"{_fmt(row['fund_flow'])} | {_fmt(row['technical'])} | "
            f"{_fmt(row['sentiment'])} | {_fmt(row['positive_return_20d_count'])} | "
            f"{_fmt(row['positive_return_60d_count'])} |"
        )
    return lines


def _signal_table(signal_days: list[dict[str, Any]], limit: int = 24) -> list[str]:
    lines = [
        "| 日期 | 综合 | 风险 | 资金 | 技术 | 20日/60日行业 | 信号 |",
        "|---|---:|---|---:|---:|---:|---|",
    ]
    selected = _important_signal_days(signal_days, limit)
    for row in selected:
        reasons = "；".join(row["reasons"][:4])
        lines.append(
            f"| {row['date']} | {_fmt(row['composite'])} | {row['risk_level']} | "
            f"{_fmt(row['fund_flow'])} | {_fmt(row['technical'])} | "
            f"{row['positive_return_20d_count']}/{row['positive_return_60d_count']} | "
            f"{reasons} |"
        )
    return lines


def _important_signal_days(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    priority_words = ("区间", "最高", "最低", "切换", "上穿 20", "下穿 3", "最大")
    ranked = sorted(
        rows,
        key=lambda row: sum(
            any(word in reason for word in priority_words) for reason in row["reasons"]
        ),
        reverse=True,
    )
    selected_dates = {row["date"] for row in ranked[:limit]}
    return [row for row in rows if row["date"] in selected_dates]


def _industry_frequency_lines(freq: dict[str, Any]) -> list[str]:
    return [
        f"- 候选行业出现频率 Top: {_format_industries(freq['brief_candidate_counts'], 8)}。",
        f"- 拥挤风险出现频率 Top: {_format_industries(freq['brief_risk_counts'], 8)}。",
        f"- 落后方向出现频率 Top: {_format_industries(freq['brief_lagging_counts'], 8)}。",
        f"- 结构分 Top5 频率 Top: {_format_industries(freq['top5_counts'], 8)}。",
        f"- 拥挤温度>=80 频率 Top: {_format_industries(freq['crowding_counts'], 8)}。",
        f"- TCR 边际上升 Top: {_format_tcr_changes(freq['tcr_change'][:8])}。",
        f"- TCR 边际下降 Top: {_format_tcr_changes(list(reversed(freq['tcr_change'][-8:])))}。",
    ]


def _format_counts(counts: dict[str, int]) -> str:
    return "，".join(f"{key} {value}天" for key, value in counts.items())


def _format_industries(rows: list[dict[str, Any]], limit: int) -> str:
    return "、".join(f"{row['industry_name']}({row['days']})" for row in rows[:limit]) or "无"


def _format_tcr_changes(rows: list[dict[str, Any]]) -> str:
    return "、".join(f"{row['industry_name']}({row['delta']:+.2f})" for row in rows) or "无"


def _write_artifacts(
    output_root: Path,
    payload: dict[str, Any],
    markdown: str,
    *,
    update_latest: bool,
) -> dict[str, Path]:
    run_id = f"run_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    run_dir = (
        output_root
        / "runs"
        / f"start={payload['start_date']}_end={payload['end_date']}"
        / run_id
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    json_path = run_dir / "review.json"
    markdown_path = run_dir / "review.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    if update_latest:
        latest_dir = output_root / "latest"
        latest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(json_path, latest_dir / json_path.name)
        shutil.copy2(markdown_path, latest_dir / markdown_path.name)
    return {"json": json_path, "markdown": markdown_path}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _names(rows: list[dict[str, Any]]) -> list[str]:
    return [str(row["industry_name"]) for row in rows if row.get("industry_name")]


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [_to_float(row.get(key)) for row in rows]
    finite = [value for value in values if math.isfinite(value)]
    return round(sum(finite) / len(finite), 4) if finite else None


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _fmt(value: Any) -> str:
    number = _to_float(value)
    return f"{number:.2f}" if math.isfinite(number) else ""


if __name__ == "__main__":
    raise SystemExit(main())
