"""基础化工 MDI / 钛白粉 参考价在线采集爬虫 (ChemicalsCrawler)。

数据源: 生意社 (100ppi.com) 商品频道免费页面, 每日发布商品参考价, 静态 HTML (带 WAF, 需浏览器 TLS 指纹)。
- MDI:   https://mdi.100ppi.com/    "8月31日，聚合MDI参考价为16866.67" (元/吨)
- 钛白粉: https://tio2.100ppi.com/  "8月31日，钛白粉参考价为14060.00" (元/吨)

口径与限制:
- 参考价为生意社商品均价口径, 与本地历史快照的价差字段 (mdi_gross_spread_cny/tio2_spread_cny) 不同,
  映射到新增参考价字段 (mdi_price_cny/tio2_price_cny);
- R32 制冷剂: 100ppi 氟化工频道无 R32 条目, 无免费结构化源, 不采集;
- 开工率 / 价差 / 库存天数: 无免费结构化在线源, 保持本地快照历史值。
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from curl_cffi import requests

from stock_data.fetcher.industry.common import now_utc_iso

logger = logging.getLogger(__name__)

PPI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
MDI_PPI_URL = "https://mdi.100ppi.com/"
TIO2_PPI_URL = "https://tio2.100ppi.com/"


def parse_mdi_reference_price(html_text: str) -> float | None:
    """从 MDI 频道页提取最新聚合 MDI 参考价 (元/吨)。

    快讯格式: "[ MDI ] 8月31日，聚合MDI参考价为16866.67，与8月1日(...)相比，下降了5.6%"
    """
    m = re.search(r"聚合MDI参考价为\s*([\d.]+)", html_text)
    if m:
        return round(float(m.group(1)), 2)
    return None


def parse_tio2_reference_price(html_text: str) -> float | None:
    """从钛白粉频道页提取最新钛白粉参考价 (元/吨)。

    快讯格式: "8月31日，钛白粉参考价为14060.00，与8月1日(15460.00)相比，下降了9.06%"
    """
    m = re.search(r"钛白粉参考价为\s*([\d.]+)", html_text)
    if m:
        return round(float(m.group(1)), 2)
    return None


class ChemicalsCrawler:
    """生意社 MDI / 钛白粉 参考价克制爬虫 (curl_cffi 浏览器指纹绕过 WAF)。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.snapshot_dir = self.raw_dir / "chemicals" / "100ppi"

    def _get(self, url: str) -> str | None:
        try:
            resp = requests.get(url, headers=PPI_HEADERS, impersonate="chrome120", timeout=20)
            if resp.status_code != 200:
                logger.warning("生意社页面返回 HTTP %d: %s", resp.status_code, url)
                return None
            resp.encoding = "utf-8"
            return str(resp.text)
        except Exception as e:
            logger.warning("访问生意社页面异常 [%s]: %s", url, e)
            return None

    def fetch_latest_prices(self) -> dict[str, Any] | None:
        """抓取 MDI 与钛白粉频道最新参考价并归档页面快照。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        result: dict[str, Any] = {}

        for key, url, parse_fn, name in (
            ("mdi_price_cny", MDI_PPI_URL, parse_mdi_reference_price, "聚合MDI"),
            ("tio2_price_cny", TIO2_PPI_URL, parse_tio2_reference_price, "钛白粉"),
        ):
            html_text = self._get(url)
            if html_text is None:
                continue
            snapshot_file = self.snapshot_dir / f"100ppi_{key.split('_')[0]}_latest.html"
            try:
                snapshot_file.write_text(html_text, encoding="utf-8")
            except Exception as e:
                logger.debug("保存生意社快照失败: %s", e)
            price = parse_fn(html_text)
            if price is not None:
                result[key] = price
                logger.info("✅ 成功抓取生意社%s参考价: %s 元/吨", name, price)
            else:
                logger.warning("生意社%s频道解析失败 (格式可能已改版)", name)

        if not result:
            return None
        result["source"] = "100ppi"
        result["source_url"] = MDI_PPI_URL
        result["release_date"] = date.today().isoformat()
        result["data_status"] = "actual"
        result["collected_at"] = now_utc_iso()
        return result
