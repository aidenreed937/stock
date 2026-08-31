"""SIA / WSTS 全球半导体月度销售额协同采集器 (SemiconductorCollector)。

双源协同架构:
1. 主源 (WSTS Historical Billings): 负责 1986 ~ 至今 40 年连续无缺口的全球及四大区域 3MMA 销售额底表;
2. 补充源 (SIA Monthly News): 负责补充 China 销售额、官方新闻发布日期 (release_date) 及最新月份校验。
"""

import calendar
import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from curl_cffi import requests

from stock_data.fetcher.industry.common import (
    now_utc_iso,
    save_raw_snapshot,
)
from stock_data.fetcher.industry.models import SemiconductorSalesRecord

logger = logging.getLogger(__name__)

MONTH_MAP = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

WSTS_EXCEL_URL = "https://www.wsts.org/esraCMS/extension/media/f/WST/7735/WSTS-Historical-Billings-Report-Jun_2026.xlsx"


@dataclass(frozen=True)
class _WstsParsedItem:
    report_month: str
    trade_date: date
    global_sales_usd: float
    americas_sales_usd: float | None
    europe_sales_usd: float | None
    japan_sales_usd: float | None
    asia_pacific_sales_usd: float | None  # WSTS "Asia Pacific" 区域含中国


def parse_wsts_excel_file(excel_path: Path) -> list[SemiconductorSalesRecord]:
    """解析 WSTS 官方 Historical Billings Excel 文件的 3MMA 工作表。"""
    xl = pd.ExcelFile(excel_path)
    df_raw = pd.read_excel(xl, sheet_name="3MMA")

    raw_list: list[_WstsParsedItem] = []
    i = 3
    while i < len(df_raw):
        val_0 = df_raw.iloc[i, 0]
        if pd.isna(val_0):
            i += 1
            continue
        try:
            year = int(str(val_0).strip())
        except ValueError:
            i += 1
            continue

        regions: dict[str, list[Any]] = {}
        for r_offset in range(1, 6):
            if i + r_offset < len(df_raw):
                reg_name = str(df_raw.iloc[i + r_offset, 0]).strip()
                row_vals = df_raw.iloc[i + r_offset, 1:13].values
                regions[reg_name.lower()] = list(row_vals)

        worldwide_vals = regions.get("worldwide", [])
        americas_vals = regions.get("americas", [])
        europe_vals = regions.get("europe", [])
        japan_vals = regions.get("japan", [])
        asia_vals = regions.get("asia pacific", [])

        for m_idx in range(12):
            if m_idx < len(worldwide_vals):
                w_val = worldwide_vals[m_idx]
                if pd.notna(w_val) and isinstance(w_val, int | float) and w_val > 0:
                    month = m_idx + 1
                    report_month = f"{year:04d}-{month:02d}"
                    last_day = calendar.monthrange(year, month)[1]
                    t_date = date(year, month, last_day)

                    sales_b = round(float(w_val) / 1_000_000.0, 3)
                    am_b = (
                        round(float(americas_vals[m_idx]) / 1_000_000.0, 3)
                        if m_idx < len(americas_vals) and pd.notna(americas_vals[m_idx])
                        else None
                    )
                    eu_b = (
                        round(float(europe_vals[m_idx]) / 1_000_000.0, 3)
                        if m_idx < len(europe_vals) and pd.notna(europe_vals[m_idx])
                        else None
                    )
                    jp_b = (
                        round(float(japan_vals[m_idx]) / 1_000_000.0, 3)
                        if m_idx < len(japan_vals) and pd.notna(japan_vals[m_idx])
                        else None
                    )
                    as_b = (
                        round(float(asia_vals[m_idx]) / 1_000_000.0, 3)
                        if m_idx < len(asia_vals) and pd.notna(asia_vals[m_idx])
                        else None
                    )

                    raw_list.append(
                        _WstsParsedItem(
                            report_month=report_month,
                            trade_date=t_date,
                            global_sales_usd=sales_b,
                            americas_sales_usd=am_b,
                            europe_sales_usd=eu_b,
                            japan_sales_usd=jp_b,
                            asia_pacific_sales_usd=as_b,
                        )
                    )
        i += 6

    raw_list.sort(key=lambda x: x.trade_date)
    sales_map = {r.report_month: r.global_sales_usd for r in raw_list}

    records: list[SemiconductorSalesRecord] = []
    for r in raw_list:
        rm = r.report_month
        y, m = int(rm[:4]), int(rm[5:7])

        prev_m_str = f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"
        mom = None
        if prev_m_str in sales_map and sales_map[prev_m_str] > 0:
            mom = round((r.global_sales_usd - sales_map[prev_m_str]) / sales_map[prev_m_str], 4)

        prev_y_str = f"{y - 1:04d}-{m:02d}"
        yoy = None
        if prev_y_str in sales_map and sales_map[prev_y_str] > 0:
            yoy = round((r.global_sales_usd - sales_map[prev_y_str]) / sales_map[prev_y_str], 4)

        records.append(
            SemiconductorSalesRecord(
                report_month=r.report_month,
                trade_date=r.trade_date,
                global_sales_usd=r.global_sales_usd,
                americas_sales_usd=r.americas_sales_usd,
                europe_sales_usd=r.europe_sales_usd,
                japan_sales_usd=r.japan_sales_usd,
                asia_pacific_sales_usd=r.asia_pacific_sales_usd,
                yoy_growth=yoy,
                mom_growth=mom,
                unit="billion_usd",
                source="WSTS/SIA",
                source_url="https://www.wsts.org/67/Historical-Billings-Report",
                data_status="actual",
                collected_at=now_utc_iso(),
            )
        )

    return records


