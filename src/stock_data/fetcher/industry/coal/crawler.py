"""煤炭市场秦皇岛动力煤价格在线采集爬虫 (CoalMarketCrawler)。

数据源: CCTD (秦皇岛海运煤炭交易市场) 官网秦皇岛动力煤价格栏目, 免费静态页面 (GBK 编码)。
- URL: https://www.cctd.com.cn/index.php?a=lists&c=index&catid=520&m=content
- 字段: 秦皇岛港 CCTD 综合交易 5500 大卡平仓价 (元/吨), 周频发布。

已核实不可用源 (不采用):
- ak.macro_china_daily_energy(): 金十源沿海六大电数据实测停更于 2019-06;
- ak.spot_price_qh(): 99期货接口实测报错, 不可用;
- 电厂库存/日耗/可用天数与秦皇岛港库存: 无免费结构化在线源, 保持本地快照历史值。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import requests

from stock_data.fetcher.industry.base_parser import HtmlParserProtocol
from stock_data.fetcher.industry.common import now_utc_iso

logger = logging.getLogger(__name__)

CCTD_URL = "https://www.cctd.com.cn/index.php?a=lists&c=index&catid=520&m=content"
CCTD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class CctdCoalPriceHtmlParser:
    """CCTD 秦皇岛动力煤价格页 HTML 纯解析策略。"""

    def parse(self, html_text: str, **kwargs: Any) -> dict[str, Any] | None:
        """从 CCTD 秦皇岛动力煤价格页提取 CCTD 综合交易 5500 平仓价。"""
        idx = html_text.find("本期值")
        if idx < 0:
            return None
        segment = html_text[idx : idx + 300]
        m_price = re.search(r"<em[^>]*>\s*([\d.]+)\s*</em>", segment)
        if not m_price:
            return None
        m_mom = re.search(r"较上期.*?<em[^>]*>\s*([-\d.]+)\s*</em>", segment, re.DOTALL)
        m_date = re.search(r"日期：(\d{4}-\d{2}-\d{2})", html_text)
        if not m_date:
            return None
        return {
            "report_date": m_date.group(1),
            "q5500_fob_price_cny": float(m_price.group(1)),
            "q5500_mom": float(m_mom.group(1)) if m_mom else None,
        }


def parse_cctd_q5500(html_text: str) -> dict[str, Any] | None:
    """向后兼容的 CCTD 动力煤价格提取函数 (委托 CctdCoalPriceHtmlParser)。"""
    return CctdCoalPriceHtmlParser().parse(html_text)


class CoalMarketCrawler:
    """CCTD 秦皇岛动力煤价格页克制爬虫 (支持解析策略注入)。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry",
        parser: HtmlParserProtocol[dict[str, Any]] | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.snapshot_dir = self.raw_dir / "coal" / "cctd"
        self.parser = parser or CctdCoalPriceHtmlParser()

    def fetch_latest_q5500(self, force: bool = False) -> dict[str, Any] | None:
        """抓取 CCTD 最新一期 Q5500 平仓价并归档页面快照 (支持本地快照缓存)。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_file = self.snapshot_dir / "cctd_q5500_latest.html"

        if not force and snapshot_file.exists() and snapshot_file.stat().st_size > 0:
            try:
                html_text = snapshot_file.read_text(encoding="utf-8")
                parsed = self.parser.parse(html_text)
                if parsed:
                    parsed["source"] = "CCTD"
                    parsed["source_url"] = CCTD_URL
                    parsed["release_date"] = parsed["report_date"]
                    parsed["data_status"] = "actual"
                    parsed["collected_at"] = now_utc_iso()
                    logger.info(
                        "命中 CCTD 本地 RAW 快照: %s 元/吨 (%s)",
                        parsed["q5500_fob_price_cny"],
                        parsed["report_date"],
                    )
                    return parsed
            except Exception as e:
                logger.debug("读取 CCTD 本地快照失败，将在线重抓: %s", e)

        try:
            logger.info("正在抓取 CCTD 秦皇岛动力煤价格页: %s", CCTD_URL)
            resp = requests.get(CCTD_URL, headers=CCTD_HEADERS, timeout=20)
            if resp.status_code != 200:
                logger.warning("CCTD 页面返回 HTTP %d", resp.status_code)
                return None
            resp.encoding = "gbk"
            html_text = resp.text
        except Exception as e:
            logger.warning("访问 CCTD 页面异常: %s", e)
            return None

        try:
            snapshot_file.write_text(html_text, encoding="utf-8")
        except Exception as e:
            logger.debug("保存 CCTD 快照失败: %s", e)

        parsed = self.parser.parse(html_text)
        if parsed is None:
            logger.warning("CCTD 页面解析失败 (格式可能已改版)")
            return None

        parsed["source"] = "CCTD"
        parsed["source_url"] = CCTD_URL
        parsed["release_date"] = parsed["report_date"]
        parsed["data_status"] = "actual"
        parsed["collected_at"] = now_utc_iso()
        logger.info(
            "✅ 成功抓取 CCTD Q5500 平仓价: %s 元/吨 (%s)",
            parsed["q5500_fob_price_cny"],
            parsed["report_date"],
        )
        return parsed
