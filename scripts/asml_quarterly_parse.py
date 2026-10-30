"""ASML 季度财报新闻稿解析 v2：要点句优先 + 表格辅助 + 双源交叉验证。

要点句（bullet）跨年代一致，是本解析器主源：
  "Q2 net sales of €9.3 billion, gross margin of 54.0%, net income of €2.9 billion"
  "ASML expects Q3 2026 total net sales between €11.0B and €12.0B, and a gross margin between 55% and 57%"
表格（Figures in millions）辅助 IBM/units/backlog 与交叉验证 GM。

季度识别：要点句 "Q[N]" + 表格列头末列年份（最可靠）；其次正文年份。

输入：data/raw/industry/semiconductor/equipment/asml/sec_edgar/*.gz（RAW HTML 保真）
输出：data/curated/industry/semiconductor_equipment_gm.parquet

用法：uv run python scripts/asml_quarterly_parse.py
"""

from __future__ import annotations

import gzip
import logging
import re
from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.semiconductor.schemas import SEMICONDUCTOR_EQUIPMENT_GM_SCHEMA

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw/industry/semiconductor/equipment/asml/sec_edgar")
OUT = Path("data/curated/industry/semiconductor/equipment/semiconductor_equipment_gm.parquet")

SCHEMA = SEMICONDUCTOR_EQUIPMENT_GM_SCHEMA


def _read_gz(path: Path) -> str:
    with gzip.open(path, "rb") as f:
        raw = f.read()
    return re.sub(r"<[^>]+>", " ", raw.decode("utf-8", "ignore"))


_HTML_ENTITIES = {
    "&#32;": " ",
    "&#160;": " ",
    "&nbsp;": " ",
    "&#8226;": " . ",
    "&#8364;": "EUR ",
    "&amp;": "&",
    "&#39;": "'",
    "&#8211;": "-",
    "&#8212;": "-",
    "&#8220;": '"',
    "&#8221;": '"',
}


def _txt(s: str) -> str:
    for k, v in _HTML_ENTITIES.items():
        s = s.replace(k, v)
    s = s.replace("\u20ac", "EUR ").replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s)
    return s


def _qend(year: int, qn: int) -> date:
    return date(year, qn * 3, 28)


def _report_quarter_from_filing(release_date: date) -> tuple[str, date]:
    """ASML 财报节奏：1月发 Q4（上年）、4月发 Q1、7月发 Q2、10月发 Q3。"""
    m = release_date.month
    if m <= 1:
        qn, yr = 4, release_date.year - 1
    elif m <= 4:
        qn, yr = 1, release_date.year
    elif m <= 7:
        qn, yr = 2, release_date.year
    elif m <= 10:
        qn, yr = 3, release_date.year
    else:
        qn, yr = 4, release_date.year - 1
    return f"{yr}-Q{qn}", _qend(yr, qn)


def _parse_quarter(text: str, release_date: date) -> tuple[str, date]:
    """报告季度：优先按发布月推导（最可靠），要点句 Q[N] 交叉确认。"""
    q_by_filing, t_date = _report_quarter_from_filing(release_date)
    bullet_q = _bullet_q(text)
    if bullet_q and bullet_q != f"Q{q_by_filing[-1]}":
        # 极少数错位（如 2026-01-28 发布 Q4 2025 却在 1 月底），以要点句优先
        m = re.match(r"Q([1-4])", bullet_q)
        qn = int(m.group(1))
        yr = release_date.year if qn < 4 else release_date.year - 1
        return f"{yr}-Q{qn}", _qend(yr, qn)
    return q_by_filing, t_date


def _bullet_q(text: str) -> str | None:
    """要点句中的本季标识 Q[N]。"""
    m = re.search(r"\bQ([1-4])\s+(?:total\s+)?net sales\b", text, re.I)
    if not m:
        m = re.search(r"\bQ([1-4])\s+(?:total\s+)?net (?:sales|bookings)\b", text, re.I)
    return f"Q{m.group(1)}" if m else None


def _extract_net_sales_bullet(text: str) -> float | None:
    """要点句本季 net sales（EUR million）：'Q2 net sales of €9.3 billion'。"""
    m = re.search(
        r"\bQ([1-4])\s+(?:total\s+)?net sales\s+of\s+(?:EUR\s*)?([\d.]+)\s*billion",
        text,
        re.I,
    )
    if m:
        return float(m.group(2)) * 1000.0
    return None


def _extract_gm_bullet(text: str) -> float | None:
    """要点句本季 GM（%）：'gross margin of 54.0%' / 'gross margin 42.6 percent'。"""
    # 限制在要点句段落（Q[N] ... net income 区域），避免命中指引句
    m = re.search(
        r"\bQ([1-4])\s+.{0,200}?gross margin\s+(?:of\s+)?([\d.]+)\s*(?:%|percent)",
        text,
        re.I,
    )
    if m:
        return float(m.group(2))
    return None


