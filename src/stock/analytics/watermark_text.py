"""数据水位事实的人读文案。"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

_STATUS_LABELS = {
    "ok": "正常",
    "lagging": "更新偏慢",
    "missing": "缺失",
    "error": "异常",
    "future": "日期晚于基准日",
    "insufficient": "样本不足",
}

_DATASET_LABELS = {
    ("tushare", "stock_daily_bar"): "A股全市场行情",
    ("tushare", "daily_basic"): "全市场估值与成交活跃度",
    ("tushare", "margin"): "两融数据",
    ("tushare", "moneyflow"): "个股资金流",
    ("tushare", "moneyflow_hsgt"): "北向资金相关数据",
    ("tushare", "stk_limit"): "涨跌停价格表",
    ("tushare", "limit_list_d"): "涨跌停事件表",
    ("tushare", "opt_basic"): "期权静态合约表",
    ("tushare", "opt_daily"): "期权日行情",
    ("tushare", "forecast"): "业绩预告",
    ("tushare", "express"): "业绩快报",
    ("tushare", "report_rc"): "卖方盈利预测",
    ("tushare", "index_classify"): "申万行业分类字典",
    ("tushare", "index_daily"): "宽基指数行情",
    ("tushare", "index_member"): "申万行业成份股映射",
    ("tushare", "sw_daily"): "申万行业指数行情",
    ("tushare", "shibor"): "银行间短端利率",
    ("lixinger", "cn_m"): "M1/M2 月度货币数据",
    ("lixinger", "sf_month"): "社融月度数据",
    ("tushare", "cn_cpi"): "中国CPI月度数据",
    ("lixinger", "index_fundamental"): "核心指数估值",
    ("lixinger", "national_debt"): "中国国债收益率",
    ("lixinger", "sw_2021_fundamental"): "申万一级行业估值",
    ("lixinger", "sw_2021_constituents"): "申万行业成份股图谱",
    ("lixinger", "investor_accounts"): "月度新增投资者",
    ("yfinance", "index_daily_bar"): "外盘指数行情",
    ("yfinance", "macro_indicators"): "外部环境代理数据",
    ("alphavantage", "macro_indicators"): "USD/CNH 外汇日线",
    ("fred", "macro_indicators"): "美国宏观背景数据",
}

_GROUP_LABELS = {
    "industry_financial_statement": "行业季频财报",
}

_GROUP_NOTES = {
    "industry_financial_statement": (
        "季频财报只作基本面底座，近20日变化优先看预告、快报和研报上修。"
    ),
    "tushare.index_classify": "行业范围已回退为申万行业行情可用代码，名称由行情或估值表补齐。",
    "lixinger.cn_m": "月频宏观只代表最新状态，不代表20日边际变化。",
    "lixinger.sf_month": "月频宏观只代表最新状态，不代表20日边际变化。",
    "tushare.cn_cpi": "月频宏观只代表最新状态，不代表20日边际变化。",
    "lixinger.investor_accounts": "新增投资者是月频慢变量，只反映参与热度水位。",
    "tushare.opt_basic": "期权合约用于PCR和期限成交观察，默认不进入主温度。",
    "tushare.opt_daily": "期权日行情用于PCR、成交和持仓观察，隐含波动率指标待定义。",
    "yfinance.macro_indicators": "外部环境按可用子项重归一，缺失项不补值。",
    "alphavantage.macro_indicators": "USD/CNH 只作人民币汇率压力观察项，不参与综合温度。",
    "fred.macro_indicators": "美国宏观背景是观察项，不参与综合温度。",
}


def human_watermark_issue_lines(rows: list[dict[str, Any]], *, max_groups: int = 6) -> list[str]:
    """把数据水位异常行转成业务可读摘要。"""
    groups = _group_watermark_rows(rows)
    if not groups:
        return []

    lines: list[str] = []
    for item in list(groups.values())[:max_groups]:
        label = _group_label(item)
        status = _status_text(item)
        latest = _latest_phrase(item)
        note = _group_note(item)
        suffix = f"；{_rstrip_sentence_end(note)}" if note else ""
        lines.append(f"- {label}: {status}，{latest}{suffix}。")

    extra_count = max(len(groups) - max_groups, 0)
    if extra_count:
        lines.append(f"- 另有 {extra_count} 类数据水位提醒，详见质量报告。")
    return lines


def human_watermark_latest_text(rows: list[dict[str, Any]], *, max_groups: int = 6) -> str:
    """把数据水位最新日期转成业务可读短句。"""
    groups = list(_group_watermark_rows(rows).values())
    parts = []
    for item in groups[:max_groups]:
        latest_values = _latest_values(item)
        latest = "、".join(latest_values) if latest_values else "无最新日期"
        parts.append(f"{_group_label(item)} {latest}")
    extra_count = max(len(groups) - max_groups, 0)
    if extra_count:
        parts.append(f"另有{extra_count}类详见质量报告")
    return "、".join(parts) if parts else "无"


def _group_watermark_rows(
    rows: list[dict[str, Any]],
) -> OrderedDict[str, list[dict[str, Any]]]:
    groups: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for row in rows:
        key = _group_key(row)
        groups.setdefault(key, []).append(row)
    return groups


def _group_key(row: dict[str, Any]) -> str:
    dataset = str(row.get("dataset") or "")
    if dataset.startswith("sw_2021_fs_"):
        return "industry_financial_statement"
    return f"{row.get('data_source')}.{dataset}"


def _group_label(rows: list[dict[str, Any]]) -> str:
    key = _group_key(rows[0])
    if key in _GROUP_LABELS:
        return _GROUP_LABELS[key]
    row = rows[0]
    data_source = str(row.get("data_source") or "")
    dataset = str(row.get("dataset") or "")
    return _DATASET_LABELS.get((data_source, dataset)) or str(row.get("note") or "配置数据集")


def _status_text(rows: list[dict[str, Any]]) -> str:
    labels = []
    for row in rows:
        status = str(row.get("status") or "")
        label = _STATUS_LABELS.get(status, status or "状态未知")
        if label not in labels:
            labels.append(label)
    return "、".join(labels)


def _latest_phrase(rows: list[dict[str, Any]]) -> str:
    latest_values = _latest_values(rows)
    if not latest_values:
        return "无最新日期"
    if len(latest_values) == 1:
        return f"最新 {latest_values[0]}"
    return "最新日期 " + "、".join(latest_values)


def _latest_values(rows: list[dict[str, Any]]) -> list[str]:
    values = []
    for row in rows:
        value = str(row.get("value_text") or "")
        if value and value not in values:
            values.append(value)
    return values


def _group_note(rows: list[dict[str, Any]]) -> str:
    key = _group_key(rows[0])
    if key in _GROUP_NOTES:
        return _GROUP_NOTES[key]
    notes = []
    for row in rows:
        note = str(row.get("note") or "")
        if note and note not in notes:
            notes.append(note)
    return "；".join(notes[:2])


def _rstrip_sentence_end(value: str) -> str:
    return value.rstrip("。；; ")
