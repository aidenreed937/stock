"""市场温度计报告模板。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

import stock_reporting.templates.input_validation as _input_validation
from stock_reporting.core.watermark import (
    human_watermark_issue_lines,
    human_watermark_latest_text,
)
from stock_reporting.engine.renderer import ReportRenderer

if TYPE_CHECKING:
    from stock_reporting.interpretation.market_temperature.config import MarketTemperatureConfig

from stock_reporting.interpretation.market_temperature.interpretation import (
    _DIMENSION_FOCUS,
    _DIMENSION_LABELS,
    _METRIC_LABELS,
)
from stock_reporting.interpretation.market_temperature.interpretation import (
    evaluate_external_pressure_section as _external_pressure_section,
)
from stock_reporting.interpretation.market_temperature.interpretation import (
    evaluate_follow_ups as _follow_up_section,
)
from stock_reporting.interpretation.market_temperature.interpretation import (
    evaluate_interpretation_priority_rows as _interpretation_priority_rows,
)
from stock_reporting.interpretation.market_temperature.interpretation import (
    evaluate_key_divergences as _key_divergence_section,
)
from stock_reporting.interpretation.market_temperature.interpretation import (
    evaluate_one_line_summary as _one_line_summary,
)
from stock_reporting.interpretation.market_temperature.interpretation import (
    evaluate_reading_brief as _human_reading_brief,
)
from stock_reporting.interpretation.market_temperature.interpretation import (
    evaluate_systemic_risk_section as _systemic_risk_section,
)
from stock_reporting.interpretation.market_temperature.interpretation import (
    get_cross_period_comment as _cross_period_comment,
)
from stock_reporting.interpretation.market_temperature.interpretation import (
    get_systemic_risk_level as _systemic_risk_level,
)
from stock_reporting.interpretation.market_temperature.interpretation import (
    get_temperature_band as _temperature_band,
)
from stock_reporting.templates.availability import (
    domain_observation_lines as _domain_observation_lines,
)
from stock_reporting.templates.external_risk import external_risk_lines as _external_risk_section
from stock_reporting.templates.market_temperature_details import (
    dimension_interpretation_comment as _dimension_interpretation_comment,
)
from stock_reporting.templates.market_temperature_details import (
    format_fact_metric_value as _format_fact_metric_value,
)
from stock_reporting.templates.market_temperature_details import (
    score_composite_temperature as _score_composite_temperature,
)
from stock_reporting.templates.market_temperature_details import (
    structured_drivers_section as _structured_drivers_section,
)
from stock_reporting.templates.market_temperature_details import (
    subgroup_text as _subgroup_text,
)
from stock_reporting.templates.market_temperature_details import (
    summarize_facts,
)

_PREFERRED_METRICS = {
    "valuation": ("valuation_temperature", "pe_percentile_10y", "pb_percentile_10y"),
    "fund_flow": (
        "margin_penetration_percentile_1250d",
        "margin_balance_growth_20d",
        "main_money_net_inflow_share",
        "main_money_net_inflow_share_20d_cum",
    ),
    "sentiment": (
        "turnover_rate_percentile_1250d",
        "advance_share",
        "investor_account_temperature",
        "limit_event_temperature",
        "limit_up_count_temperature",
        "limit_seal_success_temperature",
        "option_risk_temperature",
    ),
    "technical": ("return_20d", "rsi_14d", "above_ma20_share", "above_ma60_share"),
    "fundamental": (
        "fs_profit_growth_temperature",
        "forecast_positive_temperature",
        "report_revision_temperature",
    ),
    "macro_liquidity": (
        "macro_external_environment_temperature",
        "macro_external_pressure_temperature",
        "macro_safe_haven_pressure_temperature",
        "macro_inflation_pressure_temperature",
        "macro_demand_pressure_temperature",
        "macro_sp500_20d_return_temperature",
        "macro_nasdaq_20d_return_temperature",
        "macro_bond_yield_10y_temperature",
        "macro_shibor_on_temperature",
        "macro_real_rate_temperature",
        "macro_gold_20d_return_pressure",
        "macro_oil_20d_return_pressure",
        "macro_cnh_20d_change_temperature",
        "macro_fred_t10y2y_temperature",
        "macro_fred_fedfunds_temperature",
        "macro_fred_walcl_temperature",
        "macro_fred_cpi_yoy_temperature",
        "macro_fred_unrate_temperature",
        "macro_fred_payems_yoy_temperature",
        "macro_fred_gdp_yoy_temperature",
    ),
}


def build_report_json(
    *,
    config: MarketTemperatureConfig,
    manifest: dict[str, Any],
    scores: dict[str, Any],
    facts: pl.DataFrame,
) -> dict[str, Any]:
    """构造机器可读报告。"""
    return {
        "schema_version": config.schema_version,
        "title": config.title,
        "manifest": manifest,
        "scores": scores,
        "fact_summary": summarize_facts(facts),
        "availability": _input_validation.fact_availability(
            facts, _input_validation.MARKET_FACT_COLUMNS
        ),
    }


def render_report_markdown(
    *,
    config: MarketTemperatureConfig,
    manifest: dict[str, Any],
    scores: dict[str, Any],
    facts: pl.DataFrame,
) -> str:
    """渲染 Markdown 报告。"""
    if unavailable := _input_validation.market_unavailable(config.title, facts):
        return unavailable
    facts_sec = "\n".join(_facts_sections(facts)).strip()
    context = {
        "title": config.title,
        "manifest": manifest,
        "short_windows_str": ", ".join(str(value) for value in manifest.get("short_windows", [])),
        "composite": scores.get("composite", {}),
        "systemic_risk_lines": _systemic_risk_section(scores),
        "external_risk_lines": _external_risk_section(scores, config),
        "dimensions": scores.get("dimensions", []),
        "facts_sections": facts_sec,
    }
    return ReportRenderer.get_instance().render("temperature/market_temperature.md.j2", context)


def render_human_report_markdown(
    *,
    config: MarketTemperatureConfig,
    manifest: dict[str, Any],
    scores: dict[str, Any],
    facts: pl.DataFrame,
    comparison: dict[str, Any] | None = None,
) -> str:
    """渲染面向人工阅读的 Markdown 报告。"""
    if unavailable := _input_validation.market_unavailable(config.title, facts):
        return unavailable
    composite = scores["composite"]
    temperature = composite["temperature"]
    window_text = _window_text(manifest)
    dimensions = list(scores["dimensions"])

    dim_interpretations = []
    for item in dimensions:
        item_temperature = item["temperature"]
        dim_interpretations.append(
            {
                "name": item["name"],
                "temperature": _temperature_text(item_temperature),
                "band": _temperature_band(item_temperature),
                "comment": _dimension_interpretation_comment(item),
                "subgroups": _subgroup_text(item),
            }
        )

    cross_period_lines = _cross_period_change_section(
        comparison=comparison,
        current_manifest=manifest,
        current_scores=scores,
    )
    if cross_period_lines and cross_period_lines[-1] == "":
        cross_period_lines.pop()

    context = {
        "title": config.title,
        "manifest": manifest,
        "window_text": window_text,
        "composite_temp_text": _temperature_text(temperature),
        "systemic_risk_level": _systemic_risk_level(scores),
        "status_label": _report_status_label(composite.get("status")),
        "one_line_summary": _one_line_summary(dimensions, temperature),
        "reading_brief_lines": _human_reading_brief(dimensions, scores, facts),
        "cross_period_lines": cross_period_lines,
        "quality_brief_lines": _human_quality_brief(facts),
        "divergence_lines": _key_divergence_section(dimensions, facts),
        "systemic_risk_lines": _systemic_risk_section(scores),
        "external_risk_lines": _external_risk_section(scores, config),
        "external_pressure_lines": _external_pressure_section(facts),
        "follow_up_lines": _follow_up_section(dimensions, facts, scores),
        "interpretation_priority_lines": _interpretation_priority_rows(dimensions),
        "dimension_interpretations": dim_interpretations,
        "fact_sections": "\n".join(_human_fact_sections(facts)).strip(),
        "limit_sections": "\n".join(_human_limit_sections(facts)).strip(),
    }
    return ReportRenderer.get_instance().render(
        "temperature/market_temperature_human.md.j2", context
    )


def _facts_sections(facts: pl.DataFrame) -> list[str]:
    if facts.is_empty():
        return ["", "## 事实层", "", "无事实记录。"]
    lines = [
        "",
        "## 数据水位",
        "",
        "| 数据源 | 数据集 | 维度 | 最新日期 | 状态 | 说明 |",
        "|---|---|---|---|---|---|",
    ]
    watermarks = facts.filter(pl.col("category") == "data_watermark").sort(
        ["data_source", "dataset"]
    )
    for row in watermarks.to_dicts():
        lines.append(
            "| {source} | {dataset} | {dimension} | {value} | {status} | {note} |".format(
                source=row["data_source"],
                dataset=row["dataset"],
                dimension=row["dimension"],
                value=row["value_text"],
                status=row["status"],
                note=row["note"],
            )
        )
    lines.extend(
        [
            "",
            "## 指标事实",
            "",
            "| 维度 | 指标 | 数值 | 样本数 | 状态 | 说明 |",
            "|---|---|---:|---:|---|---|",
        ]
    )
    metrics = facts.filter(pl.col("category") == "metric_value").sort(["dimension", "metric_id"])
    for row in metrics.to_dicts():
        value = "" if row["value_float"] is None else f"{float(row['value_float']):.6g}"
        sample_size = "" if row["sample_size"] is None else str(row["sample_size"])
        lines.append(
            "| {dimension} | {metric} | {value} | {sample_size} | {status} | {note} |".format(
                dimension=row["dimension"],
                metric=row["metric_id"],
                value=value,
                sample_size=sample_size,
                status=row["status"],
                note=row["note"],
            )
        )
    lines.extend(_domain_observation_lines(facts))
    return lines


def _window_text(manifest: dict[str, Any]) -> str:
    dates = list(manifest.get("trade_dates", ()))
    if dates:
        return f"{dates[0]} 至 {dates[-1]}，共 {len(dates)} 个已落盘交易日"
    return f"最近 {manifest['main_window']} 个已落盘交易日"


def _cross_period_change_section(
    *,
    comparison: dict[str, Any] | None,
    current_manifest: dict[str, Any],
    current_scores: dict[str, Any],
) -> list[str]:
    previous_manifest = (
        comparison.get("previous_manifest") if isinstance(comparison, dict) else None
    )
    previous_scores = comparison.get("previous_scores") if isinstance(comparison, dict) else None
    if not isinstance(previous_manifest, dict):
        previous_manifest = None
    if not isinstance(previous_scores, dict):
        previous_scores = None
    if not previous_scores:
        return []

    drivers = current_scores.get("drivers")
    if isinstance(drivers, dict) and drivers.get("status") == "ok":
        return _structured_drivers_section(
            drivers=drivers,
            previous_manifest=previous_manifest,
            current_manifest=current_manifest,
        )

    previous_date = (
        str(previous_manifest.get("as_of_date")) if isinstance(previous_manifest, dict) else "前期"
    )
    current_date = str(current_manifest.get("as_of_date") or "本期")
    previous_dimensions = _dimension_rows_by_id(previous_scores)
    current_dimensions = list(current_scores.get("dimensions", []))
    rows: list[tuple[str, float | None, float | None, str]] = [
        (
            "综合温度",
            _score_composite_temperature(previous_scores),
            _score_composite_temperature(current_scores),
            "总温度接近时，不代表市场状态相同；要看内部驱动迁移。",
        )
    ]

    for current in current_dimensions:
        dimension_id = str(current.get("dimension_id") or "")
        previous = previous_dimensions.get(dimension_id)
        previous_temperature = (
            _as_float(previous.get("temperature")) if isinstance(previous, dict) else None
        )
        current_temperature = _as_float(current.get("temperature"))
        focus, _ = _DIMENSION_FOCUS.get(dimension_id, ("维度", ""))
        rows.append(
            (
                str(current.get("name") or _DIMENSION_LABELS.get(dimension_id) or dimension_id),
                previous_temperature,
                current_temperature,
                f"{focus}的跨期变化。",
            )
        )

    lines = [
        "## 跨期驱动变化",
        "",
        f"- 对比基准: {previous_date} -> {current_date}",
        "- 读法: 先看综合温度是否变化，再看是哪几个维度驱动了变化，"
        "避免只因总分接近而误判状态相同。",
        "",
        "| 项目 | 前期 | 本期 | 变化 | 读法 |",
        "|---|---:|---:|---:|---|",
    ]
    for name, previous_temperature, current_temperature, comment in rows:
        delta = (
            current_temperature - previous_temperature
            if previous_temperature is not None and current_temperature is not None
            else None
        )
        previous_text = _temperature_text(previous_temperature)
        current_text = _temperature_text(current_temperature)
        delta_text = _delta_text(delta)
        comment_text = _cross_period_comment(name, delta, comment)
        lines.append(
            f"| {name} | {previous_text} | {current_text} | {delta_text} | {comment_text} |"
        )
    lines.append("")
    return lines


def _dimension_rows_by_id(scores: dict[str, Any]) -> dict[str, dict[str, Any]]:
    dimensions = scores.get("dimensions", [])
    if not isinstance(dimensions, list):
        return {}
    return {
        str(item.get("dimension_id")): item
        for item in dimensions
        if isinstance(item, dict) and item.get("dimension_id")
    }


def _delta_text(value: float | None) -> str:
    return "不可判定" if value is None else f"{value:+.2f}"


def _human_quality_brief(facts: pl.DataFrame) -> list[str]:
    watermarks = _watermark_rows(facts)
    if not watermarks:
        return ["- 未提供数据水位事实，数据质量只能以产物生成状态为准。"]

    lines: list[str] = []
    issues = [row for row in watermarks if str(row.get("status")) != "ok"]
    hard_issues = [
        row for row in issues if str(row.get("status")) in {"error", "missing", "future"}
    ]
    if hard_issues:
        lines.append("- 硬约束: 存在缺失、异常或日期越界的数据，详见质量报告。")
        lines.extend(human_watermark_issue_lines(hard_issues, max_groups=5))
    elif issues:
        lines.append("- 水位提醒: 存在更新偏慢或样本不足的数据，主报告仅保留影响摘要。")
        lines.extend(human_watermark_issue_lines(issues, max_groups=5))
    else:
        lines.append("- 核心水位未发现硬错误。")

    fund_rows = [
        row
        for row in watermarks
        if row.get("dataset") in {"moneyflow", "moneyflow_hsgt", "margin"} and row.get("value_text")
    ]
    if fund_rows:
        lines.append(
            f"- 资金确认: {human_watermark_latest_text(fund_rows)}；"
            "资金流和两融指标以各自事实日期为准。"
        )

    slow_rows = [
        row
        for row in watermarks
        if row.get("dataset") in {"cn_m", "sf_month", "investor_accounts"}
        or str(row.get("dataset", "")).startswith("sw_2021_fs_")
    ]
    if slow_rows:
        lines.append(
            "- 慢变量: "
            f"{human_watermark_latest_text(slow_rows, max_groups=6)}；"
            "月频/季频数据只代表最新状态或底座。"
        )
    return lines


def _clean_fact_note(note: str) -> str:
    if not note:
        return ""
    parts = [p.strip() for p in note.replace("；", ";").split(";") if p.strip()]
    cleaned_parts = [_clean_part(p) for p in parts if not _is_engineering_param(p)]
    return "；".join(p for p in cleaned_parts if p)


def _is_engineering_param(p: str) -> bool:
    return any(p.startswith(prefix) for prefix in ("metric_date=", "source=", "aggregation="))


def _clean_part(p: str) -> str:
    if p.startswith("latest_value="):
        return _format_latest_val_str(p[len("latest_value=") :].strip())
    if p.startswith("latest_date="):
        return f"最新日期 {p[len('latest_date=') :]}"
    if p.startswith("ann_window="):
        return f"公告窗口 {p[len('ann_window=') :]}"
    if p.startswith("report_date="):
        return f"报告期 {p[len('report_date=') :]}"
    return p


def _format_latest_val_str(val_str: str) -> str:
    try:
        val = float(val_str)
        if val >= 1_000_000:
            return f"最新值 {val / 10000:.2f}万"
        if 0 < abs(val) < 0.1:
            return f"最新值 {val * 100:+.2f}%"
        return f"最新值 {val:.2f}"
    except ValueError:
        return f"最新值 {val_str}"


def _human_fact_sections(facts: pl.DataFrame) -> list[str]:
    lines = [
        "",
        "## 关键事实",
        "",
        "| 维度 | 指标 | 数值 | 样本 | 说明 |",
        "|---|---|---:|---:|---|",
    ]
    rows = _preferred_metric_rows(facts)
    if not rows:
        return [*lines, "| - | - | - | - | 无可用指标事实 |"]
    for row in rows:
        metric_id = str(row["metric_id"])
        value_float = _as_float(row["value_float"])
        value = _format_fact_metric_value(metric_id, value_float)
        sample_size = "" if row["sample_size"] is None else str(row["sample_size"])
        note = _clean_fact_note(str(row.get("note") or ""))
        lines.append(
            "| {dimension} | {metric} | {value} | {sample} | {note} |".format(
                dimension=_DIMENSION_LABELS.get(str(row["dimension"]), str(row["dimension"])),
                metric=_METRIC_LABELS.get(metric_id, metric_id),
                value=value,
                sample=sample_size,
                note=note,
            )
        )
    return lines


def _preferred_metric_rows(facts: pl.DataFrame) -> list[dict[str, Any]]:
    if facts.is_empty():
        return []
    frame = facts.filter(
        (pl.col("category") == "metric_value")
        & (pl.col("status") == "ok")
        & pl.col("value_float").is_not_null()
    )
    rows_by_metric = {str(row["metric_id"]): row for row in frame.to_dicts()}
    rows: list[dict[str, Any]] = []
    for metric_ids in _PREFERRED_METRICS.values():
        rows.extend(
            rows_by_metric[metric_id] for metric_id in metric_ids if metric_id in rows_by_metric
        )
    return rows


def _metric_row_by_id(facts: pl.DataFrame, metric_id: str) -> dict[str, Any] | None:
    required = {"category", "metric_id"}
    if facts.is_empty() or not required.issubset(set(facts.columns)):
        return None
    frame = facts.filter(
        (pl.col("category") == "metric_value") & (pl.col("metric_id") == metric_id)
    )
    if "status" in frame.columns:
        ok_frame = frame.filter(pl.col("status") == "ok")
        if not ok_frame.is_empty():
            frame = ok_frame
    rows = frame.to_dicts()
    return rows[0] if rows else None


def _metric_float(facts: pl.DataFrame, metric_id: str) -> float | None:
    row = _metric_row_by_id(facts, metric_id)
    if row is None:
        return None
    return _as_float(row.get("value_float"))


def _dimension_temperature(dimensions: list[dict[str, Any]], dimension_id: str) -> float | None:
    for item in dimensions:
        if str(item.get("dimension_id")) == dimension_id:
            return _as_float(item.get("temperature"))
    return None


def _watermark_rows(facts: pl.DataFrame) -> list[dict[str, Any]]:
    if facts.is_empty() or "category" not in facts.columns:
        return []
    return facts.filter(pl.col("category") == "data_watermark").to_dicts()


def _has_dataset_status(facts: pl.DataFrame, dataset_prefix: str, statuses: set[str]) -> bool:
    for row in _watermark_rows(facts):
        dataset = str(row.get("dataset") or "")
        if dataset_prefix and not dataset.startswith(dataset_prefix):
            continue
        if str(row.get("status")) in statuses:
            return True
    return False


def _has_pending_short_term(scores: dict[str, Any]) -> bool:
    short_term = scores.get("short_term")
    if not isinstance(short_term, list):
        return False
    return any(isinstance(item, dict) and item.get("status") == "pending" for item in short_term)


def _human_limit_sections(facts: pl.DataFrame) -> list[str]:
    lines = ["", "## 数据限制", ""]
    if facts.is_empty() or "category" not in facts.columns:
        watermarks = pl.DataFrame()
    else:
        watermarks = facts.filter(pl.col("category") == "data_watermark")
    issues = (
        watermarks.filter(pl.col("status") != "ok").to_dicts() if not watermarks.is_empty() else []
    )
    if issues:
        lines.extend(human_watermark_issue_lines(issues, max_groups=8))
    else:
        lines.append("- 本次配置内核心数据水位未发现异常。")
    lines.extend(
        [
            "- 资金流数据可能晚于行情日，资金结论以指标事实中的 metric_date 为准。",
            "- 季频财报和月频宏观数据只代表最新状态，不代表最近20个交易日内的边际变化。",
            "- 涨跌停事件来自 limit_list_d，不包含 ST 股票统计；stk_limit 只代表涨跌停价格。",
            (
                "- 期权合约与日行情仅用于PCR、成交额、持仓和近月合约热度观察；"
                "未定义隐含波动率前不进入主温度。"
            ),
            "- 本报告只基于本地 Curated 数据和已定义指标，不纳入新闻、政策文本或信用利差。",
        ]
    )
    return lines


def _temperature_text(value: object) -> str:
    numeric = _as_float(value)
    return "不可判定" if numeric is None else f"{numeric:.2f}"


def _text_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _join_text_items(items: list[str]) -> str:
    return "；".join(item.rstrip("。；; ") for item in items if item.strip())


def _score_temperature(item: dict[str, Any]) -> float:
    return _as_float(item.get("temperature")) or 0.0


def _report_status_label(value: object) -> str:
    status = str(value or "")
    return {
        "ready": "可用",
        "partial": "部分可用",
        "insufficient": "样本不足",
        "failed": "失败",
        "pending": "待计算",
    }.get(status, status or "未知")


def _as_float(value: object) -> float | None:
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None
