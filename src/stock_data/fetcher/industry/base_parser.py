"""产业数据 HTML 解析器协议与通用抽取工具库 (HtmlParserProtocol & Helpers)。

实现数据抓取 (I/O) 与数据解析 (Pure Transformation) 的彻底解耦与策略模式注入。
"""

from __future__ import annotations

import re
from typing import Any, Protocol, TypeVar, runtime_checkable

from bs4 import BeautifulSoup

T_out = TypeVar("T_out", covariant=True)


@runtime_checkable
class HtmlParserProtocol(Protocol[T_out]):
    """产业 HTML 解析器统一策略协议。"""

    def parse(self, html_text: str, **kwargs: Any) -> T_out | None:
        """解析 HTML 字符串并返回结构化数据字典/模型，解析失败或数据缺失时返回 None。"""
        ...


def clean_html_text(val: str | None) -> str:
    """清理字符串中的空白字符与千分位逗号。"""
    if not val:
        return ""
    return val.replace(",", "").replace("\xa0", " ").strip()


def extract_first_float(raw: str | None) -> float | None:
    """从文本中提取第一个浮点数 (支持正负号与小数点)。"""
    if raw is None:
        return None
    cleaned = clean_html_text(raw).replace(" ", "")
    m = re.search(r"[-+]?\d+\.?\d*", cleaned)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def parse_html_tables_to_rows(
    html_text: str,
    class_filter: str | None = None,
) -> list[list[str]]:
    """提取 HTML 页面中符合类名过滤条件的表格所有数据行 (包含 th/td 单元格纯文本)。"""
    soup = BeautifulSoup(html_text, "html.parser")
    all_rows: list[list[str]] = []
    for table in soup.find_all("table"):
        if class_filter:
            classes = " ".join(table.get("class") or [])
            if class_filter not in classes:
                continue
        for tr in table.find_all("tr"):
            cells = [
                clean_html_text(cell.get_text(" ", strip=True))
                for cell in tr.find_all(["td", "th"])
            ]
            if cells and any(cells):
                all_rows.append(cells)
    return all_rows
