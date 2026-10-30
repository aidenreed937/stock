"""半导体设备四巨头季度财报解析（8-K 新闻稿 GM/指引 + 10-Q XBRL 交叉验证与兜底）。

Stage 2（GM 前瞻腿四巨头扩样）：解析 AMAT/LRCX/KLAC 的 SEC EDGAR 财报，输出跨公司
季度黄金表（company 维度），供跨公司合成 gm_leading_score。

数据源分工：
- 8-K 新闻稿：GM 实际值（AMAT/LRCX 全期；KLAC 2021+）、下季 GM 指引（LRCX/KLAC）、
  服务收入占比（分部表）
- 10-Q XBRL：GM 实际值兜底（KLAC 2018-2020 新闻稿无 GM）+ 交叉验证 + 服务收入拆分

字段口径（release_date = 8-K/10-Q filingDate，无前视）：
- gross_margin_pct：非GAAP GM（新闻稿要点句）；缺失时用 10-Q XBRL GAAP GM 兜底
- gm_guidance_next_pct：下季 GM 指引区间取中值（新闻稿 guidance 段）
- services_share_pct：服务/售后收入占净销售额（分部表，跨公司口径尽量一致）
- 财季识别：从新闻稿标题/指引段提取财季号 + 财年 → report_quarter（各公司自身财季）；
  解析失败时按 8-K 发布月 + 财年历兜底（`_NEWS_QUARTER_FALLBACK`），避免财年末 Q4
  新闻稿因"年份挂在 Fiscal Year 上"而丢失季度标签

TEL（Tokyo Electron，日股）不在 EDGAR，由 `scripts/tel_quarterly_parse.py` 从日文 tanshin PDF
独立解析到 `tel_gm_quarterly.parquet`，再由本脚本投影合并进本表（见 `load_tel_rows`）。
**注意**：本表的 TEL 行来自该独立黄金表，重跑本脚本必须一并合并，否则会用 3 家覆盖掉 TEL。

用法：uv run python scripts/equipment_giants_parse.py
"""

from __future__ import annotations

import gzip
import logging
import re
from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.semiconductor.schemas import (
    SEMICONDUCTOR_EQUIPMENT_GM_MULTI_SCHEMA,
)

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw/industry/semiconductor/equipment/sec_edgar")
TEL_QUARTERLY = Path("data/curated/industry/semiconductor/equipment/tel_gm_quarterly.parquet")
OUT = Path("data/curated/industry/semiconductor/equipment/semiconductor_equipment_gm_multi.parquet")

GIANTS = ["AMAT", "LRCX", "KLAC"]


def load_tel_rows() -> list[dict]:
    """把 TEL 独立黄金表投影到本表 8 列 schema。

    TEL 不在 SEC EDGAR，由 `scripts/tel_quarterly_parse.py` 从日文 tanshin PDF 解析到
    `tel_gm_quarterly.parquet`；其字段（fiscal_year / fy_q / period_end / net_sales_jpy_m 等）
    不进入本表，只保留跨公司可比列。
    """
    if not TEL_QUARTERLY.exists():
        logger.warning("缺少 TEL 黄金表 %s，本轮不合并 TEL", TEL_QUARTERLY)
        return []
    tel = pl.read_parquet(TEL_QUARTERLY)
    return [
        {
            "company": "TEL",
            "report_quarter": row["report_quarter"],
            "release_date": row["release_date"],
            "gross_margin_pct": row["gross_margin_pct"],
            "gm_guidance_next_pct": None,
            "services_share_pct": None,
            "source": "TEL_IR",
            "data_status": "actual",
        }
        for row in tel.select(["report_quarter", "release_date", "gross_margin_pct"]).to_dicts()
    ]