def _extract_ni_bullet(text: str) -> float | None:
    m = re.search(
        r"\bQ([1-4])\s+.{0,220}?net income\s+(?:of\s+)?(?:EUR\s*)?([\d.]+)\s*billion",
        text,
        re.I,
    )
    if m:
        return float(m.group(2)) * 1000.0
    m = re.search(
        r"\bQ([1-4])\s+.{0,220}?net income\s+(?:of\s+)?(?:EUR\s*)?([\d.]+)\s*million",
        text,
        re.I,
    )
    if m:
        return float(m.group(2))
    return None


def _extract_bookings_bullet(text: str) -> float | None:
    """要点句本季 net bookings（EUR million）：'Q3 net bookings of €6.2 billion'。"""
    m = re.search(
        r"\b(?:Q([1-4])\s+)?(?:net bookings|Quarterly net bookings)(?:\s+in\s+Q([1-4]))?\s+of\s+(?:EUR\s*)?([\d.]+)\s*billion",
        text,
        re.I,
    )
    if m:
        return float(m.group(3)) * 1000.0
    return None


def _extract_gm_guidance(text: str) -> float | None:
    """下季 GM 指引（区间取中值）：'ASML expects Q3 2026 ... gross margin between 55% and 57%'。"""
    m = re.search(
        r"ASML\s+(?:expects|guides|now\s+expects)\s+Q[1-4].{0,240}?gross margin\s+"
        r"(?:of\s+|around\s+)?(?:between\s+)?([\d.]+)\s*%\s*and\s*([\d.]+)\s*%",
        text,
        re.I,
    )
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2.0
    m = re.search(
        r"ASML\s+(?:expects|guides|now\s+expects)\s+Q[1-4].{0,240}?gross margin\s+"
        r"(?:of\s+)?around\s+([\d.]+)\s*(?:%|percent)",
        text,
        re.I,
    )
    if m:
        return float(m.group(1))
    return None


def _extract_sales_guidance(text: str) -> float | None:
    """下季 net sales 指引（EUR million，区间取中值）。"""
    m = re.search(
        r"ASML\s+(?:expects|guides|now\s+expects)\s+Q[1-4].{0,240}?net sales\s+"
        r"(?:of\s+|at\s+approximately\s+|of\s+around\s+)?(?:between\s+)?(?:EUR\s*)?"
        r"([\d.]+)\s*billion\s*and\s*(?:EUR\s*)?([\d.]+)\s*billion",
        text,
        re.I,
    )
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2.0 * 1000.0
    m = re.search(
        r"ASML\s+(?:expects|guides|now\s+expects)\s+Q[1-4].{0,240}?net sales\s+"
        r"(?:at\s+approximately|of\s+around|of)\s+(?:EUR\s*)?([\d.]+)\s*billion",
        text,
        re.I,
    )
    if m:
        return float(m.group(1)) * 1000.0
    return None


def _table_row_value(
    label: str, table: str, report_quarter: str | None = None, last: bool = True
) -> float | None:
    """表格中按行标签取「报告季度列」的数值（列感知）。

    Q4 报告表头如 'Q3 2016 Q4 2016 FY 2015 FY 2016'，当前季=Q4 2016（第 2 列）；
    常规报告表头如 'Q2 2021 Q3 2021'，当前季=末列。传入 report_quarter（'2016-Q4'）
    时精确选列；否则默认取末列。
    """
    m = re.search(
        r"\b"
        + re.escape(label)
        + r"\s*(?:\([^)]*\))?\s*([\d,.\s]{2,80}?)(?=\s*(?:Q[1-4]\s+\d{4}|FY\s+\d{4}|[A-Z][a-z]|\u00a0|\([^)]*\)|$))",
        table,
    )
    if not m:
        # HTML 转纯文本后，部分表格行以 "...of which" 或其他标点连接下一行，
        # 原 lookahead 无法命中；此处只截取标签后的连续数字，仍保留列序。
        m = re.search(
            r"\b" + re.escape(label) + r"\s*(?:\([^)]*\))?\s*((?:\d[\d,]*(?:\.\d+)?\s+)+)",
            table,
        )
    if not m:
        return None
    nums = re.findall(r"[\d,]+\.?\d*", m.group(1))
    if not nums:
        return None
    vals = [float(n.replace(",", "")) for n in nums]
    if not vals:
        return None
    if report_quarter:
        # 从表头定位报告季度列：表头形如 'Q3 2016 Q4 2016 FY 2015 FY 2016'（'Q4 2016'=2016-Q4）
        mh = re.search(r"((?:Q[1-4]\s+\d{4}|FY\s+\d{4}|Q[1-4]\s+\d{4}\s*\d*)\s*)+", table)
        if mh:
            headers = re.findall(r"Q([1-4])\s+(\d{4})", mh.group(0))
            mq = re.match(r"(\d{4})-Q([1-4])$", report_quarter)
            if not mq:
                return vals[-1] if last else (vals[-2] if len(vals) >= 2 else vals[-1])
            target = (int(mq.group(2)), int(mq.group(1)))
            idx = None
            for i, (qn, yr) in enumerate(headers):
                if (int(qn), int(yr)) == target:
                    idx = i
                    break
            if idx is not None and idx < len(vals):
                return vals[idx]
    return vals[-1] if last else (vals[-2] if len(vals) >= 2 else vals[-1])


