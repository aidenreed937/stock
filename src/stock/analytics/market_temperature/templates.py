"""市场温度计报告模板。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

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
    "macro_vix_temperature": "VIX外部温度",
    "macro_us_10y_temperature": "美债10年收益率温度",
    "macro_copper_20d_return_temperature": "铜价20日收益温度",
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
    ),
    "technical": ("return_20d", "rsi_14d", "above_ma20_share", "above_ma60_share"),
    "fundamental": (
        "fs_profit_growth_temperature",
        "forecast_positive_temperature",
        "report_revision_temperature",
    ),
    "macro_liquidity": (
        "macro_external_environment_temperature",
        "macro_sp500_20d_return_temperature",
        "macro_nasdaq_20d_return_temperature",
        "macro_bond_yield_10y_temperature",
        "macro_shibor_on_temperature",
        "macro_real_rate_temperature",
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
        f"- 状态: {composite['status']}",
        "",
        "## 一句话结论",
        "",
        _one_line_summary(dimensions, temperature),
        "",
        "## 系统性风险",
        "",
        *_systemic_risk_section(scores),
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
        lines.append(f"- 主要风险: {'；'.join(red_flags)}")
    if warnings:
        lines.append(f"- 观察信号: {'；'.join(warnings)}")
    if offsets:
        lines.append(f"- 缓冲因素: {'；'.join(offsets)}")
    return lines


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
        for row in issues:
            lines.append(
                "- {source}.{dataset}: {status}，{note}".format(
                    source=row["data_source"],
                    dataset=row["dataset"],
                    status=row["status"],
                    note=row["note"],
                )
            )
    else:
        lines.append("- 本次配置内核心数据水位未发现异常。")
    lines.extend(
        [
            "- 资金流数据可能晚于行情日，资金结论以指标事实中的 metric_date 为准。",
            "- 季频财报和月频宏观数据只代表最新状态，不代表最近20个交易日内的边际变化。",
            "- 涨跌停事件来自 limit_list_d，不包含 ST 股票统计；stk_limit 只代表涨跌停价格。",
            "- 期权合约与日行情当前只做水位披露，未定义隐含波动率前不进入温度。",
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


def _as_float(value: object) -> float | None:
    if isinstance(value, int | float | str):
        return float(value)
    return None