_HTML_ENTITIES = {
    "&#32;": " ",
    "&#160;": " ",
    "&nbsp;": " ",
    "&#8226;": " . ",
    "&#8220;": '"',
    "&#8221;": '"',
    "&#8211;": "-",
    "&#8212;": "-",
    "&#39;": "'",
    "&amp;": "&",
    "&#163;": "GBP ",
    "&#165;": "JPY ",
    "&#47;": "/",
    "&#58;": ":",
    "&#59;": ";",
    "&#64;": "@",
    "&#8217;": "'",
}


def _txt(s: str) -> str:
    for k, v in _HTML_ENTITIES.items():
        s = s.replace(k, v)
    s = re.sub(r"\s+", " ", s)
    return s


def _read_gz(path: Path) -> str:
    with gzip.open(path, "rb") as f:
        raw = f.read()
    return _txt(re.sub(r"<[^>]+>", " ", raw.decode("utf-8", "ignore")))


# ---------------------------------------------------------------------------
# 8-K 新闻稿提取
# ---------------------------------------------------------------------------


def _news_gm(s: str) -> float | None:
    """本季 GM（非GAAP 优先；不同年代措辞兜底）。返回百分比数值。"""
    # 1. 非GAAP 明确式：'non-GAAP gross margin 50.0 percent' / 'as a percent of revenue of 49.9%'
    m = re.search(
        r"non-?GAAP\s+gross margin\s+(?:as a percent of revenue\s+)?(?:of\s+)?([\d.]+)\s*(?:%|percent)",
        s,
        re.I,
    )
    if m:
        return float(m.group(1))
    # 2. 'GAAP gross margin X percent and non-GAAP gross margin Y percent'（AMAT 要点句）
    m = re.search(
        r"GAAP gross margin\s+([\d.]+)\s*percent\s+and\s+non-GAAP gross margin\s+([\d.]+)\s*percent",
        s,
        re.I,
    )
    if m:
        return float(m.group(2))
    # 3. 非GAAP points 措辞：'on a non-GAAP adjusted basis, gross margin grew 3.6 points to 46.3 percent'
    m = re.search(
        r"non-?GAAP[^.]{0,80}?gross margin\s+(?:grew|increased|expanded)\s+[\d.]+\s+points\s+to\s+([\d.]+)\s*percent",
        s,
        re.I,
    )
    if m:
        return float(m.group(1))
    # 4. GAAP points 措辞：'increased gross margin by 1.6 points to 45.7 percent'（AMAT 2018）
    m = re.search(
        r"gross margin\s+(?:grew|increased|expanded)\s+[\d.]+\s+points\s+to\s+([\d.]+)\s*percent",
        s,
        re.I,
    )
    if m:
        return float(m.group(1))
    # 5. 表格：'Gross margin X % Y % ...'（首列=本季；Q4 财报多列，取首列）
    m = re.search(r"Gross margin\s+([\d.]+)\s*%\s+", s)
    if m:
        return float(m.group(1))
    return None


def _news_gm_guidance(s: str) -> float | None:
    """下季 GM 指引（区间下沿即典型值）：
    - LRCX: 'Gross margin as a percentage of revenue 45.1% +/- 1%'
    - KLAC: 'gross margin is expected to be in a range of 60.72% + - 1.00%'
    - 最新 LRCX: 'Gross margin 52.0% +/- 1%'
    """
    m = re.search(
        r"gross margin\s+(?:as a percentage of revenue\s+)?(?:is expected to be in a range of\s+)?"
        r"([\d.]+)\s*%\s*[+]\s*(?:/)?\s*[-]?\s*([\d.]+)\s*%",
        s,
        re.I,
    )
    if m:
        return float(m.group(1))
    return None


