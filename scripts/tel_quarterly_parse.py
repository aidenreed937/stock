"""Tokyo Electron (TEL) 季度财报解析：tanshin PDF → 单季 GM 黄金表。

日本 GAAP 口径（诚实标注，与美系三家不同）：
- tanshin 损益表是**累计口径**（Q1=3个月 / Q2=半年 / Q3=9个月 / Q4=全年），单季 GM 需差分；
- 无下季 GM 指引（只给 net sales/operating income 预测）→ guidance/expansion 腿不可得；
- 无服务/产品拆分 → ibm 腿不可得。
=> TEL 仅能贡献「GM 实际值水平」腿（gm_level），不进入 gm_leading 前瞻复合。

输出：data/curated/industry/tel_gm_quarterly.parquet（company=TEL，单季 GM，release_date 无前视）

用法：uv run --with pypdf python scripts/tel_quarterly_parse.py
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.semiconductor.schemas import TEL_GM_QUARTERLY_SCHEMA

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw/industry/semiconductor/equipment/tel/ir_tanshin")
OUT = Path("data/curated/industry/semiconductor/equipment/tel_gm_quarterly.parquet")

# tanshin 文件名 → 财季（FY 以报告期结束年为主键，Q1=Jun/Q2=Sep/Q3=Dec/Q4=Mar）
# 文件名如 fy26q1 / fy23q4 / 49q3 / 48Q4
_FYQ_RE = re.compile(r"(?:fy)?(\d{2})(?:Q|q)([1-4])")


def _parse_fyq(filename: str) -> tuple[int, int] | None:
    """文件名 → (财年号, 季度)。财年号映射：49=2011 财年结束年（March 31, 2012 的报告 = 49Q4）。
    为简化，返回 (报告期结束年, 季度)：q1→2025(6月), q2→2025(9月), q3→2025(12月), q4→2026(3月)。
    实际以 PDF 内文提取的期间结束日为准，文件名仅作候选。
    """
    m = _FYQ_RE.search(filename)
    if not m:
        return None
    return None  # 直接用 PDF 内文，文件名仅辅助


def _extract_period_and_income(text: str, filename: str = "") -> tuple[str | None, str | None]:
    """提取当期净销售额/销售成本。
    列序统一为 [上年同期, 上年同比%, 当期, 当期同比%]（或旧格式 [上年, 当期]）——**当期 = 末金额**。
    已用官方年度锚点验证：FY2024=1,830,527 / FY2025=2,431,568 / FY2026=2,443,533 均为末金额。
    """

    def _amounts(label: str) -> list[float]:
        # 优先损益表区块：Net sales 后 1 行内出现 Cost of sales（排除摘要行含预测值）
        m = re.search(
            re.escape(label) + r"\s+([\d,]+[\d, .]*)\s+(?:Cost of sales)\s+[\d,]+",
            text,
        )
        if m:
            return [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]+", m.group(1))]
        m = re.search(re.escape(label) + r"\s*\(Millions of yen\)\s+([^\n]+)", text)
        if not m:
            # 旧格式无单位后缀：裸 'Cost of sales 410,277 370,351'
            m = re.search(re.escape(label) + r"\s+([\d,]+[\d, .]*)", text)
        if not m:
            return []
        raw = m.group(1)
        # 提取所有金额（千分位逗号或纯数字），过滤百分数/同比（<1000 且带 % 或括号）
        out = []
        for x in re.findall(r"\(?([\d,]+\.?\d*)\)?", raw):
            v = float(x.replace(",", ""))
            if v > 1000:  # TEL 季度净销售亿级；同比% <1000
                out.append(v)
        return out

    ns_vals = _amounts("Net sales")
    cs_vals = _amounts("Cost of sales")
    if not ns_vals or not cs_vals:
        return None, None
    # 当期 = 末金额（[上年, 上年同比, 当期, 当期同比]）
    return str(ns_vals[-1]), str(cs_vals[-1])


def _extract_end_date(text: str) -> str | None:
    """期间结束日：'Six months ended September 30, 2025' → '2025-09-30'。"""
    m = re.search(
        r"(?:Three|Six|Nine)\s+months\s+ended\s+([A-Za-z]+)\s+\d{1,2},?\s+(\d{4})",
        text,
    )
    if not m:
        m = re.search(r"Year\s+ended\s+([A-Za-z]+)\s+\d{1,2},?\s+(\d{4})", text)
    if not m:
        m = re.search(r"ended\s+([A-Za-z]+)\s+\d{1,2},?\s+(\d{4})", text)
    if not m:
        return None
    month, year = m.group(1), int(m.group(2))
    mm = {
        "January": 1,
        "February": 2,
        "March": 3,
        "April": 4,
        "May": 5,
        "June": 6,
        "July": 7,
        "August": 8,
        "September": 9,
        "October": 10,
        "November": 11,
        "December": 12,
    }
    mnum = mm.get(month)
    if not mnum:
        return None
    return f"{year}-{mnum:02d}-{30 if mnum != 2 else 28}"


def _extract_release_date(text: str) -> str | None:
    """发布日：首页第 2 行（'TOKYO ELECTRON' 后的日期），如 'July 28, 2015'。
    该日期即财报发布日（无前视），比手写 IR 日历表更可靠、覆盖全。
    """
    m = re.search(
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2},?\s+\d{4}",
        text[:600],
    )
    if not m:
        return None
    month, day, year = m.group(0).split()
    mm = {
        "January": 1,
        "February": 2,
        "March": 3,
        "April": 4,
        "May": 5,
        "June": 6,
        "July": 7,
        "August": 8,
        "September": 9,
        "October": 10,
        "November": 11,
        "December": 12,
    }
    mnum = mm.get(month)
    if not mnum:
        return None
    dnum = int(day.rstrip(","))
    return f"{year}-{mnum:02d}-{dnum:02d}"


def _period_end_from_file(filename: str) -> str | None:
    """由文件名编号推导 period_end（Ground Truth 基于 IR 页标题确认的映射）。
    编号：48→FY2011, 49→FY2012, 50→FY2013, ..., 58→FY2021, 22→FY2022, ..., 27→FY2027。
    Q1→6月末, Q2→9月末, Q3→12月末, Q4→3月末。
    """
    m = re.match(r"(?:fy)?(\d{2})(?:Q|q)([1-4])", filename, re.I)
    if not m:
        return None
    num, q = int(m.group(1)), int(m.group(2))
    # 编号 → 财年结束年（3 月末所在年）
    if 48 <= num <= 58:
        fy_end = 2000 + (num - 48 + 11)  # 48→2011, 58→2021
    elif 20 <= num <= 30:
        fy_end = 2000 + num  # 22→2022, 27→2027
    else:
        return None
    qend = {1: (fy_end - 1, 6), 2: (fy_end - 1, 9), 3: (fy_end - 1, 12), 4: (fy_end, 3)}
    yr, mm = qend[q]
    return f"{yr}-{mm:02d}-{30 if mm != 3 else 31}"


def parse_all(raw_dir: Path | None = None) -> pl.DataFrame:
    rows: list[dict] = []
    source_dir = raw_dir or RAW_DIR
    for f in sorted(source_dir.glob("*.pdf")):
        try:
            from pypdf import PdfReader

            rdr = PdfReader(str(f))
            text = "\n".join((p.extract_text() or "") for p in rdr.pages)
        except Exception as e:
            logger.warning("PDF 解析失败 [%s]: %s", f.name, e)
            continue
        ns, cs = _extract_period_and_income(text, f.name)
        end = _period_end_from_file(f.name)
        rel = _extract_release_date(text)
        if not ns or not cs or not end:
            logger.warning("无损益表数据 [%s]", f.name)
            continue
        rows.append(
            {
                "company": "TEL",
                "file": f.name,
                "period_end": end,
                "release_date_raw": rel,
                "cum_net_sales_jpy_m": float(ns.replace(",", "")),
                "cum_cost_of_sales_jpy_m": float(cs.replace(",", "")),
                "cum_gross_profit_jpy_m": float(ns.replace(",", "")) - float(cs.replace(",", "")),
            }
        )
    return pl.DataFrame(rows)


# TEL 财报发布日（IR 日历，Ground Truth；财年 = 3 月期结束年，Q4=全年決算発表）
# FY2026 = 2025-04~2026-03 财年，Q4 全年 = 2026-04-30 发布
RELEASE_DATES: dict[int, dict[int, str]] = {
    2016: {1: "2015-07-28", 2: "2015-10-28", 3: "2016-01-29", 4: "2016-04-26"},
    2017: {1: "2016-07-29", 2: "2016-10-28", 3: "2017-01-31", 4: "2017-04-28"},
    2018: {1: "2017-07-27", 2: "2017-10-31", 3: "2018-01-30", 4: "2018-04-25"},
    2019: {1: "2018-07-26", 2: "2018-10-31", 3: "2019-01-31", 4: "2019-04-26"},
    2020: {1: "2019-07-26", 2: "2019-10-31", 3: "2020-01-30", 4: "2020-04-30"},
    2021: {1: "2020-07-28", 2: "2020-10-29", 3: "2021-01-28", 4: "2021-04-30"},
    2022: {1: "2021-08-16", 2: "2021-11-12", 3: "2022-02-10", 4: "2022-05-12"},
    2023: {1: "2022-08-08", 2: "2022-11-10", 3: "2023-02-09", 4: "2023-05-11"},
    2024: {1: "2023-08-10", 2: "2023-11-10", 3: "2024-02-09", 4: "2024-05-10"},
    2025: {1: "2024-08-08", 2: "2024-11-12", 3: "2025-02-06", 4: "2025-04-30"},
    2026: {1: "2025-07-31", 2: "2025-10-31", 3: "2026-02-06", 4: "2026-04-30"},
    2027: {1: "2026-07-30", 2: "2026-10-30", 3: "2027-02-05"},
}


def build_quarterly_frame(raw_dir: Path | None = None) -> pl.DataFrame:
    """从 TEL 本地 PDF 构建完整的单季 GM 表，供脚本和在线采集器复用。"""
    df = parse_all(raw_dir)
    if df.height == 0:
        return pl.DataFrame(schema=TEL_GM_QUARTERLY_SCHEMA)
    # 单季差分：累计口径 → 单季。财季序号由 period_end 月份推导（6月=Q1, 9月=Q2, 12月=Q3, 3月=Q4）
    df = df.with_columns(
        pl.when(pl.col("period_end").str.slice(5, 2) == "06")
        .then(1)
        .when(pl.col("period_end").str.slice(5, 2) == "09")
        .then(2)
        .when(pl.col("period_end").str.slice(5, 2) == "12")
        .then(3)
        .otherwise(4)
        .alias("fy_q")
    )
    df = df.sort(["period_end", "fy_q"])
    # 财年主键：period_end 是 3 月 → 财年=当年；否则 = 下一个 3 月所在年
    df = df.with_columns(
        pl.when(pl.col("period_end").str.slice(5, 2) == "03")
        .then(pl.col("period_end").str.slice(0, 4).cast(pl.Int64))
        .otherwise(pl.col("period_end").str.slice(0, 4).cast(pl.Int64) + 1)
        .alias("fiscal_year")
    )
    # 单季：按财年分组，当前累计 − 上一季累计；Q1 单季 = Q1 累计
    df = (
        df.with_columns(
            pl.col("cum_net_sales_jpy_m")
            .diff()
            .over("fiscal_year", order_by="fy_q")
            .alias("d_net"),
            pl.col("cum_gross_profit_jpy_m")
            .diff()
            .over("fiscal_year", order_by="fy_q")
            .alias("d_gp"),
        )
        .with_columns(
            pl.when(pl.col("fy_q") == 1)
            .then(pl.col("cum_net_sales_jpy_m"))
            .otherwise(pl.col("d_net"))
            .alias("net_sales_jpy_m"),
            pl.when(pl.col("fy_q") == 1)
            .then(pl.col("cum_gross_profit_jpy_m"))
            .otherwise(pl.col("d_gp"))
            .alias("gross_profit_jpy_m"),
        )
        .with_columns(
            (pl.col("gross_profit_jpy_m") / pl.col("net_sales_jpy_m") * 100.0).alias(
                "gross_margin_pct"
            )
        )
    )
    # 发布日：IR 日历表为准（新格式首页无日期）；早期（FY2015 及更早）用首页第 2 行兜底
    release_dates = pl.DataFrame(
        [
            {"fiscal_year": int(fy), "fy_q": int(q), "release_date": dt}
            for fy, d in RELEASE_DATES.items()
            for q, dt in d.items()
        ]
    )
    df = df.join(release_dates, on=["fiscal_year", "fy_q"], how="left", suffix="_fallback")
    df = df.with_columns(
        pl.coalesce([pl.col("release_date"), pl.col("release_date_raw")]).alias("release_date")
    )
    df = df.with_columns(pl.col("release_date").str.slice(0, 10).str.to_date())
    # report_quarter: 财年 + 季度（'FY2026-Q1' 以 3 月期结束年为准）
    df = df.with_columns(
        (
            "FY" + pl.col("fiscal_year").cast(pl.String) + "-Q" + pl.col("fy_q").cast(pl.String)
        ).alias("report_quarter")
    )
    df = df.with_columns(pl.col("period_end").str.to_date(strict=False))
    df = df.select(
        [
            "company",
            "report_quarter",
            "fiscal_year",
            "fy_q",
            "period_end",
            "net_sales_jpy_m",
            "gross_profit_jpy_m",
            "gross_margin_pct",
            "release_date",
            "file",
        ]
    ).cast(TEL_GM_QUARTERLY_SCHEMA)
    return df


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    df = build_quarterly_frame()
    if df.height == 0:
        logger.error("无数据")
        return
    df.write_parquet(OUT)
    print(f"已写出 {OUT}（{df.height} 行）")
    print(
        df.filter(pl.col("gross_margin_pct").is_not_null() & pl.col("release_date").is_not_null())
        .select(
            [
                "report_quarter",
                "period_end",
                "net_sales_jpy_m",
                "gross_profit_jpy_m",
                "gross_margin_pct",
                "release_date",
            ]
        )
        .tail(20)
    )


if __name__ == "__main__":
    main()
