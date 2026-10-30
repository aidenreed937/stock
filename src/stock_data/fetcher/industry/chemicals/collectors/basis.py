"""生意社 100ppi 每日现期基差采集器 (SpotFuturesBasisCollector)。

负责从生意社官方每日现期表 (sf/day-YYYY-MM-DD.html) 抓取、缓存 RAW 快照并解析大宗商品现货与基差。
具备：
1. 本地 RAW 快照断点续传（Cache First）；
2. 自动处理 100ppi HW_CHECK 安全质询 Cookie 注入；
3. 非交易日自动跳过与指数退避重试防封。
"""

from __future__ import annotations

import logging
import random
import re
import time
from datetime import date, timedelta
from pathlib import Path

import requests

from stock_data.fetcher.industry.chemicals.parsers.basis_table import (
    ChemicalBasisRow,
    parse_100ppi_basis_html,
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


class SpotFuturesBasisCollector:
    """生意社大宗商品每日现期基差采集器。"""

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry/chemicals",
        session: requests.Session | None = None,
        base_url: str = "https://www.100ppi.com/sf/day-{date}.html",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.sf_raw_dir = self.raw_dir / "100ppi_sf"
        self.sf_raw_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.base_url = base_url

    def download_daily_html(
        self,
        trade_date: date,
        force: bool = False,
    ) -> tuple[Path | None, str | None]:
        """下载或读取本地缓存的每日现期表 HTML。

        Returns:
            (快照路径, 页面文本)。若为非交易日或无数据返回 (None, None)。
        """
        d_str = trade_date.isoformat()
        snapshot_path = self.sf_raw_dir / f"day-{d_str}.html"

        # 1. 本地缓存命中 (Cache First)
        if not force and snapshot_path.exists() and snapshot_path.stat().st_size > 1024:
            try:
                content = snapshot_path.read_text(encoding="utf-8")
                return snapshot_path, content
            except Exception as e:
                logger.warning(f"读取本地缓存 {snapshot_path} 失败: {e}，重新网络下载")

        # 2. 网络下载与 WAF 质询自适应
        url = self.base_url.format(date=d_str)
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.get(url, timeout=12)

                # 404 说明是非交易日（休市）或该日无归档
                if resp.status_code == 404:
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
                if len(text) > 1024 and ("fdata" in text or "商品" in text):
                    # 写入本地原子缓存
                    tmp_path = snapshot_path.with_suffix(".tmp")
                    tmp_path.write_text(text, encoding="utf-8")
                    tmp_path.replace(snapshot_path)
                    return snapshot_path, text

                # 某些无数据日页面很小或提示暂无数据
                if "暂无数据" in text or len(text) < 1000:
                    return None, None

            except requests.RequestException as exc:
                logger.warning(f"抓取 {url} 网络异常: {exc} (尝试 {attempt}/{max_retries})")
                time.sleep(attempt * 1.0)

        return None, None

    def collect_date(
        self,
        trade_date: date,
        symbols: set[str] | None = None,
        force: bool = False,
    ) -> list[ChemicalBasisRow]:
        """采集并解析单个交易日的现期基差记录。"""
        # 周末直接跳过
        if trade_date.weekday() >= 5:
            return []

        _, html = self.download_daily_html(trade_date, force=force)
        if not html:
            return []

        return parse_100ppi_basis_html(html, trade_date, target_symbols=symbols)

    def collect_date_range(
        self,
        start_date: date,
        end_date: date,
        symbols: set[str] | None = None,
        delay_seconds: float = 0.3,
        force: bool = False,
    ) -> list[ChemicalBasisRow]:
        """按时间段连续采集并解析大宗商品现期基差。"""
        all_records: list[ChemicalBasisRow] = []
        cur = start_date
        total_days = (end_date - start_date).days + 1
        processed_days = 0

        while cur <= end_date:
            processed_days += 1
            if cur.weekday() < 5:
                # 检查是否命中缓存，未命中时休眠
                d_str = cur.isoformat()
                cached = (self.sf_raw_dir / f"day-{d_str}.html").exists()

                rows = self.collect_date(cur, symbols=symbols, force=force)
                if rows:
                    all_records.extend(rows)

                if not cached and delay_seconds > 0:
                    jitter = random.uniform(delay_seconds * 0.8, delay_seconds * 1.2)
                    time.sleep(jitter)

            if processed_days % 60 == 0 or cur == end_date:
                logger.info(
                    f"回填进度: {cur.isoformat()} ({processed_days}/{total_days} 天), "
                    f"累计已获取 {len(all_records)} 条基差记录"
                )

            cur += timedelta(days=1)

        return all_records
