"""生意社 100ppi 商品定基指数采集器 (CommodityIndexCollector)。

负责从生意社官方商品指数表 (cindex/ptrade-{ppid}.html) 抓取、缓存 RAW 快照并解析。
支持：
1. 默认涵盖 PX、POY、FDY、DTY、聚合MDI、钛白粉等非期货品种；
2. 本地 RAW 快照断点续传（Cache First）；
3. 自动注入 HW_CHECK WAF Cookie 质询响应；
4. 批量采集与重试防封。
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests

from stock_data.fetcher.industry.chemicals.parsers.commodity_index import (
    CommodityIndexRow,
    parse_100ppi_ptrade_html,
)

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 默认监控的非期货核心大宗化工品池与对照组
DEFAULT_COMMODITY_CONFIG: dict[str, dict[str, Any]] = {
    "PX": {"ppid": 968, "name": "对二甲苯(PX)"},
    "POY": {"ppid": 1006, "name": "涤纶长丝POY"},
    "FDY": {"ppid": 1005, "name": "涤纶长丝FDY"},
    "DTY": {"ppid": 1007, "name": "涤纶长丝DTY"},
    "MDI_poly": {"ppid": 975, "name": "聚合MDI"},
    "TiO2": {"ppid": 645, "name": "金红石型钛白粉"},
    "PTA": {"ppid": 356, "name": "精对苯二甲酸(PTA)"},
    "MEG": {"ppid": 222, "name": "乙二醇(MEG)"},
}


class CommodityIndexCollector:
    """生意社商品定基指数采集器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry/chemicals",
        session: requests.Session | None = None,
        base_url: str = "https://www.100ppi.com/cindex/ptrade-{ppid}.html",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.cindex_raw_dir = self.raw_dir / "100ppi_cindex"
        self.cindex_raw_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.base_url = base_url

    def download_ptrade_html(
        self,
        ppid: int,
        fetch_date: date | None = None,
        force: bool = False,
    ) -> tuple[Path | None, str | None]:
        """下载或读取本地当日缓存的 ptrade HTML 页面。

        Args:
            ppid: 生意社商品编号。
            fetch_date: 采集基准日（默认为今日）。
            force: 是否忽略本地快照强制网络重新下载。

        Returns:
            (快照路径, 页面文本)。若抓取失败返回 (None, None)。
        """
        cur_date = fetch_date or date.today()
        d_str = cur_date.isoformat()
        snapshot_path = self.cindex_raw_dir / f"ptrade-{ppid}-{d_str}.html"

        # 1. 本地当日缓存命中 (Cache First)
        if not force and snapshot_path.exists() and snapshot_path.stat().st_size > 100:
            try:
                content = snapshot_path.read_text(encoding="utf-8")
                return snapshot_path, content
            except Exception as e:
                logger.warning(f"读取本地缓存 {snapshot_path} 失败: {e}，重新网络下载")

        # 2. 网络下载与 WAF 质询自适应
        url = self.base_url.format(ppid=ppid)
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.get(url, timeout=12)

                if resp.status_code == 404:
                    logger.warning(f"商品 ppid={ppid} 页面不存在 404: {url}")
                    return None, None

                if resp.status_code != 200:
                    logger.warning(
                        f"抓取 {url} 失败 HTTP {resp.status_code} (尝试 {attempt}/{max_retries})"
                    )
                    time.sleep(attempt * 0.8)
                    continue

                text = resp.text

                # 检查是否触发 HW_CHECK 安全质询
                if "HW_CHECK" in text:
                    m = re.search(r'var\s+_0x2\s*=\s*"([^"]+)"', text)
                    if m:
                        token = m.group(1)
                        self.session.cookies.set("HW_CHECK", token, domain=".100ppi.com")
                        logger.debug(f"注入 HW_CHECK token: {token} 并重发请求")
                        resp2 = self.session.get(url, timeout=12)
                        text = resp2.text

                # 验证是否为真实数据页面
                if len(text) > 100 and ("商品指数" in text or "日期" in text):
                    # 写入本地原子缓存
                    tmp_path = snapshot_path.with_suffix(".tmp")
                    tmp_path.write_text(text, encoding="utf-8")
                    tmp_path.replace(snapshot_path)
                    return snapshot_path, text

                if "暂无数据" in text or len(text) < 100:
                    logger.warning(f"商品 ppid={ppid} 暂无数据或页面内容异常")
                    return None, None

            except requests.RequestException as exc:
                logger.warning(f"抓取 {url} 网络异常: {exc} (尝试 {attempt}/{max_retries})")
                time.sleep(attempt * 1.0)

        return None, None

    def collect_commodity(
        self,
        symbol: str,
        ppid: int,
        name: str,
        fetch_date: date | None = None,
        force: bool = False,
    ) -> list[CommodityIndexRow]:
        """采集单个商品的定基指数数据行。"""
        _, html = self.download_ptrade_html(ppid, fetch_date=fetch_date, force=force)
        if not html:
            return []
        return parse_100ppi_ptrade_html(html, ppid=ppid, symbol=symbol, product_name=name)

    def collect_all(
        self,
        commodities: dict[str, dict[str, Any]] | None = None,
        fetch_date: date | None = None,
        force: bool = False,
        interval_sec: float = 0.5,
    ) -> list[CommodityIndexRow]:
        """批量采集指定或默认商品池的定基指数记录。

        Args:
            commodities: 自定义商品池字典，格式为 {symbol: {"ppid": int, "name": str}}。
            fetch_date: 采集基准日。
            force: 是否强制网络刷新。
            interval_sec: 品类间抓取休眠间隔（防风控）。

        Returns:
            所有品类近 90 天数据合并后的记录列表。
        """
        pool = commodities or DEFAULT_COMMODITY_CONFIG
        all_records: list[CommodityIndexRow] = []

        for symbol, conf in pool.items():
            ppid = conf["ppid"]
            name = conf["name"]
            logger.info(f"开始采集商品定基指数: {symbol} ({name}, ID={ppid})")
            rows = self.collect_commodity(
                symbol=symbol,
                ppid=ppid,
                name=name,
                fetch_date=fetch_date,
                force=force,
            )
            logger.info(f"商品 {symbol} 解析出 {len(rows)} 条日频指数记录")
            all_records.extend(rows)
            if interval_sec > 0:
                time.sleep(interval_sec)

        return all_records