def parse_sia_china_and_date(html_text: str, source_url: str) -> dict[str, Any] | None:
    """从 SIA 新闻 HTML 中高精度抽取月份、发布日期及中国区销售与增速数据。"""
    # 1. 匹配发布日期 (兼容 WASHINGTON, Dec. 5, 2022 / WASHINGTON—Jan. 9, 2023)
    rel_date = None
    date_m = re.search(
        r"WASHINGTON[—,\s\-]*([A-Za-z]+)\.?\s+(\d{1,2}),\s*(20\d\d)", html_text, re.IGNORECASE
    )
    if date_m:
        rel_m_str, rel_d_str, rel_y_str = date_m.groups()
        rel_m_num = MONTH_MAP.get(rel_m_str.lower().rstrip("."))
        if rel_m_num:
            rel_date = date(int(rel_y_str), rel_m_num, int(rel_d_str))

    # 2. 匹配所属月份
    m_month = re.search(
        r"(?:during|in|for)\s+(?:the\s+month\s+of\s+)?([A-Za-z]+)\.?\s+(20\d\d)",
        html_text,
        re.IGNORECASE,
    )
    if not m_month:
        return None
    m_str, y_str = m_month.groups()
    m_num = MONTH_MAP.get(m_str.lower().rstrip("."))
    if not m_num:
        return None

    report_month = f"{int(y_str):04d}-{m_num:02d}"

    # 3. 匹配中国区增速与销售额
    china_sales = None
    china_yoy = None
    china_mom = None

    for sent in re.split(r"\.\s+", html_text):
        if "china" in sent.lower():
            if "month-to-month" in sent.lower() and china_mom is None:
                c_m = re.search(r"China\s*\(([-+]?[\d.]+)\s*(?:%|percent)\)", sent, re.IGNORECASE)
                if c_m:
                    china_mom = round(float(c_m.group(1)) / 100.0, 4)
            if "year-to-year" in sent.lower() and china_yoy is None:
                c_y = re.search(r"China\s*\(([-+]?[\d.]+)\s*(?:%|percent)\)", sent, re.IGNORECASE)
                if c_y:
                    china_yoy = round(float(c_y.group(1)) / 100.0, 4)

    if china_yoy is None:
        c_any = re.search(r"China\s*\(([-+]?[\d.]+)\s*(?:%|percent)\)", html_text, re.IGNORECASE)
        if not c_any:
            c_any = re.search(r"([-+]?[\d.]+)\s*(?:%|percent)[^.]*?China", html_text, re.IGNORECASE)
        if c_any:
            val = float(c_any.group(1)) / 100.0
            if "decreased" in html_text.lower() and val > 0 and "-" not in c_any.group(1):
                val = -val
            china_yoy = round(val, 4)

    china_m_abs = re.search(
        r"China\s+(?:\([^)]+\)\s+)?(?:were|totaled|was)?\s*\$?([\d.]+)\s*billion",
        html_text,
        re.IGNORECASE,
    )
    if china_m_abs:
        china_sales = float(china_m_abs.group(1))

    return {
        "report_month": report_month,
        "release_date": rel_date,
        "china_sales_usd": china_sales,
        "china_yoy_growth": china_yoy,
        "china_mom_growth": china_mom,
        "source_url": source_url,
    }