def _extract_table(text: str) -> str:
    ti = text.find("Figures in millions")
    if ti < 0:
        return ""
    return text[ti : ti + 5000]


def parse_one(path: Path, release_date: date, source_url: str) -> dict | None:
    raw = _read_gz(path)
    text = _txt(raw)
    table = _extract_table(text)

    report_quarter, t_date = _parse_quarter(text, release_date)

    # 本季列标签兼容：早期 'Net sales'，2024+ 'Total net sales'；'New systems' vs 'New lithography systems'
    net_sales_bullet = _extract_net_sales_bullet(text)
    gm_bullet = _extract_gm_bullet(text)
    ni_bullet = _extract_ni_bullet(text)
    nb_bullet = _extract_bookings_bullet(text)

    gm_table = _table_row_value("Gross margin (%)", table, report_quarter) or _table_row_value(
        "Gross margin", table, report_quarter
    )
    # 双源交叉验证 GM：要点句与表格应一致（偏差 > 1pp 告警）
    if gm_bullet and gm_table and abs(gm_bullet - gm_table) > 1.0:
        logger.warning("GM 双源不一致 [%s]: bullet=%.1f table=%.1f", path.name, gm_bullet, gm_table)
    gm = gm_bullet or gm_table

    # 表格提供百万欧元精度；新闻稿 bullet 只保留到十亿欧元一位小数。
    # 优先使用表格，避免 net_sales 与 gross_profit 的精度不一致而扭曲反推毛利率。
    net_sales_table = _table_row_value(
        "Total net sales", table, report_quarter
    ) or _table_row_value("Net sales", table, report_quarter)
    net_sales = net_sales_table or net_sales_bullet
    ni = ni_bullet or _table_row_value("Net income", table, report_quarter)
    ibm = _table_row_value("Installed Base Management sales", table, report_quarter)
    if ibm is None:
        ibm = _table_row_value(
            "service and field option sales", table, report_quarter
        )  # 2016 早期列名
    new_u = _table_row_value(
        "New lithography systems sold", table, report_quarter
    ) or _table_row_value("New systems sold", table, report_quarter)
    used_u = _table_row_value(
        "Used lithography systems sold", table, report_quarter
    ) or _table_row_value("Used systems sold", table, report_quarter)
    nb = nb_bullet or _table_row_value("Net bookings", table, report_quarter)
    backlog = _table_row_value("Systems backlog", table, report_quarter)
    gp = _table_row_value("Gross profit", table, report_quarter)

    gm_guide = _extract_gm_guidance(text)
    sales_guide = _extract_sales_guidance(text)

    return {
        "report_quarter": report_quarter,
        "trade_date": t_date,
        "net_sales_eur_m": round(net_sales, 1) if net_sales else None,
        "gross_profit_eur_m": gp,
        "gross_margin_pct": gm,
        "net_income_eur_m": ni,
        "ibm_sales_eur_m": ibm,
        "new_litho_units": new_u,
        "used_litho_units": used_u,
        "net_bookings_eur_m": nb,
        "systems_backlog_eur_m": backlog,
        "gm_guidance_next_pct": gm_guide,
        "net_sales_guidance_next_eur_m": sales_guide,
        "release_date": release_date,
        "source": "ASML_6K",
        "source_url": source_url,
        "data_status": "actual",
        "collected_at": "",
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    records: list[dict] = []
    files = sorted(RAW_DIR.glob("*.gz"))
    for path in files:
        m = re.match(r"(\d{4}-\d{2}-\d{2})__", path.name)
        if not m:
            continue
        rel = date.fromisoformat(m.group(1))
        rec = parse_one(path, rel, "https://www.sec.gov/edgar/")
        if rec:
            records.append(rec)
    if not records:
        logger.error("无解析结果")
        return
    df = (
        pl.DataFrame(records, schema=SCHEMA)
        .unique(subset=["report_quarter"], keep="last")
        .sort("trade_date")
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(OUT)
    show = df.select(
        [
            "report_quarter",
            "trade_date",
            "net_sales_eur_m",
            "gross_margin_pct",
            "ibm_sales_eur_m",
            "new_litho_units",
            "net_bookings_eur_m",
            "systems_backlog_eur_m",
            "gm_guidance_next_pct",
            "net_sales_guidance_next_eur_m",
            "release_date",
        ]
    )
    print(show)
    print(f"\n已写入: {OUT}  ({len(df)} 季度)")
    # 完整性摘要
    print("\n=== 字段覆盖 ===")
    for c in [
        "gross_margin_pct",
        "net_sales_eur_m",
        "ibm_sales_eur_m",
        "new_litho_units",
        "net_bookings_eur_m",
        "gm_guidance_next_pct",
    ]:
        n = df[c].is_not_null().sum()
        print(f"{c}: {n}/{len(df)}")


if __name__ == "__main__":
    main()