def _news_services_share(s: str, ticker: str) -> float | None:
    """服务收入占净销售额（分部表）。返回占比或 None。"""
    if ticker == "LRCX":
        # 'Systems revenue $ X ... Customer support-related revenue and other Y ... Z total'
        m = re.search(
            r"Customer support-related revenue and other\s+\$?\s*([\d,]+).{0,40}?\$?\s*([\d,]+)\s*\$?\s*[\d,]+\s*$",
            s,
            re.I | re.M,
        )
        # 更稳：Systems revenue 与 Customer support 都在同一表，直接找两个数
        m = re.search(
            r"Systems revenue\s+\$?\s*([\d,]+)[\s\S]{0,200}?Customer support-related revenue and other\s+\$?\s*([\d,]+)",
            s,
            re.I,
        )
        if m:
            sys_r, cust_r = float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
            return cust_r / (sys_r + cust_r) * 100.0
        return None
    if ticker == "AMAT":
        # 分部表：'Applied Global Services' 后接财季列，下一行 'Net sales $ X' / 'Net revenue $ X'
        m = re.search(
            r"Applied Global Services\s+(?:Q[1-4]\s+FY\s?\d{4}\s*)+\(in millions[^)]*\)\s*(?:Net sales|Net revenue|Revenue)\s+\$\s*([\d,]+)",
            s,
            re.I,
        )
        if not m:
            # 宽松：'Applied Global Services' 后 400 字符内 'Net sales $' / 'Net revenue $'
            m = re.search(
                r"Applied Global Services.{0,400}?(?:Net sales|Net revenue|Revenue)\s+\$\s*([\d,]+)",
                s,
                re.I | re.S,
            )
        if not m:
            return None
        services = float(m.group(1).replace(",", ""))
        # 顶部合计营收：优先 'Quarterly revenue $X billion'（Q4 财报顶部先报全年），
        # 再 'Record revenue $X billion'（非 Q4），再 'Total revenue $' 表内值。
        m2 = re.search(
            r"Quarterly\s+(?:revenue|net revenue|net sales)\s+(?:of\s+)?\$?\s*([\d.]+)\s*billion",
            s,
            re.I,
        )
        if not m2:
            m2 = re.search(
                r"(?:Record\s+)?(?:revenue|net revenue|net sales)\s+(?:of\s+)?\$?\s*([\d.]+)\s*billion",
                s,
                re.I,
            )
        if m2:
            total = float(m2.group(1)) * 1000.0
        else:
            m2 = re.search(r"Total revenue\s+\$?\s*([\d,]+)", s, re.I)
            if not m2:
                return None
            total = float(m2.group(1).replace(",", ""))
        return services / total * 100.0 if total else None
    # KLAC：无服务/产品拆分，返回 None
    return None


