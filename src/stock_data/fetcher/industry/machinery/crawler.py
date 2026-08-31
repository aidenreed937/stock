"""中国工程机械工业协会 (CCMA) 与小松 (Komatsu) 官方克制在线爬虫。"""

from __future__ import annotations

import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

from curl_cffi import requests

from stock_data.fetcher.industry.common import (
    now_utc_iso,
    read_raw_text,
    save_raw_snapshot,
)

logger = logging.getLogger(__name__)

CCMA_BASE_URL = "http://www.cncma.org"
CCMA_NEWS_LIST_URL = "http://www.cncma.org/column/23"
KOMATSU_DEMAND_ORDERS_URL = "https://www.komatsu.jp/en/ir/library/demand-orders"


def parse_ccma_excavator_article(html_text: str, source_url: str = "") -> dict[str, Any] | None:
    """从 CCMA 官方新闻 HTML 正文中高精度抽取所属月份、发布日期与挖掘机产销数据。

    典型通报句式:
    "据中国工程机械工业协会对挖掘机主要制造企业统计，2026年7月销售各类挖掘机19521台，同比增长13.9%。
    其中：国内销量7608台（含电动挖掘机41台），同比增长4.13%；出口11913台（含电动挖掘机62台），同比增长21.2%。"
    """
    if "挖掘机" not in html_text:
        return None

    # 1. 解析所属月份 (排除 'YYYY年MM月DD日' 的发布日期格式，匹配 'YYYY年M月销售各类挖掘机' 或 'YYYY年M月工程机械...')
    month_m = re.search(
        r"(20\d\d)\s*年\s*(?:1-)?(\d{1,2})\s*月(?:份)?(?!\s*\d{1,2}\s*日)", html_text
    )
    if not month_m:
        return None
    year = int(month_m.group(1))
    month = int(month_m.group(2))
    report_month = f"{year:04d}-{month:02d}"

    # 2. 解析发布日期 (例如: 2026年08月07日 / 2026-08-07)
    rel_date = None
    date_m = re.search(r"(20\d\d)[年\-/](\d{1,2})[月\-/](\d{1,2})", html_text)
    if date_m:
        ry, rm, rd = int(date_m.group(1)), int(date_m.group(2)), int(date_m.group(3))
        try:
            rel_date = date(ry, rm, rd)
        except ValueError:
            pass

    # 3. 解析挖掘机当月总销量
    total_units: float | None = None
    tot_m = re.search(
        r"销售各类挖掘机\s*(\d+)\s*台",
        html_text,
    )
    if not tot_m:
        tot_m = re.search(r"共销售挖掘机\s*(\d+)\s*台", html_text)
    if tot_m:
        total_units = float(tot_m.group(1))

    # 4. 解析国内销量
    dom_units: float | None = None
    dom_m = re.search(r"国内销量\s*(\d+)\s*台", html_text)
    if dom_m:
        dom_units = float(dom_m.group(1))

    # 5. 解析出口销量
    exp_units: float | None = None
    exp_m = re.search(r"出口(?:量)?\s*(\d+)\s*台", html_text)
    if exp_m:
        exp_units = float(exp_m.group(1))

    if total_units is None and dom_units is None and exp_units is None:
        return None

    if total_units is None and dom_units is not None and exp_units is not None:
        total_units = dom_units + exp_units

    return {
        "report_month": report_month,
        "release_date": rel_date,
        "excavator_total_units": total_units or 0.0,
        "excavator_domestic_units": dom_units or 0.0,
        "excavator_export_units": exp_units or 0.0,
        "source": "CCMA",
        "source_url": source_url,
        "collected_at": now_utc_iso(),
    }


def parse_komatsu_china_hours_text(text: str) -> dict[str, float]:
    """从小松官方公告或新闻文本中抽取中国区挖掘机月度开工小时数。

    匹配示例:
    "中国地区小松挖掘机开工小时数为90.8小时"
    "China: 90.8 hours"
    """
    results: dict[str, float] = {}

    # 句式 1: "2026年7月...中国地区小松挖掘机开工小时数为90.8小时"
    matches = re.finditer(
        r"(20\d\d)\s*年\s*(\d{1,2})\s*月[^。，\n]*?中国(?:地区)?[^。，\n]*?开工小时数(?:为)?\s*([\d.]+)\s*小时",
        text,
    )
    for m in matches:
        yr = int(m.group(1))
        mo = int(m.group(2))
        hrs = float(m.group(3))
        results[f"{yr:04d}-{mo:02d}"] = hrs

    # 句式 2: "China ... 90.8"
    matches_en = re.finditer(
        r"(?:China|CHINA)[^\d\n]*?(20\d\d)-(0[1-9]|1[0-2])[^\d\n]*?([\d.]+)\s*hours?",
        text,
        re.IGNORECASE,
    )
    for m in matches_en:
        rm = f"{m.group(1)}-{m.group(2)}"
        hrs = float(m.group(3))
        results[rm] = hrs

    return results


