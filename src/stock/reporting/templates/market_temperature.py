"""市场温度计报告模板。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

from stock.reporting.core.watermark import (
    human_watermark_issue_lines,
    human_watermark_latest_text,
)

if TYPE_CHECKING:
    from stock.analytics.market_temperature.config import MarketTemperatureConfig

_METRIC_LABELS = {
    "valuation_temperature": "估值温度",
    "pe_percentile_5y": "PE五年分位",
    "pb_percentile_5y": "PB五年分位",
    "equity_risk_premium": "股权风险溢价",
    "margin_buy_share_zscore_60d": "融资买入占比60日Z分",
    "margin_penetration_percentile_1250d": "两融渗透率五年分位",
    "margin_balance_growth_20d": "两融余额20日变化",
    "main_money_net_inflow_share": "主力净流入成交占比",
    "market_amount_percentile_1250d": "成交额五年分位",
    "turnover_rate_percentile_1250d": "换手率五年分位",
    "advance_share": "上涨家数占比",
    "investor_account_temperature": "月度新增投资者温度",
    "limit_event_temperature": "涨跌停情绪温度",
    "limit_up_count_temperature": "涨停家数温度",
    "limit_down_count_temperature": "跌停家数反向温度",
    "limit_up_down_strength_temperature": "涨跌停强弱温度",
    "limit_seal_success_temperature": "封板成功率温度",
    "option_risk_temperature": "期权风险温度",
    "option_put_call_volume_ratio_temperature": "认沽/认购成交量比温度",
    "option_put_call_oi_ratio_temperature": "认沽/认购持仓比温度",
    "option_amount_temperature": "期权成交额温度",
    "option_open_interest_temperature": "期权持仓量温度",
    "option_near_month_amount_share_temperature": "近月期权成交占比温度",
    "return_20d": "20日收益中位数",
    "rsi_14d": "RSI中位数",
    "ma_bias_20d": "20日均线乖离中位数",
    "above_ma20_share": "站上20日线占比",
    "above_ma60_share": "站上60日线占比",
    "fs_revenue_growth_temperature": "收入正增长行业占比",
    "fs_profit_growth_temperature": "利润正增长行业占比",
    "fs_roe_temperature": "ROE历史分位",
    "forecast_positive_temperature": "正向业绩预告占比",
    "report_revision_temperature": "盈利预测上修占比",
    "macro_bond_yield_10y_temperature": "10年国债流动性温度",
    "macro_shibor_on_temperature": "Shibor O/N流动性温度",
    "macro_real_rate_temperature": "实际利率流动性温度",
    "macro_m2_yoy_temperature": "M2同比温度",
    "macro_social_finance_stock_temperature": "社融存量同比温度",
    "macro_external_environment_temperature": "外部环境温度",
    "macro_sp500_20d_return_temperature": "标普500 20日收益温度",
    "macro_nasdaq_20d_return_temperature": "纳斯达克20日收益温度",
    "macro_usd_index_temperature": "美元指数外部温度",
    "macro_usd_index_20d_change_temperature": "美元指数20日变化温度",
    "macro_cnh_20d_change_temperature": "人民币汇率20日变化温度",
    "macro_vix_temperature": "VIX外部温度",
    "macro_us_10y_temperature": "美债10年收益率温度",
    "macro_copper_20d_return_temperature": "铜价20日收益温度",
    "macro_gold_20d_return_pressure": "黄金20日收益压力",
    "macro_oil_20d_return_pressure": "原油20日收益压力",
    "macro_safe_haven_pressure_temperature": "避险压力",
    "macro_inflation_pressure_temperature": "通胀压力",
    "macro_demand_pressure_temperature": "需求压力",
    "macro_external_pressure_temperature": "总体外部压力",
    "macro_fred_t10y2y_temperature": "美国期限利差温度",
    "macro_fred_fedfunds_temperature": "美国政策利率温度",
    "macro_fred_walcl_temperature": "美联储资产负债表温度",
    "macro_fred_cpi_yoy_temperature": "美国CPI同比反向温度",
    "macro_fred_unrate_temperature": "美国失业率反向温度",
    "macro_fred_payems_yoy_temperature": "美国非农同比温度",
    "macro_fred_gdp_yoy_temperature": "美国GDP同比温度",
}

_DIMENSION_FOCUS = {
    "valuation": ("估值水位", "日频估值主要由价格驱动，高温表示安全边际收缩。"),
    "fund_flow": ("资金确认", "资金数据较快但常晚一日，用于确认行情质量。"),
    "sentiment": (
        "交易情绪",
        "日频情绪观察短线热度和赚钱效应，月度新增投资者只作慢变量。",
    ),
    "technical": ("趋势广度", "日频技术最敏感，优先用于判断20日趋势和扩散。"),
    "fundamental": ("盈利底座", "财报是低频底座，预告和研报才反映近20日预期变化。"),
    "macro_liquidity": ("宏观流动性", "利率和外盘较快，货币信用/CPI偏慢，主要看风险环境。"),
}

_DIMENSION_TIMELINESS = {
    "technical": (
        "短线信号",
        "最快",
        "日频行情与宽度",
        "先看趋势、均线宽度和超买超卖。",
    ),
    "sentiment": (
        "短线信号",
        "快，含月频慢变量",
        "日频换手、上涨扩散、涨跌停事件，叠加月度新增投资者",
        "日频看赚钱效应是否扩散，开户温度只看参与热度水位。",
    ),
    "valuation": (
        "约束信号",
        "快",
        "日频估值与价格",
        "看安全边际，不单独代表盈利变化。",
    ),
    "fund_flow": (
        "确认信号",
        "较快",
        "两融和资金流常晚一日",
        "看资金是否确认技术修复。",
    ),
    "macro_liquidity": (
        "环境底座",
        "分化",
        "利率/外盘日频，货币信用月频",
        "看估值环境和外部风险偏好，不直接解释20日边际变化。",
    ),
    "fundamental": (
        "盈利底座",
        "偏慢",
        "财报季频，预告/研报较快",
        "财报看底座，预告和上修比例看近期预期。",
    ),
}

_DIMENSION_LABELS = {
    "valuation": "估值面",
    "fund_flow": "资金面",
    "sentiment": "情绪面",
    "technical": "技术面",
    "fundamental": "基本面",
    "macro_liquidity": "宏观流动性",
}

_PREFERRED_METRICS = {
    "valuation": ("valuation_temperature", "pe_percentile_5y", "pb_percentile_5y"),
    "fund_flow": (
        "margin_penetration_percentile_1250d",
        "margin_balance_growth_20d",
        "main_money_net_inflow_share",
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
    }


def render_report_markdown(
    *,
    config: MarketTemperatureConfig,
    manifest: dict[str, Any],
    scores: dict[str, Any],
    facts: pl.DataFrame,
) -> str:
    """渲染 Markdown 报告。"""
    lines = [
        f"# {config.title}",
        "",
        f"- 基准日期: {manifest['as_of_date']}",
        f"- 主窗口: 最近 {manifest['main_window']} 个已落盘交易日",
        f"- 短线补充窗口: {', '.join(str(value) for value in manifest['short_windows'])} 日",
        f"- 产物运行 ID: {manifest['run_id']}",
        "",
        "## 综合温度",
        "",
        f"- 状态: {scores['composite']['status']}",
        f"- 温度: {scores['composite']['temperature']}",
        f"- 说明: {scores['composite']['reason']}",
        "",
        "## 系统性风险",
        "",
        *_systemic_risk_section(scores),
        "",
        "## 六维状态",
        "",
        "| 维度 | 权重 | 温度 | 状态 | 指标事实 | 说明 |",
        "|---|---:|---:|---|---:|---|",
    ]
    for item in scores["dimensions"]:
        lines.append(
            "| {name} | {weight:.0%} | {temperature} | {status} | {ok}/{total} | {reason} |".format(
                name=item["name"],
                weight=item["weight"],
                temperature=item["temperature"],
                status=item["status"],
                ok=item["ok_metric_count"],
                total=item["metric_count"],
                reason=item["reason"],
            )
        )
    lines.extend(_facts_sections(facts))
    return "\n".join(lines) + "\n"


def render_human_report_markdown(
    *,
    config: MarketTemperatureConfig,
    manifest: dict[str, Any],
    scores: dict[str, Any],
    facts: pl.DataFrame,
    comparison: dict[str, Any] | None = None,
) -> str:
    """渲染面向人工阅读的 Markdown 报告。"""
    composite = scores["composite"]
    temperature = composite["temperature"]
    window_text = _window_text(manifest)
    dimensions = list(scores["dimensions"])
    lines = [
        f"# {config.title}人工阅读版",
        "",
        f"- 基准日期: {manifest['as_of_date']}",
        f"- 观察窗口: {window_text}",
        f"- 综合温度: {_temperature_text(temperature)} / 100",
        f"- 系统性风险: {_systemic_risk_level(scores)}",
        f"- 状态: {_report_status_label(composite.get('status'))}",
        "",
        "## 一句话结论",
        "",
        _one_line_summary(dimensions, temperature),
        "",
        "## 读法总览",
        "",
        *_human_reading_brief(dimensions, scores, facts),
        "",
        *_cross_period_change_section(
            comparison=comparison,
            current_manifest=manifest,
            current_scores=scores,
        ),
        "## 数据质量提示",
        "",
        *_human_quality_brief(facts),
        "",
        "## 关键背离",
        "",
        *_key_divergence_section(dimensions, facts),
        "",
        "## 系统性风险",
        "",
        *_systemic_risk_section(scores),
        "",
        "## 外部压力提示",
        "",
        *_external_pressure_section(facts),
        "",
        "## 后续跟踪",
        "",
        *_follow_up_section(dimensions, facts, scores),
        "",
        "## 解读顺序",
        "",
        *_interpretation_priority_rows(dimensions),
        "",
        "## 六维解读",
        "",
        "| 维度 | 温度 | 分档 | 解读 |",
        "|---|---:|---|---|",
    ]
    for item in dimensions:
        dimension_id = str(item["dimension_id"])
        item_temperature = item["temperature"]
        lines.append(
            "| {name} | {temperature} | {band} | {comment} |".format(
                name=item["name"],
                temperature=_temperature_text(item_temperature),
                band=_temperature_band(item_temperature),
                comment=_dimension_comment(dimension_id, item_temperature),
            )
        )
    lines.extend(_human_fact_sections(facts))
    lines.extend(_human_limit_sections(facts))
    return "\n".join(lines) + "\n"


def summarize_facts(facts: pl.DataFrame) -> dict[str, Any]:
    """汇总事实表状态。"""
    if facts.is_empty():
        return {"rows": 0, "by_status": {}, "by_category": {}}
    return {
        "rows": facts.height,
        "by_status": _count_by(facts, "status"),
        "by_category": _count_by(facts, "category"),
    }


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
    return lines


def _count_by(facts: pl.DataFrame, column: str) -> dict[str, int]:
    return {
        str(row[column]): int(row["len"])
        for row in facts.group_by(column).len().sort(column).to_dicts()
    }


def _window_text(manifest: dict[str, Any]) -> str:
    dates = list(manifest.get("trade_dates", ()))
    if dates:
        return f"{dates[0]} 至 {dates[-1]}，共 {len(dates)} 个已落盘交易日"
    return f"最近 {manifest['main_window']} 个已落盘交易日"


def _one_line_summary(dimensions: list[dict[str, Any]], temperature: object) -> str:
    band = _temperature_band(temperature)
    valid = [item for item in dimensions if _as_float(item.get("temperature")) is not None]
    if not valid:
        return f"综合温度暂不可判定，当前状态为{band}，需要先补齐核心指标事实。"
    hottest = max(valid, key=_score_temperature)
    coldest = min(valid, key=_score_temperature)
    return (
        f"综合温度处于{band}；最高维度是{hottest['name']}({_temperature_text(hottest['temperature'])})，"
        f"最低维度是{coldest['name']}({_temperature_text(coldest['temperature'])})。"
        "解读时优先看高温维度是否由资金和基本面共同确认。"
    )


def _human_reading_brief(
    dimensions: list[dict[str, Any]], scores: dict[str, Any], facts: pl.DataFrame
) -> list[str]:
    composite = scores.get("composite", {})
    composite_temperature = composite.get("temperature") if isinstance(composite, dict) else None
    valid = [item for item in dimensions if _as_float(item.get("temperature")) is not None]
    hot = [item for item in valid if (_as_float(item.get("temperature")) or 0.0) >= 70]
    cold = [item for item in valid if (_as_float(item.get("temperature")) or 0.0) < 40]
    lines = [
        "- 先定市场环境: "
        f"综合温度 {_temperature_text(composite_temperature)}，"
        f"系统性风险 {_systemic_risk_level(scores)}；"
        "它回答的是整体风险偏好和追高安全边际，不直接等同于行业方向。"
    ]
    if hot:
        lines.append(f"- 高温来源: {_dimension_list_text(hot)}；这些维度决定风险上沿。")
    if cold:
        lines.append(
            f"- 拖累来源: {_dimension_list_text(cold)}；这些维度说明行情质量尚未全面确认。"
        )

    valuation = _dimension_temperature(dimensions, "valuation")
    fund_flow = _dimension_temperature(dimensions, "fund_flow")
    sentiment = _dimension_temperature(dimensions, "sentiment")
    technical = _dimension_temperature(dimensions, "technical")
    fundamental = _dimension_temperature(dimensions, "fundamental")
    macro = _dimension_temperature(dimensions, "macro_liquidity")

    if (
        technical is not None
        and technical < 40
        and any(value is not None and value >= 70 for value in (valuation, fund_flow, sentiment))
    ):
        lines.append(
            "- 最容易误读: 技术面低温不是低风险，而是趋势广度弱；"
            "它衡量最近20个交易日的中位收益和均线宽度，不等同于基准日当天涨跌；"
            "如果估值、资金或情绪同时偏热，通常表示热度集中在少数方向。"
        )
    investor_temperature = _metric_float(facts, "investor_account_temperature")
    if investor_temperature is not None and investor_temperature >= 80:
        if sentiment is not None and sentiment < 65:
            lines.append(
                "- 慢变量情绪: 月度新增投资者处于高温，但日频情绪未同步过热；"
                "这代表参与热度水位高，不代表基准日全面亢奋。"
            )
        else:
            lines.append(
                "- 慢变量情绪: 月度新增投资者处于高温，"
                "需和换手、上涨家数、涨跌停事件一起判断情绪拥挤。"
            )
    if valuation is not None and valuation >= 80:
        lines.append(
            "- 估值约束: 估值高温主要由价格和估值分位驱动，"
            "含义是安全边际收缩，不代表盈利已经同步改善。"
        )
    if fund_flow is not None and fund_flow >= 70 and technical is not None and technical < 40:
        lines.append(
            "- 资金读法: 资金面高温但技术面偏冷时，重点看资金是否集中在少数方向，"
            "需要用行业结构报告验证扩散程度。"
        )
    if fundamental is not None and macro is not None:
        lines.append(
            "- 慢变量读法: 基本面和宏观流动性更多是底座；"
            "月频、季频指标只能说明最新状态，不能解释最近20个交易日内的每一次波动。"
        )
    if _has_pending_short_term(scores):
        lines.append("- 短线节奏: 5/10日短线温度尚未形成正式分数，短节奏优先看行业报告。")
    return lines


def _systemic_risk_section(scores: dict[str, Any]) -> list[str]:
    risk = scores.get("systemic_risk", {})
    if not isinstance(risk, dict) or not risk:
        return ["- 系统性风险暂不可判定。"]
    lines = [
        f"- 风险等级: {risk.get('level', '不可判定')}",
        f"- 结论: {risk.get('message', '')}",
    ]
    red_flags = _text_items(risk.get("red_flags"))
    warnings = _text_items(risk.get("warnings"))
    offsets = _text_items(risk.get("offsets"))
    if red_flags:
        lines.append(f"- 主要风险: {_join_text_items(red_flags)}")
    if warnings:
        lines.append(f"- 观察信号: {_join_text_items(warnings)}")
    if offsets:
        lines.append(f"- 缓冲因素: {_join_text_items(offsets)}")
    return lines


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


def _score_composite_temperature(scores: dict[str, Any]) -> float | None:
    composite = scores.get("composite", {})
    if not isinstance(composite, dict):
        return None
    return _as_float(composite.get("temperature"))


def _delta_text(value: float | None) -> str:
    return "不可判定" if value is None else f"{value:+.2f}"


def _cross_period_comment(name: str, delta: float | None, fallback: str) -> str:
    if delta is None:
        return fallback
    absolute = abs(delta)
    if name == "综合温度" and absolute < 3:
        return "总分接近，重点看内部驱动是否换挡。"
    if absolute < 5:
        return "变化不大。"
    direction = "升温" if delta > 0 else "降温"
    strength = "明显" if absolute >= 20 else ""
    return f"{strength}{direction}，{fallback}"


def _systemic_risk_level(scores: dict[str, Any]) -> str:
    risk = scores.get("systemic_risk", {})
    if not isinstance(risk, dict) or not risk:
        return "不可判定"
    return str(risk.get("level") or "不可判定")


def _dimension_list_text(rows: list[dict[str, Any]]) -> str:
    parts = [
        f"{item.get('name', '')} {_temperature_text(item.get('temperature'))}"
        for item in rows
        if item.get("name")
    ]
    return "、".join(parts) if parts else "无"


def _dimension_comment(dimension_id: str, temperature: object) -> str:
    focus, base = _DIMENSION_FOCUS.get(dimension_id, ("维度状态", "按当前温度分档解读。"))
    band = _temperature_band(temperature)
    value = _as_float(temperature)
    if value is None:
        return f"{focus}暂不可判定；{base}"
    if value >= 80:
        prefix = f"{focus}高温"
    elif value >= 60:
        prefix = f"{focus}偏热"
    elif value >= 40:
        prefix = f"{focus}中性"
    elif value >= 20:
        prefix = f"{focus}偏冷"
    else:
        prefix = f"{focus}低温"
    return f"{prefix}，处于{band}；{base}"


def _interpretation_priority_rows(dimensions: list[dict[str, Any]]) -> list[str]:
    rows_by_dimension = {str(item["dimension_id"]): item for item in dimensions}
    lines = [
        "| 层级 | 维度 | 温度 | 跟踪速度 | 读法 |",
        "|---|---|---:|---|---|",
    ]
    for dimension_id, (layer, speed, basis, usage) in _DIMENSION_TIMELINESS.items():
        item = rows_by_dimension.get(dimension_id)
        if item is None:
            continue
        lines.append(
            "| {layer} | {name} | {temperature} | {speed} | {basis}；{usage} |".format(
                layer=layer,
                name=item["name"],
                temperature=_temperature_text(item.get("temperature")),
                speed=speed,
                basis=basis,
                usage=usage,
            )
        )
    return lines


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


def _key_divergence_section(dimensions: list[dict[str, Any]], facts: pl.DataFrame) -> list[str]:
    valuation = _dimension_temperature(dimensions, "valuation")
    fund_flow = _dimension_temperature(dimensions, "fund_flow")
    sentiment = _dimension_temperature(dimensions, "sentiment")
    technical = _dimension_temperature(dimensions, "technical")
    fundamental = _dimension_temperature(dimensions, "fundamental")
    macro = _dimension_temperature(dimensions, "macro_liquidity")
    investor_temperature = _metric_float(facts, "investor_account_temperature")
    margin_growth = _metric_float(facts, "margin_balance_growth_20d")
    main_money = _metric_float(facts, "main_money_net_inflow_share")
    lines: list[str] = []

    if technical is not None and fund_flow is not None and technical >= 60 and fund_flow < 50:
        detail = []
        if margin_growth is not None:
            detail.append(f"两融余额20日变化 {margin_growth:.2%}")
        if main_money is not None:
            detail.append(f"主力净流入占比 {main_money:.2%}")
        suffix = f"；{'，'.join(detail)}" if detail else ""
        lines.append(
            "- 价格修复的资金确认不足: "
            f"技术面 {_temperature_text(technical)}，"
            f"资金面 {_temperature_text(fund_flow)}{suffix}。"
        )
    if (
        investor_temperature is not None
        and investor_temperature >= 80
        and (sentiment is None or sentiment < 65)
    ):
        lines.append(
            "- 开户热度与日频情绪背离: "
            f"新增投资者温度 {_temperature_text(investor_temperature)}，"
            f"情绪面 {_temperature_text(sentiment)}；慢变量高温尚未等同于当日全面过热。"
        )
    if valuation is not None and macro is not None and valuation >= 80 and macro >= 60:
        lines.append(
            "- 估值约束与流动性支撑并存: "
            f"估值面 {_temperature_text(valuation)}，宏观流动性 {_temperature_text(macro)}；"
            "低利率能支撑风险偏好，但高估值会压缩追高安全边际。"
        )
    if (
        fundamental is not None
        and fundamental >= 50
        and _has_dataset_status(facts, "sw_2021_fs_", {"lagging"})
    ):
        lines.append(
            "- 基本面分数可用但正式财报偏慢: "
            f"基本面 {_temperature_text(fundamental)}；季频行业财报只作底座，"
            "近20日变化应优先看预告和研报上修事实。"
        )
    return lines or ["- 暂未发现需要单独强调的维度背离。"]


def _follow_up_section(
    dimensions: list[dict[str, Any]], facts: pl.DataFrame, scores: dict[str, Any]
) -> list[str]:
    fund_flow = _dimension_temperature(dimensions, "fund_flow")
    if fund_flow is not None and fund_flow >= 50:
        fund_flow_line = (
            "- 资金确认: 观察资金面高温能否延续，尤其是两融余额、主力净流入是否继续改善；"
            "若趋势广度不跟随，高资金分可能只是集中交易。"
        )
    else:
        fund_flow_line = (
            "- 资金确认: 观察资金面温度是否回到50以上，以及两融余额、主力净流入是否由收缩转为改善。"
        )
    lines = [
        fund_flow_line,
        "- 趋势确认: 观察站上60日线占比是否继续提高，避免只有20日修复而中期趋势未确认。",
    ]
    investor_temperature = _metric_float(facts, "investor_account_temperature")
    if investor_temperature is not None and investor_temperature >= 80:
        lines.append(
            "- 情绪传导: 新增开户已处高温时，继续跟踪换手率、上涨家数和涨跌停事件是否同步升温。"
        )
    if _has_dataset_status(facts, "sw_2021_fs_", {"lagging"}) or _has_dataset_status(
        facts, "", {"lagging"}
    ):
        lines.append("- 慢变量更新: 月频宏观和季频财报更新后再复核基本面、宏观流动性分数。")
    if _has_pending_short_term(scores):
        lines.append("- 短线温度: 5/10日短线温度仍待接入或待计算，短节奏暂不要当成正式温度分。")
    return lines


def _external_pressure_section(facts: pl.DataFrame) -> list[str]:
    metric_ids = (
        "macro_external_pressure_temperature",
        "macro_safe_haven_pressure_temperature",
        "macro_inflation_pressure_temperature",
        "macro_demand_pressure_temperature",
    )
    rows = [_metric_row_by_id(facts, metric_id) for metric_id in metric_ids]
    available = [
        row for row in rows if row is not None and _as_float(row.get("value_float")) is not None
    ]
    if not available:
        return ["- 暂无外部压力项事实；该模块只作风险背景，不进入综合温度。"]

    lines = [
        "- 口径: 分数越高代表外盘对 A 股的额外压力越大；该模块默认 weight=0，不进入六维综合温度。",
        "",
        "| 压力项 | 分数 | 分档 | 读法 |",
        "|---|---:|---|---|",
    ]
    for row in available:
        metric_id = str(row["metric_id"])
        value = _as_float(row.get("value_float"))
        name = _METRIC_LABELS.get(metric_id, metric_id)
        band = _pressure_band(value)
        comment = _pressure_comment(metric_id, value)
        lines.append(f"| {name} | {_temperature_text(value)} | {band} | {comment} |")
    return lines


def _pressure_band(value: object) -> str:
    pressure = _as_float(value)
    if pressure is None:
        return "不可判定"
    if pressure >= 80:
        return "高压力"
    if pressure >= 60:
        return "中等偏高"
    if pressure >= 40:
        return "中性"
    return "压力不明显"


def _pressure_comment(metric_id: str, value: object) -> str:
    pressure = _as_float(value)
    if pressure is None:
        return "样本不足，不能解读。"
    if metric_id == "macro_external_pressure_temperature":
        base = "取避险、通胀、需求三类压力的最大值，用于提示外盘风险来源。"
    elif metric_id == "macro_safe_haven_pressure_temperature":
        base = "观察黄金、VIX 和美股是否共同指向避险交易。"
    elif metric_id == "macro_inflation_pressure_temperature":
        base = "观察原油、美债收益率和美国CPI是否共同形成估值分母压力。"
    elif metric_id == "macro_demand_pressure_temperature":
        base = "观察铜、原油和美股是否共同指向全球需求走弱。"
    else:
        base = "仅作外部背景观察。"
    if pressure >= 80:
        return f"压力高，{base}"
    if pressure >= 60:
        return f"压力偏高，{base}"
    if pressure >= 40:
        return f"压力中性，{base}"
    return f"压力不明显，{base}"


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
        value_float = _as_float(row["value_float"])
        value = "" if value_float is None else f"{value_float:.6g}"
        sample_size = "" if row["sample_size"] is None else str(row["sample_size"])
        lines.append(
            "| {dimension} | {metric} | {value} | {sample} | {note} |".format(
                dimension=_DIMENSION_LABELS.get(str(row["dimension"]), str(row["dimension"])),
                metric=_METRIC_LABELS.get(str(row["metric_id"]), str(row["metric_id"])),
                value=value,
                sample=sample_size,
                note=row["note"],
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


def _temperature_band(value: object) -> str:
    temperature = _as_float(value)
    if temperature is None:
        return "不可判定"
    if temperature < 20:
        return "低温机会区"
    if temperature < 40:
        return "偏冷修复观察区"
    if temperature < 60:
        return "中性轮动区"
    if temperature < 80:
        return "偏热修复区"
    return "高温拥挤区"


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