def _news_quarter(s: str, ticker: str, filing_date: str) -> str | None:
    """财季识别：返回各公司自身财季 'YYYY-QN'。

    - AMAT：标题 'THIRD QUARTER 2026' 或指引 'for the fourth quarter of fiscal 2026'
    - KLAC：标题 'FISCAL 2026 FOURTH QUARTER AND FULL YEAR RESULTS'（注意财季在前、财年在前）
    - LRCX：正文 'the quarter ended June 28, 2026'（按季度末日期推导财季）
    """
    if ticker in ("AMAT", "KLAC"):
        # 标题/指引段：'THIRD QUARTER 2026' / 'FISCAL 2026 FOURTH QUARTER' / 'for the fourth quarter of fiscal 2026'
        m = re.search(
            r"(?:for the\s+)?(?:fiscal\s+\d{4}\s+)?(?:first|second|third|fourth|[1-4])(?:st|nd|rd|th)?\s+quarter"
            r"(?:\s+of\s+)?(?:\s+)?(?:fiscal\s+)?(?:\d{4})?",
            s,
            re.I,
        )
        if not m:
            m = re.search(
                r"(?:first|second|third|fourth|[1-4])(?:st|nd|rd|th)?\s+quarter\s+of\s+(?:fiscal\s+)?(\d{4})",
                s,
                re.I,
            )
        if not m:
            return None
        word = m.group(0).lower()
        ord_map = {"first": 1, "second": 2, "third": 3, "fourth": 4, "1": 1, "2": 2, "3": 3, "4": 4}
        qn = None
        for k, v in ord_map.items():
            if k in word:
                qn = v
                break
        if qn is None:
            return None
        ym = re.search(r"(\d{4})", word)
        year = int(ym.group(1)) if ym else None
        if year is None:
            return None
        # AMAT 财年 10 月末：FY2026 Q1 报告期 2025-11 ~ 2026-01，标题 'first quarter 2026' 即 FY2026-Q1；
        # KLAC 财年 6 月末：'FISCAL 2026 SECOND QUARTER' = FY2026-Q2。
        return f"{year}-Q{qn}"
    # LRCX：'the quarter ended June 28, 2026' → 财季推导（财年末 6 月末）
    m = re.search(r"quarter ended\s+([A-Za-z]+)\s+\d{1,2},?\s+(\d{4})", s)
    if not m:
        m = re.search(r"the\s+([A-Za-z]+)\s+\d{4}\s+quarter", s)
        if m:
            # 'the June 2026 quarter' → 6月 = Q4
            month = m.group(1)
            year = int(m.group(2))
            qn = {
                "sep": 1,
                "oct": 2,
                "nov": 2,
                "dec": 2,
                "jan": 3,
                "feb": 3,
                "mar": 3,
                "apr": 4,
                "may": 4,
                "jun": 4,
            }.get(month[:3].lower())
            return f"{year}-Q{qn}" if qn else None
        return None
    month = m.group(1)
    year = int(m.group(2))
    # LRCX 财年末 6 月末：7-9月=Q1, 10-12月=Q2, 1-3月=Q3, 4-6月=Q4
    qn = {
        "jul": 1,
        "aug": 1,
        "sep": 1,
        "oct": 2,
        "nov": 2,
        "dec": 2,
        "jan": 3,
        "feb": 3,
        "mar": 3,
        "apr": 4,
        "may": 4,
        "jun": 4,
    }.get(month[:3].lower())
    return f"{year}-Q{qn}" if qn else None


#: 8-K 发布月 → 财季兜底映射（仅在标题/正文解析不出财季时使用）。
#:
#: 值 = (财季号, 年份修正量)；财季标签的年份取"**季末所在公历年**"，因此跨年财季
#: 需要 -1 修正。各公司财年历：
#: - AMAT 财年末 10 月末：2 月发 Q1 / 5 月发 Q2 / 8 月发 Q3 / 11 月发 Q4（季末与发布同年）
#: - KLAC / LRCX 财年末 6 月末：10-11 月发 Q1 / 1-2 月发 Q2 / 4-5 月发 Q3 / 7-8 月发 Q4
#:   其中 Q2 的季末在 12 月（上一年），故发布月为次年 1-2 月时年份需 -1
_NEWS_QUARTER_FALLBACK: dict[str, dict[int, tuple[int, int]]] = {
    "AMAT": {2: (1, 0), 5: (2, 0), 8: (3, 0), 11: (4, 0)},
    "KLAC": {
        10: (1, 0),
        11: (1, 0),
        1: (2, -1),
        2: (2, -1),
        4: (3, 0),
        5: (3, 0),
        7: (4, 0),
        8: (4, 0),
    },
    "LRCX": {
        10: (1, 0),
        11: (1, 0),
        1: (2, -1),
        2: (2, -1),
        4: (3, 0),
        5: (3, 0),
        7: (4, 0),
        8: (4, 0),
    },
}


def _news_quarter_fallback(ticker: str, filing: str) -> str | None:
    """财季兜底：按 8-K 发布月与该公司的财年历反推 `'YYYY-QN'`。

    用于 `_news_quarter` 解析失败的场景。典型是财年末 Q4 新闻稿标题写作
    "Fourth Quarter and Fiscal Year 2025 Results"——年份挂在 "Fiscal Year" 上
    而非 "fourth quarter" 之后，正则取不到年份便返回 None，最终 report_quarter 为空。
    """
    parts = filing[:7].split("-")
    if len(parts) != 2:
        return None
    try:
        year, month = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    mapped = _NEWS_QUARTER_FALLBACK.get(ticker, {}).get(month)
    if mapped is None:
        return None
    quarter, year_shift = mapped
    return f"{year + year_shift}-Q{quarter}"


