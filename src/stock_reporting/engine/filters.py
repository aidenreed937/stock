"""Markdown 报告专用 Jinja2 过滤器库 (Filters Library)。

提供统一、安全的数值格式化、单位转换与标准 GitHub Flavored Markdown 表格生成函数。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import polars as pl

if TYPE_CHECKING:
    from jinja2 import Environment


def format_pct(
    value: float | int | None,
    digits: int = 2,
    *,
    signed: bool = True,
) -> str:
    """格式化百分比数值。

    Args:
        value: 浮点数或整数，如 0.052 代表 5.2%
        digits: 保留小数位数
        signed: 是否显式展示正负号 (+/-)

    Examples:
        >>> format_pct(0.052, digits=2, signed=True)
        '+5.20%'
        >>> format_pct(-0.0035, digits=2, signed=True)
        '-0.35%'
        >>> format_pct(None)
        '-'
    """
    if value is None:
        return "-"
    fmt = f"{'+' if signed else ''}.{digits}f"
    return f"{format(float(value) * 100, fmt)}%"


def format_decimal(
    value: float | int | None,
    digits: int = 2,
    *,
    signed: bool = False,
    thousands_sep: bool = True,
) -> str:
    """格式化浮点数或整数，支持千分位与正负号。

    Args:
        value: 数值输入
        digits: 保留小数位数
        signed: 是否显式展示正负号 (+/-)
        thousands_sep: 是否使用千分位逗号

    Examples:
        >>> format_decimal(3450.2, digits=2)
        '3,450.20'
        >>> format_decimal(0.45, digits=1, signed=True)
        '+0.5'
        >>> format_decimal(None)
        '-'
    """
    if value is None:
        return "-"
    sep = "," if thousands_sep else ""
    sign = "+" if signed else ""
    fmt = f"{sign}{sep}.{digits}f"
    return format(float(value), fmt)


def format_currency_yi(value: float | int | None, digits: int = 2) -> str:
    """金额换算为'亿元'单位展示。

    Args:
        value: 基础货币金额（元）
        digits: 保留小数位数

    Examples:
        >>> format_currency_yi(18200000000)
        '182.00 亿'
        >>> format_currency_yi(None)
        '-'
    """
    if value is None:
        return "-"
    return f"{float(value) / 1e8:.{digits}f} 亿"


def format_currency_wan(value: float | int | None, digits: int = 2) -> str:
    """金额换算为'万元'单位展示。"""
    if value is None:
        return "-"
    return f"{float(value) / 1e4:.{digits}f} 万"


def _extract_table_data(
    data: list[dict[str, Any]] | pl.DataFrame | None,
    headers: list[str] | None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """提取表格表头与行字典列表。"""
    if data is None:
        return [], []
    if isinstance(data, pl.DataFrame):
        if data.is_empty():
            return [], []
        actual_headers = headers if headers is not None else list(data.columns)
        valid_cols = [c for c in actual_headers if c in data.columns]
        if not valid_cols:
            return [], []
        return valid_cols, data.select(valid_cols).to_dicts()

    if not data:
        return [], []
    actual_headers = headers if headers is not None else list(data[0].keys())
    return actual_headers, data


def render_markdown_table(
    data: list[dict[str, Any]] | pl.DataFrame | None,
    headers: list[str] | None = None,
    alignments: dict[str, str] | None = None,
) -> str:
    """将字典列表或 Polars DataFrame 渲染为标准 GitHub 风格 Markdown 表格。"""
    actual_headers, rows = _extract_table_data(data, headers)
    if not actual_headers or not rows:
        return "*暂无数据*"

    alignments = alignments or {}
    align_tokens: list[str] = []
    for h in actual_headers:
        align = alignments.get(h, "left").lower()
        if align in ("right", "r"):
            align_tokens.append("---:")
        elif align in ("center", "c"):
            align_tokens.append(":---:")
        else:
            align_tokens.append("---")

    header_line = "| " + " | ".join(actual_headers) + " |"
    separator_line = "| " + " | ".join(align_tokens) + " |"

    body_lines: list[str] = []
    for row in rows:
        cells = [str(row.get(h, "")) if row.get(h) is not None else "" for h in actual_headers]
        clean_cells = [c.replace("\n", " ").replace("\r", "") for c in cells]
        body_lines.append("| " + " | ".join(clean_cells) + " |")

    return "\n".join([header_line, separator_line, *body_lines])


def register_filters(env: Environment) -> None:
    """向 Jinja2 Environment 注册全部自定义过滤器。"""
    env.filters["pct"] = format_pct
    env.filters["decimal"] = format_decimal
    env.filters["yi"] = format_currency_yi
    env.filters["wan"] = format_currency_wan
    env.filters["md_table"] = render_markdown_table
