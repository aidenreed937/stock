"""农业农村部「生猪产品数据」月度通报在线采集爬虫 (MaraPorkCrawler)。

数据源: 农业农村部官网生猪专题-月度数据栏目 (五部门联合发布), 服务端渲染表格 + 每月一份 XLSX。
- 栏目: https://www.moa.gov.cn/ztzl/szcpxx/jdsj/{YYYY}/{YYYYMM}/
- 字段: 能繁母猪存栏 (万头/季度末口径), 全国生猪出场价格 (元/公斤), 猪粮比价, 每头净利润 (元/头)。
- 已知漂移: 2025-09 起猪粮比价与每头净利润从月度页消失; 能繁母猪 2026 年起仅季度末月发布
  ("X季度末" 口径), 解析按字段缺失容忍设计。
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from stock_data.fetcher.industry.common import now_utc_iso

logger = logging.getLogger(__name__)

MARA_JDSJ_ROOT = "https://www.moa.gov.cn/ztzl/szcpxx/jdsj"
MARA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
FETCH_INTERVAL_SECONDS = 3.0  # 克制爬取间隔 (WAF 站点, 月度低频)


def _to_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    cleaned = raw.replace(",", "").replace(" ", "").strip()
    m = re.search(r"[-+]?\d+\.?\d*", cleaned)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def parse_mara_monthly_table(html_text: str) -> dict[str, Any] | None:
    """解析农业农村部生猪产品数据月度表格页。

    页面含多张 table.data_table (生产/价格/进出口/成本收益), 行格式:
      <td>2025年8月末能繁母猪存栏（万头）</td> <td>4038</td> ...
      <td>2025年8月份全国生猪出场价格（元/公斤）</td> <td>14.23</td>
      <td>2025年8月份猪粮比价</td> <td>5.94</td>
      <td>2025年8月份散养生猪每头净利润（元）</td> <td>-109</td>
    2026 年起能繁母猪为季度末口径: "2026年1季度末能繁母猪存栏（万头）"。
    """
    soup = BeautifulSoup(html_text, "html.parser")
    rows: list[tuple[str, str]] = []
    for table in soup.find_all("table"):
        if "data_table" not in " ".join(table.get("class") or []):
            continue
        for tr in table.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) < 2:
                continue
            # 兼容 5 列结构 [序号, 指标, 数值, 环比, 同比] 与旧 2 列结构 [指标, 数值]
            if len(tds) >= 3 and tds[0].strip().isdigit():
                rows.append((tds[1], tds[2]))
            else:
                rows.append((tds[0], tds[1]))
    if not rows:
        return None

    sow_val: float | None = None
    pig_price: float | None = None
    ratio_val: float | None = None
    profit_val: float | None = None
    report_month: str | None = None

    for label, value in rows:
        # 从任意指标行提取月份 (月度页可能缺某类指标, 如 2026 年能繁母猪仅季度末发布)
        if report_month is None:
            m = re.search(r"(20\d\d)\s*年\s*(?:(\d{1,2})\s*月|(\d)\s*季度)末?", label)
            if m:
                year = int(m.group(1))
                month = int(m.group(2)) if m.group(2) else int(m.group(3)) * 3
                report_month = f"{year:04d}-{month:02d}"
        if "能繁母猪存栏" in label:
            raw = _to_float(value)
            if raw is not None:
                sow_val = round(raw * 0.01, 2)  # 万头 -> 百万头
        elif "生猪出场价格" in label and pig_price is None:
            pig_price = _to_float(value)
        elif "猪粮比价" in label and ratio_val is None:
            ratio_val = _to_float(value)
        elif "每头净利润" in label and profit_val is None:
            profit_val = _to_float(value)

    if report_month is None or (sow_val is None and pig_price is None):
        return None

    return {
        "report_month": report_month,
        "sow_stock_million_heads": sow_val,
        "pig_price_cny_per_kg": pig_price,
        "hog_to_grain_ratio": ratio_val,
        "pig_farming_profit_cny_head": profit_val,
    }


class MaraPorkCrawler:
    """农业农村部生猪产品数据月度表格页克制爬虫。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.mara_dir = self.raw_dir / "agriculture" / "mara"

    def _get(self, url: str, timeout: int = 20) -> requests.Response | None:
        try:
            resp = requests.get(url, headers=MARA_HEADERS, timeout=timeout)
            if resp.status_code == 200:
                resp.encoding = "utf-8"
                return resp
            logger.warning("农业农村部页面返回 HTTP %d: %s", resp.status_code, url)
        except Exception as e:
            logger.warning("访问农业农村部页面异常 [%s]: %s", url, e)
        return None

    def discover_latest_month(self, max_tries: int = 6) -> str | None:
        """从当前月往前逐月探测 jdsj 月度页, 首个 200 即最新已发布月份 (YYYY-MM)。"""
        today = date.today()
        for offset in range(max_tries):
            year = today.year
            month = today.month - offset
            while month <= 0:
                year -= 1
                month += 12
            month_key = f"{year:04d}-{month:02d}"
            url = f"{MARA_JDSJ_ROOT}/{year}/{month_key.replace('-', '')}/"
            resp = self._get(url, timeout=15)
            if resp is not None:
                logger.info("探测到最新生猪月度数据页: %s", month_key)
                return month_key
            time.sleep(FETCH_INTERVAL_SECONDS)
        return None

    def fetch_latest_month(self) -> dict[str, Any] | None:
        """抓取最新一期生猪月度数据页并解析, 同时归档页面 HTML 快照。"""
        self.mara_dir.mkdir(parents=True, exist_ok=True)
        month_key = self.discover_latest_month()
        if month_key is None:
            logger.warning("未探测到农业农村部生猪月度数据页")
            return None

        year, month = month_key.split("-")
        url = f"{MARA_JDSJ_ROOT}/{year}/{year}{month}/"
        resp = self._get(url)
        if resp is None:
            return None

        snapshot_file = self.mara_dir / f"jdsj_{year}{month}.html"
        try:
            snapshot_file.write_text(resp.text, encoding="utf-8")
        except Exception as e:
            logger.debug("保存农业农村部月度快照失败: %s", e)

        parsed = parse_mara_monthly_table(resp.text)
        if parsed is None:
            logger.warning("农业农村部 %s 月度页解析失败", month_key)
            return None

        parsed["source"] = "MARA"
        parsed["source_url"] = url
        parsed["release_date"] = date.today().isoformat()
        parsed["data_status"] = "actual"
        parsed["collected_at"] = now_utc_iso()
        logger.info(
            "✅ 成功抓取农业农村部 %s 生猪数据: 能繁=%s 万头, 价格=%s 元/公斤",
            month_key,
            parsed.get("sow_stock_million_heads"),
            parsed.get("pig_price_cny_per_kg"),
        )
        return parsed