# ---------------------------------------------------------------------------
# 10-Q XBRL 提取（GM 兜底 + 服务收入拆分 + 交叉验证）
# ---------------------------------------------------------------------------


def _xbrl_extract(raw: str, tag: str) -> list[tuple[str, float]]:
    """提取 ix:nonFraction 中指定 tag 的 (contextRef, value)。精确匹配 tag 末段（防
    'CostOfRevenue' 误命中 'CostOfRevenueAndOperatingExpense' 之类前缀相同的标签）。"""
    out = []
    pat = re.compile(r"<ix:nonFraction\b[^>]*>([\d,]+)</ix:nonFraction>")
    for m in pat.finditer(raw):
        full = m.group(0)
        nm = re.search(r'name="([^"]+)"', full)
        cr = re.search(r'contextRef="([^"]+)"', full)
        if nm and cr and nm.group(1).split(":")[-1] == tag:
            out.append((cr.group(1), float(m.group(1).replace(",", ""))))
    return out


def _xbrl_contexts(raw: str) -> dict[str, tuple[str, bool]]:
    """解析 ix:header context：id -> (endDate, has_segment)。"""
    ctx: dict[str, tuple[str, bool]] = {}
    h = raw.find("<ix:header")
    if h < 0:
        return ctx
    he = raw.find("</ix:header>")
    seg = raw[h : he if he > 0 else h + 120000]
    for cm in re.finditer(r'<xbrli:context[^>]*id="([^"]+)"[^>]*>(.*?)</xbrli:context>', seg, re.S):
        cid, body = cm.group(1), cm.group(2)
        end = re.search(r"<xbrli:endDate>(\d{4}-\d{2}-\d{2})</xbrli:endDate>", body)
        ctx[cid] = (end.group(1) if end else None, "<xbrli:segment>" in body)
    return ctx


def _fiscal_quarter_from_end(end_date: str, ticker: str) -> str | None:
    """按各公司财年历，从期间结束日推导财季 'YYYY-QN'。

    - AMAT：财年末 10 月末。Q1=11-1月, Q2=2-4月, Q3=5-7月, Q4=8-10月
    - LRCX/KLAC：财年末 6 月末。Q1=7-9月, Q2=10-12月, Q3=1-3月, Q4=4-6月
    """
    m = re.match(r"(\d{4})-(\d{2})-\d{2}", end_date)
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if ticker == "AMAT":
        qn = {11: 1, 12: 1, 1: 1, 2: 2, 3: 2, 4: 2, 5: 3, 6: 3, 7: 3, 8: 4, 9: 4, 10: 4}[month]
    else:
        qn = {7: 1, 8: 1, 9: 1, 10: 2, 11: 2, 12: 2, 1: 3, 2: 3, 3: 3, 4: 4, 5: 4, 6: 4}[month]
    # 财季跨年：Q1-Q3 的季末月在同一年（LRCX Q3=3月 → 2026-Q3），Q4=6月 → 2026-Q4；
    # AMAT Q1 季末 1 月 → 2026-Q1（若月份为 1 且财季 Q1 则用当年）
    return f"{year}-Q{qn}"


def _single_quarter_gm_and_end(raw: str) -> tuple[float | None, str | None]:
    """10-Q XBRL 提取本季 GAAP GM% + 本季结束日。返回 (gm_pct, end_date)。"""
    ctx = _xbrl_contexts(raw)
    revs = _xbrl_extract(raw, "RevenueFromContractWithCustomerExcludingAssessedTax")
    costs = _xbrl_extract(raw, "CostOfRevenue")
    if not revs or not costs:
        return None, None
    nos = {c: v for c, v in ctx.items() if not v[1] and v[0]}
    latest_end = max((v[0] for v in nos.values()), default=None)
    if not latest_end:
        return None, None
    cand = {c for c, v in nos.items() if v[0] == latest_end}
    rev_map = dict(revs)
    cost_map = dict(costs)
    best = None
    for c in cand:
        if c in rev_map and c in cost_map:
            if best is None or rev_map[c] < rev_map[best]:
                best = c
    if best is None:
        return None, None
    r, co = rev_map[best], cost_map[best]
    return ((r - co) / r * 100.0 if r else None), latest_end


