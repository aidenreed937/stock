"""巨潮资讯 (CNINFO) 纯碱重大产能公告在线采集器。

基于深交所/上交所官方信息披露平台 (cninfo.com.cn) 公开接口，
定向检索纯碱核心上市公司（远兴能源、中盐化工、山东海化等）关于投料、试车、二期、达产等重大产能事件。
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from curl_cffi import requests

from stock_data.fetcher.industry.chemicals.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
)

logger = logging.getLogger(__name__)

# 默认监控的纯碱核心上市公司 (A 股)
DEFAULT_SODA_ASH_STOCKS = [
    {"secCode": "000683", "column": "szse", "name": "远兴能源"},
    {"secCode": "600328", "column": "sse", "name": "中盐化工"},
    {"secCode": "000822", "column": "szse", "name": "山东海化"},
    {"secCode": "600409", "column": "sse", "name": "三友化工"},
    {"secCode": "000707", "column": "szse", "name": "双环科技"},
]

DEFAULT_KEYWORDS = "天然碱 投料 试车 达产 二期 项目 技改"


class CninfoAnnouncementCollector:
    """巨潮资讯公告在线检索与抓取器。"""

    CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    CNINFO_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search&lastPage=index",
        "Origin": "https://www.cninfo.com.cn",
        "X-Requested-With": "XMLHttpRequest",
    }

    def __init__(
        self,
        raw_dir: Path | str = "data/raw/industry/chemicals/capacity/announcements",
        raw_root: Path | str = "data/raw",
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.raw_root = Path(raw_root)
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def fetch_announcements_for_stock(
        self,
        sec_code: str,
        column: str = "szse",
        keywords: str | list[str] = DEFAULT_KEYWORDS,
        start_date: date | str = "2023-01-01",
        end_date: date | str | None = None,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """定向检索指定股票的重大事件公告（支持多关键词轮询与去重）。"""
        s_date = date.fromisoformat(str(start_date)) if isinstance(start_date, str) else start_date
        e_date = (
            date.fromisoformat(str(end_date))
            if isinstance(end_date, str)
            else (end_date or date.today())
        )

        kw_list = keywords.split() if isinstance(keywords, str) else list(keywords)
        seen_ids: set[str] = set()
        announcements: list[dict[str, Any]] = []

        for kw in kw_list:
            # CNINFO searchkey 包含代码与单关键词
            effective_searchkey = f"{sec_code} {kw}".strip()
            payload = {
                "pageNum": "1",
                "pageSize": str(page_size),
                "column": column,
                "tabName": "fulltext",
                "plate": "",
                "stock": "",
                "searchkey": effective_searchkey,
                "secid": "",
                "category": "",
                "trade": "",
                "seDate": f"{s_date.isoformat()}~{e_date.isoformat()}",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "false",
            }

            try:
                resp = requests.post(
                    self.CNINFO_QUERY_URL,
                    headers=self.CNINFO_HEADERS,
                    data=payload,
                    impersonate="chrome120",
                    timeout=15,
                )
                if resp.status_code == 200:
                    content_bytes = resp.content
                    sha = raw_content_sha256(content_bytes)

                    snapshot_name = (
                        f"cninfo_{sec_code}_{kw}_{s_date.isoformat()}_{e_date.isoformat()}.json"
                    )
                    snapshot_path = self.raw_dir / snapshot_name
                    snapshot_path.write_bytes(content_bytes)

                    data = json.loads(resp.text)
                    raw_items = data.get("announcements") or []
                    for item in raw_items:
                        aid = item.get("announcementId") or item.get("announcementTitle")
                        if aid and aid not in seen_ids:
                            seen_ids.add(aid)
                            item["_raw_content_sha256"] = sha
                            item["_raw_snapshot_path"] = raw_snapshot_path_value(
                                snapshot_path, self.raw_root
                            )
                            announcements.append(item)
                else:
                    logger.warning(
                        "巨潮资讯公告接口响应异常: HTTP %d (代码=%s, 关键词=%s)",
                        resp.status_code,
                        sec_code,
                        kw,
                    )
            except Exception as exc:
                logger.warning("检索巨潮资讯公告异常 (代码=%s, 关键词=%s): %s", sec_code, kw, exc)

        logger.info("代码=%s 检索完成，共命中 %d 条去重公告", sec_code, len(announcements))
        return announcements

    def fetch_all_soda_ash_announcements(
        self,
        stocks: list[dict[str, str]] | None = None,
        keywords: str = DEFAULT_KEYWORDS,
        start_date: date | str = "2023-01-01",
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        """批量获取核心纯碱上市公司的相关公告列表。"""
        target_stocks = stocks or DEFAULT_SODA_ASH_STOCKS
        all_announcements: list[dict[str, Any]] = []
        for s in target_stocks:
            res = self.fetch_announcements_for_stock(
                sec_code=s["secCode"],
                column=s.get("column", "szse"),
                keywords=keywords,
                start_date=start_date,
                end_date=end_date,
            )
            all_announcements.extend(res)

        # 按公告时间倒序排列
        all_announcements.sort(key=lambda x: x.get("announcementTime", 0), reverse=True)
        return all_announcements