class CcmaCrawler:
    """中国工程机械工业协会 (CCMA) 挖掘机销售快报克制在线爬虫。"""

    def __init__(
        self,
        timeout: int = 15,
        impersonate: str = "chrome120",
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.timeout = timeout
        self.impersonate = impersonate
        self.raw_dir = Path(raw_dir)
        self.machinery_dir = self.raw_dir / "machinery"

    def fetch_latest_sales(self) -> dict[str, dict[str, Any]]:
        """从 CCMA 官网抓取最新月度挖掘机产销通报并保存原始 HTML Gzip 快照。"""
        self.machinery_dir.mkdir(parents=True, exist_ok=True)
        results: dict[str, dict[str, Any]] = {}

        # 1. 先扫描本地已归档的 CCMA 快照
        for h in self.machinery_dir.glob("ccma_*.html*"):
            try:
                content = read_raw_text(h)
                parsed = parse_ccma_excavator_article(content, source_url="")
                if parsed and parsed.get("report_month"):
                    results[str(parsed["report_month"])] = parsed
            except Exception as e:
                logger.debug("读取本地 CCMA 快照失败 [%s]: %s", h.name, e)

        # 2. 在线克制请求 CCMA 官网列表页
        try:
            logger.info("正在在线扫描 CCMA 官网销售快报列表: %s", CCMA_NEWS_LIST_URL)
            resp = requests.get(
                CCMA_NEWS_LIST_URL,
                impersonate=self.impersonate,
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                logger.warning("CCMA 官网列表请求返回 HTTP %d", resp.status_code)
                return results

            html_text = resp.text
            save_raw_snapshot(
                "machinery",
                "ccma_news_list.html.gz",
                html_text,
                base_dir=self.raw_dir,
                compress=True,
            )

            # 匹配快报文章链接
            article_links = re.findall(
                r'href="(/article/\d+)"[^>]*>([^<]*销售快报一[^<]*)</a>',
                html_text,
            )
            for link_path, _title in article_links[:5]:
                full_url = f"{CCMA_BASE_URL}{link_path}"
                slug = link_path.strip("/").replace("/", "_")
                try:
                    time.sleep(0.2)
                    r_art = requests.get(
                        full_url, impersonate=self.impersonate, timeout=self.timeout
                    )
                    if r_art.status_code == 200:
                        save_raw_snapshot(
                            "machinery",
                            f"ccma_{slug}.html.gz",
                            r_art.text,
                            base_dir=self.raw_dir,
                            compress=True,
                        )
                        parsed = parse_ccma_excavator_article(r_art.text, full_url)
                        if parsed and parsed.get("report_month"):
                            results[str(parsed["report_month"])] = parsed
                except Exception as e:
                    logger.debug("抓取 CCMA 快报文章失败 [%s]: %s", full_url, e)
        except Exception as exc:
            logger.warning("CCMA 官网在线抓取异常: %s", exc)

        return results


class KomatsuCrawler:
    """小松 (Komatsu) 官网全球及中国区挖机开工小时数克制在线爬虫。"""

    def __init__(
        self,
        timeout: int = 15,
        impersonate: str = "chrome120",
        raw_dir: Path | str = "data/raw/industry",
    ) -> None:
        self.timeout = timeout
        self.impersonate = impersonate
        self.raw_dir = Path(raw_dir)
        self.machinery_dir = self.raw_dir / "machinery"

    def fetch_latest_hours(self) -> dict[str, float]:
        """从小松官网抓取最新 Komtrax 开工小时数数据。"""
        self.machinery_dir.mkdir(parents=True, exist_ok=True)
        results: dict[str, float] = {}

        # 1. 扫描本地已归档的小松快照
        for h in self.machinery_dir.glob("komatsu_*.html*"):
            try:
                content = read_raw_text(h)
                parsed = parse_komatsu_china_hours_text(content)
                results.update(parsed)
            except Exception as e:
                logger.debug("读取本地小松快照失败 [%s]: %s", h.name, e)

        # 2. 在线克制请求小松官网
        try:
            logger.info("正在在线扫描小松官网需求与订单页面: %s", KOMATSU_DEMAND_ORDERS_URL)
            resp = requests.get(
                KOMATSU_DEMAND_ORDERS_URL,
                impersonate=self.impersonate,
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                save_raw_snapshot(
                    "machinery",
                    "komatsu_demand_orders.html.gz",
                    resp.text,
                    base_dir=self.raw_dir,
                    compress=True,
                )
                parsed = parse_komatsu_china_hours_text(resp.text)
                results.update(parsed)
        except Exception as exc:
            logger.warning("小松官网在线抓取异常: %s", exc)

        return results