def _xbrl_services_share(raw: str, ticker: str) -> float | None:
    """10-Q XBRL 服务收入占比（AMAT/LRCX 有服务标签；KLAC 无→None）。"""
    ctx = _xbrl_contexts(raw)
    nos = {c: v for c, v in ctx.items() if not v[1] and v[0]}
    latest_end = max((v[0] for v in nos.values()), default=None)
    if not latest_end:
        return None
    cand = {c for c, v in nos.items() if v[0] == latest_end}
    rev_map = dict(_xbrl_extract(raw, "RevenueFromContractWithCustomerExcludingAssessedTax"))
    total_rev = min((rev_map[c] for c in cand if c in rev_map), default=None)
    if total_rev is None:
        return None
    # 各家服务收入 tag
    service_tags = {
        "AMAT": ["amat:AppliedGlobalServicesRevenue", "ServicesRevenue"],
        "LRCX": ["lrcx:CustomerSupportRevenue", "CustomerSupportRelatedRevenue"],
        "KLAC": ["ServicesRevenue"],
    }
    serv_rev = None
    for tag in service_tags.get(ticker, []):
        rows = _xbrl_extract(raw, tag)
        vals = [v for c, v in rows if c in cand]
        if vals:
            serv_rev = min(vals)
            break
    if serv_rev is None:
        return None
    return serv_rev / total_rev * 100.0 if total_rev else None


