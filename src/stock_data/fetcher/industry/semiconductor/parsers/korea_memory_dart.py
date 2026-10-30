"""DART 定期报告发现、文档节点定位和韩国存储财报 HTML 解析。

本模块只处理 DART 的源端表示：金额保持报告列示的 KRW million，季度成本的
差分由采集器根据报告期上下文完成。这样可以把网页结构变化与 FX/DOI 派生逻辑
隔离开，并允许直接用 RAW HTML 快照做离线回归。
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

DART_REPORT_URL_PREFIX = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="


@dataclass(frozen=True)
class DartReport:
    """DART 搜索结果中的一份定期报告。"""

    company: str
    report_quarter: str
    report_type: str
    filing_date: date
    rcp_no: str
    dcm_no: str = ""
    title: str = ""
    source_url: str = ""
    is_revision: bool = False


@dataclass(frozen=True)
class DartTocNode:
    """DART report viewer 主页面中的一个文档节点。"""

    text: str
    rcp_no: str
    dcm_no: str
    ele_id: str
    offset: str
    length: str
    dtd: str
    toc_no: str = ""


@dataclass(frozen=True)
class SamsungInventoryFact:
    """三星 C. Inventory 表的源端事实。"""

    inventory_krw_million: float
    group_inventory_krw_million: float
    inventory_scope: str


@dataclass(frozen=True)
class SamsungSegmentFact:
    """三星分部摘要表的累计 DS 收入和营业利润。"""

    ds_revenue_krw_million: float
    ds_operating_profit_krw_million: float
    reported_unit: str = "million_krw"


@dataclass(frozen=True)
class SkHynixFinancialFact:
    """SK 海力士合并财务报表中的库存和营业成本。"""

    inventory_krw_million: float
    cost_of_revenue_quarter_krw_million: float | None
    cost_of_revenue_cumulative_krw_million: float | None
    cost_of_revenue_annual_krw_million: float | None


def normalize_dart_text(value: str) -> str:
    """压缩 DART HTML 中的空白和实体，保留韩文/英文可检索文本。"""
    text = html_lib.unescape(value or "")
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def parse_report_quarter(
    title: str,
    report_type: str,
    filing_date: date,
) -> str | None:
    """从 DART 报告标题推导自然季度，标题不带期间时使用保守回退。"""
    text = normalize_dart_text(title)
    matches = re.findall(r"(20\d{2})\s*[./-]\s*(\d{1,2})", text)
    if matches:
        # DART 列表行通常同时包含报告期 ``(2025.12)`` 和提交日
        # ``2026.03.10``，报告期在前，不能取最后一个日期。
        year, month = (int(item) for item in matches[0])
        quarter = {3: 1, 6: 2, 9: 3, 12: 4}.get(month)
        if quarter is not None:
            return f"{year}Q{quarter}"

    year = filing_date.year
    normalized_type = report_type.lower()
    if "business" in normalized_type or "사업" in text:
        if filing_date.month <= 4:
            year -= 1
        return f"{year}Q4"
    if "half" in normalized_type or "반기" in text:
        return f"{year}Q2"
    if "quarter" in normalized_type or "분기" in text:
        quarter = 1 if filing_date.month <= 6 else 3
        return f"{year}Q{quarter}"
    return None


def normalize_report_type(title: str) -> str | None:
    """将 DART 报告名归一为业务报告/半期报告/季度报告。"""
    text = normalize_dart_text(title)
    if "사업보고서" in text:
        return "business_report"
    if "반기보고서" in text:
        return "half_year_report"
    if "분기보고서" in text:
        return "quarterly_report"
    return None


def parse_dart_search_results(
    content: str | bytes,
    *,
    company: str,
) -> list[DartReport]:
    """解析 DART ``search.ax`` 返回的 HTML 列表。

    DART 页面没有稳定的 JSON 接口；报告链接通过 ``openReportViewer`` 的
    JavaScript 调用暴露。解析同时支持链接属性和 HTML 中的调用文本，避免
    仅依赖当前列表 CSS class。
    """
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    soup = BeautifulSoup(text, "html.parser")
    reports: dict[str, DartReport] = {}

    anchors = soup.find_all("a")
    for anchor in anchors:
        call = " ".join(
            str(anchor.get(attribute) or "") for attribute in ("onclick", "href", "data-url")
        )
        match = re.search(
            r"openReport(?:Viewer|ListViewer|ViewerEng)?\s*\(\s*['\"](\d{10,})['\"]"
            r"\s*(?:,\s*['\"]?(\d*)['\"]?)?",
            call,
        )
        if match is None:
            continue
        rcp_no, dcm_no = match.group(1), match.group(2) or ""
        row = anchor.find_parent("tr")
        row_text = normalize_dart_text(row.get_text(" ", strip=True) if row else anchor.text)
        report_type = normalize_report_type(row_text)
        if report_type is None:
            continue
        date_matches = re.findall(r"20\d{2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2}", row_text)
        if not date_matches:
            continue
        filing_date = _parse_date(date_matches[-1])
        report_quarter = parse_report_quarter(row_text, report_type, filing_date)
        if report_quarter is None:
            continue
        report = DartReport(
            company=company,
            report_quarter=report_quarter,
            report_type=report_type,
            filing_date=filing_date,
            rcp_no=rcp_no,
            dcm_no=dcm_no,
            title=row_text,
            source_url=f"{DART_REPORT_URL_PREFIX}{rcp_no}",
            is_revision="정정" in row_text,
        )
        reports[rcp_no] = report

    return sorted(reports.values(), key=lambda item: (item.filing_date, item.rcp_no))


def select_latest_dart_revisions(
    reports: Iterable[DartReport],
    *,
    target_quarters: set[str] | None = None,
) -> dict[str, DartReport]:
    """按报告季度选最终版本，修订报告按提交日和 RCP 编号取最新。"""
    selected: dict[str, DartReport] = {}
    for report in reports:
        if target_quarters is not None and report.report_quarter not in target_quarters:
            continue
        previous = selected.get(report.report_quarter)
        if previous is None or (report.filing_date, report.rcp_no) > (
            previous.filing_date,
            previous.rcp_no,
        ):
            selected[report.report_quarter] = report
    return selected


def parse_dart_toc_nodes(content: str | bytes) -> list[DartTocNode]:
    """从 ``dsaf001/main.do`` 的 JavaScript treeData 中提取文档节点。"""
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    nodes: list[DartTocNode] = []
    block_pattern = re.compile(
        r"var node\d+ = \{\};(?P<body>.*?)(?=\n\s*var node\d+ = \{\};|\n\s*treeData|\Z)",
        flags=re.DOTALL,
    )
    for match in block_pattern.finditer(text):
        body = match.group("body")

        def value(name: str, default: str = "", *, _body: str = body) -> str:
            found = re.search(
                rf"\['{re.escape(name)}'\]\s*=\s*(?:\"([^\"]*)\"|'([^']*)')",
                _body,
            )
            return (
                (found.group(1) if found and found.group(1) is not None else found.group(2))
                if found
                else default
            )

        node = DartTocNode(
            text=normalize_dart_text(value("text")),
            rcp_no=value("rcpNo"),
            dcm_no=value("dcmNo"),
            ele_id=value("eleId"),
            offset=value("offset"),
            length=value("length"),
            dtd=value("dtd", "dart4.xsd"),
            toc_no=value("tocNo"),
        )
        if node.text and node.rcp_no and node.dcm_no and node.ele_id:
            nodes.append(node)
    return nodes


def select_dart_toc_node(
    nodes: Iterable[DartTocNode],
    *selectors: str,
) -> DartTocNode:
    """按标题关键词选择一个 DART 文档节点，找不到时明确失败。"""
    candidates = list(nodes)
    for selector in selectors:
        normalized = normalize_dart_text(selector)
        for node in candidates:
            if normalized in node.text:
                return node
    raise ValueError(f"DART 文档目录未找到节点: {selectors}")


def build_dart_viewer_url(node: DartTocNode) -> str:
    """构造 DART report viewer 文档 URL。"""
    return (
        "https://dart.fss.or.kr/report/viewer.do"
        f"?rcpNo={node.rcp_no}&dcmNo={node.dcm_no}&eleId={node.ele_id}"
        f"&offset={node.offset}&length={node.length}&dtd={node.dtd}"
    )


def parse_samsung_inventory_html(content: str | bytes) -> SamsungInventoryFact:
    """解析三星 ``다. 재고자산 현황`` 的 DS 半导体和集团总库存。"""
    table = _find_section_table(content, "재고자산 현황")
    rows = _table_rows(table)
    ds_candidates: list[tuple[float, str]] = []
    group_candidates: list[float] = []
    for cells in rows:
        labels, values = _labels_and_numbers(cells)
        normalized = _compact("".join(labels))
        if not values or "소계" not in normalized:
            continue
        if "총계" in normalized or normalized.startswith("총"):
            group_candidates.append(values[0])
            continue
        # 2020–2021 的旧表也写作 ``DS 부문``，但仍把 ``반도체 사업`` 与
        # ``DP 사업`` 分开列示；只有 2022 起不再出现这两列时才是新 DS 口径。
        is_new_ds = "DS부문" in normalized and "반도체사업" not in normalized
        is_legacy_semiconductor = (
            "DS" in normalized
            and "반도체" in normalized
            and "DS계" not in normalized
            and "DP" not in normalized
        )
        if is_new_ds or is_legacy_semiconductor:
            scope = "ds_division" if is_new_ds else "legacy_semiconductor_business"
            ds_candidates.append((values[0], scope))

    if not ds_candidates or not group_candidates:
        raise ValueError("三星 DART 库存表未找到 DS 半导体小计和集团总计")
    inventory, scope = ds_candidates[0]
    group_inventory = group_candidates[0]
    if inventory <= 0 or group_inventory <= 0:
        raise ValueError("三星 DART 库存表的 DS/集团库存必须为正数")
    return SamsungInventoryFact(
        inventory_krw_million=inventory,
        group_inventory_krw_million=group_inventory,
        inventory_scope=scope,
    )


def parse_samsung_segment_html(content: str | bytes) -> SamsungSegmentFact:
    """解析三星 ``라. 사업부문별 요약 재무 현황`` 的 DS 累计数据。"""
    table = _find_section_table(content, "사업부문별 요약 재무 현황")
    rows = _table_rows(table)
    revenue: float | None = None
    operating_profit: float | None = None
    for cells in rows:
        labels, values = _labels_and_numbers(cells)
        normalized = _compact("".join(labels))
        is_ds_semiconductor = (
            "DS부문" in normalized and "반도체" in normalized and "DS계" not in normalized
        )
        is_ds_summary = (
            "DS부문" in normalized
            and "반도체" not in normalized
            and "DS계" not in normalized
            and "DS부문계" not in normalized
            and "DP" not in normalized
        )
        if not values or not (is_ds_semiconductor or is_ds_summary):
            continue
        if "매출액" in normalized or "총매출액" in normalized:
            revenue = values[0]
        elif "영업이익" in normalized:
            operating_profit = values[0]
    if revenue is None or operating_profit is None:
        raise ValueError("三星 DART 分部摘要未找到 DS 收入和营业利润")
    preceding_table = table.find_previous("table")
    unit_text = normalize_dart_text(
        preceding_table.get_text(" ", strip=True) if preceding_table is not None else ""
    )
    reported_unit = "hundred_million_krw" if "억원" in unit_text else "million_krw"
    multiplier = 100.0 if reported_unit == "hundred_million_krw" else 1.0
    return SamsungSegmentFact(
        ds_revenue_krw_million=revenue * multiplier,
        ds_operating_profit_krw_million=operating_profit * multiplier,
        reported_unit=reported_unit,
    )


def parse_skhynix_financial_html(content: str | bytes) -> SkHynixFinancialFact:
    """解析 SK 海力士合并财务报表的库存和营业成本。"""
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    soup = BeautifulSoup(text, "html.parser")
    inventory: float | None = None
    cost_values: list[float] | None = None
    for row in soup.find_all("tr"):
        cells = [
            normalize_dart_text(cell.get_text(" ", strip=True))
            for cell in row.find_all(["td", "th"])
        ]
        if not cells:
            continue
        normalized = "".join(cells)
        values = [_parse_number(cell) for cell in cells]
        numbers = [
            value for cell, value in zip(cells, values) if value is not None and "%" not in cell
        ]
        if "재고자산" in normalized and inventory is None and numbers:
            inventory = numbers[0]
        if "매출원가" in normalized and cost_values is None and numbers:
            cost_values = numbers
    if inventory is None or not cost_values:
        raise ValueError("SK 海力士 DART 合并报表未找到 재고자산/매출원가")
    return SkHynixFinancialFact(
        inventory_krw_million=inventory,
        cost_of_revenue_quarter_krw_million=cost_values[0],
        cost_of_revenue_cumulative_krw_million=cost_values[1] if len(cost_values) > 1 else None,
        cost_of_revenue_annual_krw_million=cost_values[0],
    )


def derive_quarterly_cumulative(
    cumulative: dict[str, float],
    existing_quarterly: dict[str, float] | None = None,
) -> dict[str, float]:
    """将三星报告中按季度年初累计的分部值差分为单季值。"""
    existing = existing_quarterly or {}
    result: dict[str, float] = dict(existing)
    for year in sorted({quarter[:4] for quarter in cumulative}):
        prior_sum = 0.0
        for quarter_number in range(1, 5):
            quarter = f"{year}Q{quarter_number}"
            if quarter in cumulative:
                value = cumulative[quarter] - prior_sum
                if value < 0:
                    raise ValueError(f"DART 累计值差分为负数: {quarter}={value}")
                result[quarter] = value
            elif quarter not in result:
                # 后续季度无法在缺少前置季度时安全差分，保留缺口而不是估算。
                continue
            prior_sum += result[quarter]
    return result


def _find_section_table(content: str | bytes, marker: str) -> Any:
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    soup = BeautifulSoup(content, "html.parser")
    heading = None
    for tag in soup.find_all(["p", "div", "td", "span"]):
        text = normalize_dart_text(tag.get_text(" ", strip=True))
        if (_compact(marker) in _compact(text) or marker in text) and len(text) <= 200:
            heading = tag
            break
    if heading is None:
        raise ValueError(f"DART HTML 未找到章节: {marker}")
    for table in heading.find_all_next("table"):
        if table.get("border") == "1" or table.find("thead") is not None:
            return table
    raise ValueError(f"DART 章节未找到表格: {marker}")


def _table_rows(table: Any) -> list[list[str]]:
    """展开 HTML rowspan/colspan，返回逻辑行。"""
    occupied: dict[tuple[int, int], str] = {}
    result: list[list[str]] = []
    for row_index, row in enumerate(table.find_all("tr")):
        cells = row.find_all(["td", "th"], recursive=False)
        if not cells:
            continue
        values: dict[int, str] = {}
        column = 0
        for cell in cells:
            while (row_index, column) in occupied:
                values[column] = occupied.pop((row_index, column))
                column += 1
            value = normalize_dart_text(cell.get_text(" ", strip=True))
            colspan = _span(cell.get("colspan"))
            rowspan = _span(cell.get("rowspan"))
            for offset in range(colspan):
                values[column + offset] = value
                for row_offset in range(1, rowspan):
                    occupied[(row_index + row_offset, column + offset)] = value
            column += colspan
        while (row_index, column) in occupied:
            values[column] = occupied.pop((row_index, column))
            column += 1
        result.append([values[index] for index in sorted(values)])
    return result


def _labels_and_numbers(cells: list[str]) -> tuple[list[str], list[float]]:
    labels: list[str] = []
    values: list[float] = []
    for cell in cells:
        number = _parse_number(cell)
        if number is None or "%" in cell or "회" in cell:
            if cell:
                labels.append(cell)
        else:
            values.append(number)
    return labels, values


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", normalize_dart_text(value))


def _parse_number(value: str) -> float | None:
    text = normalize_dart_text(value).replace(",", "")
    if not text or text in {"-", "–", "—"} or "%" in text or "회" in text:
        return None
    text = text.replace("△", "-")
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
        return None
    return float(text)


def _span(value: str | None) -> int:
    try:
        return max(1, int(value or "1"))
    except ValueError:
        return 1


def _parse_date(value: str) -> date:
    parts = [int(item) for item in re.split(r"[./-]", value)]
    return date(parts[0], parts[1], parts[2])


__all__ = [
    "DART_REPORT_URL_PREFIX",
    "DartReport",
    "DartTocNode",
    "SamsungInventoryFact",
    "SamsungSegmentFact",
    "SkHynixFinancialFact",
    "build_dart_viewer_url",
    "derive_quarterly_cumulative",
    "normalize_dart_text",
    "normalize_report_type",
    "parse_dart_search_results",
    "parse_dart_toc_nodes",
    "parse_report_quarter",
    "parse_samsung_inventory_html",
    "parse_samsung_segment_html",
    "parse_skhynix_financial_html",
    "select_dart_toc_node",
    "select_latest_dart_revisions",
]