class SemiconductorCollector:
    """WSTS / SIA 全球及中国半导体月度销售额双源协同采集适配器。"""

    def __init__(
        self,
        timeout: int = 20,
        impersonate: str = "chrome120",
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.timeout = timeout
        self.impersonate = impersonate
        self.raw_dir = Path(raw_dir)
        self.sia_raw_dir = self.raw_dir / "sia"

    def collect(self) -> list[SemiconductorSalesRecord]:
        """执行 WSTS 历史底表与 SIA 最新月报的双源协同采集。"""
        wsts_records = self._fetch_and_parse_wsts_history()
        sia_enrichments = self._fetch_sia_news_enrichments()

        final_records: list[SemiconductorSalesRecord] = []
        for r in wsts_records:
            enrich = sia_enrichments.get(r.report_month)
            if enrich:
                china_sales = enrich.get("china_sales_usd")
                c_yoy = enrich.get("china_yoy_growth")
                c_mom = enrich.get("china_mom_growth")
                rel_d = enrich.get("release_date")
                s_url = str(enrich.get("source_url") or r.source_url)
                rec = SemiconductorSalesRecord(
                    report_month=r.report_month,
                    trade_date=r.trade_date,
                    global_sales_usd=r.global_sales_usd,
                    china_sales_usd=float(china_sales) if china_sales is not None else None,
                    china_yoy_growth=float(c_yoy) if c_yoy is not None else None,
                    china_mom_growth=float(c_mom) if c_mom is not None else None,
                    americas_sales_usd=r.americas_sales_usd,
                    europe_sales_usd=r.europe_sales_usd,
                    japan_sales_usd=r.japan_sales_usd,
                    asia_pacific_sales_usd=r.asia_pacific_sales_usd,
                    yoy_growth=r.yoy_growth,
                    mom_growth=r.mom_growth,
                    unit="billion_usd",
                    source="WSTS/SIA",
                    source_url=s_url,
                    release_date=rel_d if isinstance(rel_d, date) else None,
                    data_status="actual",
                    collected_at=now_utc_iso(),
                )
            else:
                rec = r
            final_records.append(rec)

        final_records.sort(key=lambda x: x.trade_date)
        logger.info("WSTS/SIA 半导体协同采集完成: 共 %d 个月度连续数据", len(final_records))
        return final_records

    def _fetch_and_parse_wsts_history(self) -> list[SemiconductorSalesRecord]:
        """下载并解析 WSTS 官方 Historical Billings Report。"""
        excel_path = self.sia_raw_dir / "WSTS-Historical-Billings-Report-Jun_2026.xlsx"
        if not excel_path.exists():
            try:
                resp = requests.get(
                    WSTS_EXCEL_URL, impersonate=self.impersonate, timeout=self.timeout
                )
                if resp.status_code == 200:
                    self.sia_raw_dir.mkdir(parents=True, exist_ok=True)
                    excel_path.write_bytes(resp.content)
            except Exception as exc:
                logger.warning("下载 WSTS 官方 Excel 失败: %s", exc)

        if not excel_path.exists():
            logger.error("未找到 WSTS 官方历史 Excel 文件: %s", excel_path)
            return []

        return parse_wsts_excel_file(excel_path)

    def _fetch_sia_news_enrichments(self) -> dict[str, dict[str, Any]]:
        """在线抓取 SIA 官网最新月度新闻，解析 China 销售数据与 release_date。"""
        enrichments: dict[str, dict[str, Any]] = {}

        # 在线获取最新发布的月报公报
        list_url = "https://www.semiconductors.org/news-events/latest-news/"
        try:
            resp = requests.get(list_url, impersonate=self.impersonate, timeout=self.timeout)
            if resp.status_code == 200:
                save_raw_snapshot(
                    "sia",
                    "latest_news_list.html.gz",
                    resp.text,
                    base_dir=self.raw_dir,
                    compress=True,
                )
                links = re.findall(
                    r'href="(https://www\.semiconductors\.org/global-semiconductor-sales-[^"]+)"',
                    resp.text,
                )
                for link in set(links[:10]):
                    try:
                        r_art = requests.get(
                            link, impersonate=self.impersonate, timeout=self.timeout
                        )
                        if r_art.status_code == 200:
                            slug = link.rstrip("/").split("/")[-1]
                            save_raw_snapshot(
                                "sia",
                                f"{slug}.html.gz",
                                r_art.text,
                                base_dir=self.raw_dir,
                                compress=True,
                            )
                            parsed = parse_sia_china_and_date(r_art.text, link)
                            if parsed and parsed.get("report_month"):
                                enrichments[str(parsed["report_month"])] = parsed
                        time.sleep(0.1)
                    except Exception as e:
                        logger.debug("SIA 文章补充解析失败 [%s]: %s", link, e)
        except Exception as exc:
            logger.debug("抓取 SIA 新闻列表异常: %s", exc)

        return enrichments