def _legacy_10q_gm(raw: str) -> float | None:
    """老式 10-Q（无 XBRL）文本损益表 GM：'Total revenues X ... Costs of revenues Y'（首列=本季）。"""
    s = _txt(re.sub(r"<[^>]+>", " ", raw))
    m = re.search(r"Total revenues\s+\$?\s*([\d,]+)", s)
    if not m:
        return None
    rev = float(m.group(1).replace(",", ""))
    mc = re.search(r"Costs? of revenues?\s+\$?\s*([\d,]+)", s)
    if not mc:
        return None
    cost = float(mc.group(1).replace(",", ""))
    return (rev - cost) / rev * 100.0 if rev else None


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def parse_company(ticker: str, raw_dir: Path | None = None) -> list[dict]:
    """解析单家公司：8-K 新闻稿为主，10-Q XBRL 兜底/交叉验证。"""
    comp_dir = (raw_dir or RAW_DIR) / ticker
    files = sorted(comp_dir.glob(f"{ticker}__*.gz"))
    news_files = [f for f in files if "_10Q_" not in f.name]
    q10_files = [f for f in files if "_10Q_" in f.name]
    rows: dict[str, dict] = {}  # report_quarter -> row

    news_gm_fallback: dict[str, float | None] = {}
    for nf in news_files:
        s = _read_gz(nf)
        filing = nf.name.split("__")[1]
        gm = _news_gm(s)
        guid = _news_gm_guidance(s)
        serv = _news_services_share(s, ticker)
        q = _news_quarter(s, ticker, filing) or _news_quarter_fallback(ticker, filing)
        # 占位文件（内容过短、无指引无服务）跳过
        if guid is None and serv is None and len(s) < 6000:
            logger.debug("占位文件跳过 [%s %s]", ticker, nf.name)
            continue
        key = q or filing[:7]
        row = rows.setdefault(
            key,
            {
                "company": ticker,
                "report_quarter": q,
                "release_date": date.fromisoformat(filing),
                "gross_margin_pct": None,  # GM 以 10-Q 为准（权威实际值），新闻稿仅兜底
                "gm_guidance_next_pct": guid,
                "services_share_pct": serv,
                "source": "8-K",
                "data_status": "actual",
            },
        )
        if guid is not None:
            row["gm_guidance_next_pct"] = guid
        if serv is not None:
            row["services_share_pct"] = serv
        news_gm_fallback[key] = gm

    # 10-Q XBRL 兜底 GM（新闻稿缺 GM 的季度）+ 服务占比。
    # 匹配策略：10-Q 与新闻稿同一季度，filing 日期相邻（10-Q 晚 2-6 周）。
    # 用 release_date 邻近匹配（±60 天内最近者），避免财年/日历标签错位导致的合并失败。
    news_dates = sorted((r["release_date"], k) for k, r in rows.items() if r["release_date"])
    import bisect

    for qf in q10_files:
        with gzip.open(qf, "rb") as f:
            raw = f.read().decode("utf-8", "ignore")
        filing = qf.name.split("__")[1]
        fd = date.fromisoformat(filing)
        gm, end_date = _single_quarter_gm_and_end(raw)
        if gm is None:
            # 老式 10-Q 无 XBRL：文本损益表兜底（KLAC 2016-2019）
            gm = _legacy_10q_gm(raw)
        serv = _xbrl_services_share(raw, ticker)
        if gm is None and serv is None:
            continue
        # 找最近新闻稿行
        if not news_dates:
            continue
        ds = [d for d, _ in news_dates]
        pos = bisect.bisect_left(ds, fd)
        best_key, best_gap = None, None
        for p in (pos - 1, pos):
            if 0 <= p < len(news_dates):
                gap = abs((news_dates[p][0] - fd).days)
                if best_key is None or gap < best_gap:
                    best_key, best_gap = news_dates[p][1], gap
        if best_key is None or best_gap > 60:
            # 无邻近新闻稿行：新起一行
            rows.setdefault(
                f"{filing[:4]}-10Q",
                {
                    "company": ticker,
                    "report_quarter": _fiscal_quarter_from_end(end_date, ticker)
                    if end_date
                    else _news_quarter_fallback(ticker, filing),
                    "release_date": fd,
                    "gross_margin_pct": gm,
                    "gm_guidance_next_pct": None,
                    "services_share_pct": serv,
                    "source": "10-Q",
                    "data_status": "actual",
                },
            )
            continue
        row = rows[best_key]
        if row.get("gross_margin_pct") is None and gm is not None:
            row["gross_margin_pct"] = gm
            row["data_status"] = "actual_10q"
        if row.get("services_share_pct") is None and serv is not None:
            row["services_share_pct"] = serv

    # 新闻稿 GM 兜底：10-Q 未覆盖的季度（财年末 Q4 无 10-Q 只有 10-K）
    for key, gm in news_gm_fallback.items():
        if key in rows and gm is not None and rows[key].get("gross_margin_pct") is None:
            rows[key]["gross_margin_pct"] = gm

    return list(rows.values())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    all_rows: list[dict] = []
    for t in GIANTS:
        rows = parse_company(t)
        logger.info("%s: 解析 %d 个记录", t, len(rows))
        all_rows.extend(rows)
    tel_rows = load_tel_rows()
    logger.info("TEL: 合并 %d 个记录（来自 tel_gm_quarterly）", len(tel_rows))
    all_rows.extend(tel_rows)
    df = pl.DataFrame(all_rows).cast(SEMICONDUCTOR_EQUIPMENT_GM_MULTI_SCHEMA)
    df.write_parquet(OUT)
    print(f"已写出 {OUT}（{df.height} 行）")
    print(
        df.select(
            [
                "company",
                "report_quarter",
                "release_date",
                "gross_margin_pct",
                "gm_guidance_next_pct",
                "services_share_pct",
            ]
        ).head(20)
    )


if __name__ == "__main__":
    main()
