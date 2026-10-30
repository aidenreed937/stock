"""Mysteel / 隆众大宗化工周评快讯自动化回填器 (MysteelWeeklyBackfiller)。

负责:
1. 扫描 Mysteel 纯碱等化工品官方专栏列表页，提取周评链接与标题;
2. 增量同步配置清单至 config/data_sources/chemicals_weekly_sources.csv;
3. 批量下载快照 (含 429 频控重试与防封休眠机制) 并固化哈希;
4. 驱动 parse_commodity_weekly_metrics 提取指标并增量更新 weekly_survey.csv。
"""

from __future__ import annotations

import csv
import logging
import random
import re
import time
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup
from curl_cffi import requests

from stock_data.fetcher.industry.chemicals.collectors.weekly_survey import (
    ChemicalWeeklySurveyCollector,
)
from stock_data.fetcher.industry.chemicals.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.chemicals.parsers.weekly_survey import (
    parse_commodity_weekly_metrics,
    parse_page_release_date,
)
from stock_data.fetcher.industry.common import now_utc_iso

logger = logging.getLogger(__name__)

SODA_ASH_LIST_URL_TEMPLATE = (
    "https://nenghua.mysteel.com/list/article/pa11297a041301,160103aaaaa{page}.html"
)

STANDARD_PRODUCT_MAPPINGS: dict[str, str] = {
    "SA": "纯碱",
    "TA": "精对苯二甲酸",
    "MEG": "乙二醇",
    "MA": "甲醇",
    "V": "聚氯乙烯",
    "TIO2": "钛白粉",
    "UR": "尿素",
    "SH": "烧碱",
    "EB": "苯乙烯",
    "PP": "聚丙烯",
    "PX": "对二甲苯",
}


class MysteelWeeklyBackfiller:
    """Mysteel 周报列表扫描与快照批量回填器。"""

    def __init__(self, raw_dir: Path | str) -> None:
        self.raw_dir = Path(raw_dir)
        self.survey_dir = self.raw_dir / "chemicals" / "operating_rates"
        self.snapshot_dir = self.survey_dir / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.collector = ChemicalWeeklySurveyCollector(raw_dir=self.raw_dir)

    def discover_soda_ash_articles(self, max_pages: int = 3) -> dict[str, tuple[str, str]]:
        """扫描 Mysteel 纯碱专栏列表页，提取周报日期、标题与 URL。"""
        discovered: dict[str, tuple[str, str]] = {}
        for page in range(1, max_pages + 1):
            url = SODA_ASH_LIST_URL_TEMPLATE.format(page=page)
            logger.info("扫描 Mysteel 纯碱专栏第 %d 页: %s", page, url)
            try:
                resp = requests.get(url, impersonate="chrome120", timeout=12)
                if resp.status_code != 200:
                    logger.warning("请求列表页失败 (HTTP %d): %s", resp.status_code, url)
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", href=re.compile(r"/a/\d+/[A-F0-9]+\.html")):
                    title = a.get_text().strip()
                    href = str(a.get("href") or "")
                    if "纯碱" in title and "产量周数据分析" in title:
                        m_date = re.search(r"（(\d{8})", title)
                        if m_date:
                            d_raw = m_date.group(1)
                            d_str = f"{d_raw[:4]}-{d_raw[4:6]}-{d_raw[6:8]}"
                            if d_str not in discovered:
                                discovered[d_str] = (title, href)
            except Exception as exc:
                logger.warning("扫描第 %d 页遇到异常: %s", page, exc)
        logger.info("Mysteel 共发现 %d 篇纯碱周数据分析文章", len(discovered))
        return discovered

    def sync_sources_csv(
        self,
        discovered: dict[str, tuple[str, str]],
        config_csv: Path,
    ) -> int:
        """增量合并文章链接至 config/data_sources/chemicals_weekly_sources.csv。"""
        existing_keys: set[tuple[str, str, str]] = set()
        rows: list[dict[str, str]] = []
        if config_csv.exists():
            with config_csv.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    p_name = r.get("product_name", "")
                    d_str = r.get("report_date", "")
                    sym = r.get("symbol", "")
                    existing_keys.add((p_name, sym, d_str))
                    rows.append(r)

        added_count = 0
        for d_str, (_, href) in sorted(discovered.items()):
            key = ("纯碱", "SA", d_str)
            if key not in existing_keys:
                rows.append(
                    {
                        "product_name": "纯碱",
                        "symbol": "SA",
                        "report_date": d_str,
                        "source_url": href,
                    }
                )
                existing_keys.add(key)
                added_count += 1

        rows.sort(key=lambda r: (r["product_name"], r["report_date"]), reverse=True)
        config_csv.parent.mkdir(parents=True, exist_ok=True)
        with config_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["product_name", "symbol", "report_date", "source_url"]
            )
            writer.writeheader()
            writer.writerows(rows)

        logger.info(
            "已向 %s 增量写入 %d 条新周报源配置，总配置数: %d",
            config_csv,
            added_count,
            len(rows),
        )
        return added_count

    def backfill_and_parse(
        self,
        sources: dict[str, tuple[str, str]] | list[dict[str, str]],
        force: bool = False,
        max_count: int | None = None,
        target_symbol: str | None = None,
    ) -> int:
        """抓取 Mysteel/隆众周报快照并通用解析开工率、产量与库存指标。"""
        existing_records = self.collector._load_raw_csv()
        now_iso = now_utc_iso()
        newly_added = 0

        tasks: list[dict[str, str]] = []
        if isinstance(sources, dict):
            for d_str, (title, url) in sources.items():
                tasks.append(
                    {
                        "product_name": "纯碱",
                        "symbol": "SA",
                        "report_date": d_str,
                        "source_url": url,
                        "title": title,
                    }
                )
        else:
            for item in sources:
                sym = item.get("symbol", "").strip().upper()
                p_name = STANDARD_PRODUCT_MAPPINGS.get(sym, item.get("product_name", ""))
                tasks.append(
                    {
                        "product_name": p_name,
                        "symbol": sym,
                        "report_date": item.get("report_date", ""),
                        "source_url": item.get("source_url", ""),
                        "title": item.get("title", f"{p_name}周度数据分析"),
                    }
                )

        if target_symbol and target_symbol.upper() != "ALL":
            target_upper = target_symbol.upper()
            if target_upper == "NON_SA":
                tasks = [t for t in tasks if t["symbol"].upper() in ("TA", "MEG", "MA", "V")]
            else:
                symbols_set = {s.strip() for s in target_upper.split(",")}
                tasks = [t for t in tasks if t["symbol"].upper() in symbols_set]

        tasks.sort(key=lambda x: (x["product_name"], x["report_date"]), reverse=True)
        if max_count is not None:
            tasks = tasks[:max_count]

        total_tasks = len(tasks)
        for idx, t in enumerate(tasks, start=1):
            prod_name = t["product_name"]
            sym = t["symbol"]
            d_str = t["report_date"]
            url = t["source_url"]
            title = t["title"]
            source_name = "100PPI" if "100ppi" in url else "Longzhong_Oilchem"
            prefix = "100ppi" if "100ppi" in url else "mysteel"

            key = (prod_name, d_str, source_name)
            if (
                not force
                and key in existing_records
                and existing_records[key].get("operating_rate_pct")
            ):
                continue

            logger.info(
                "[%d/%d] 处理周报源 (%s-%s, %s): %s",
                idx,
                total_tasks,
                sym,
                d_str,
                source_name,
                title,
            )
            html_text = ""
            h_hash = ""
            snap_path_val = ""

            # 1. 优先查找本地已有匹配快照
            existing_snaps = list(self.snapshot_dir.glob(f"*{sym}_{d_str}_*.html"))
            if existing_snaps and not force:
                try:
                    html_text = existing_snaps[0].read_text(encoding="utf-8")
                    snap_file = existing_snaps[0]
                    content_bytes = html_text.encode("utf-8")
                    h_hash = raw_content_sha256(content_bytes)
                    snap_path_val = raw_snapshot_path_value(snap_file, self.raw_dir)
                except Exception as exc:
                    logger.debug("读取本地快照失败: %s", exc)

            # 2. 本地无快照且允许在线时抓取
            if not html_text:
                time.sleep(random.uniform(2.5, 4.5))
                if newly_added > 0 and newly_added % 10 == 0:
                    logger.info("已连续抓取 10 篇新文章，主动休眠 6 秒冷却...")
                    time.sleep(6.0)
                try:
                    resp = requests.get(url, impersonate="chrome120", timeout=15)
                    if resp.status_code == 200:
                        html_text = resp.text
                    elif resp.status_code in (429, 451, 403):
                        logger.warning(
                            "抓取遇到频控 (HTTP %d)，等待 6 秒重试: %s", resp.status_code, url
                        )
                        time.sleep(6.0)
                        resp_retry = requests.get(url, impersonate="chrome120", timeout=15)
                        if resp_retry.status_code == 200:
                            html_text = resp_retry.text
                        else:
                            logger.warning("重试仍失败 (HTTP %d): %s", resp_retry.status_code, url)
                            continue
                    else:
                        logger.warning("抓取失败 (HTTP %d): %s", resp.status_code, url)
                        continue

                    if html_text:
                        content_bytes = html_text.encode("utf-8")
                        h_hash = raw_content_sha256(content_bytes)
                        snap_file = self.snapshot_dir / f"{prefix}_{sym}_{d_str}_{h_hash[:16]}.html"
                        if not snap_file.exists():
                            snap_file.write_bytes(content_bytes)
                        snap_path_val = raw_snapshot_path_value(snap_file, self.raw_dir)
                except Exception as exc:
                    logger.warning("抓取网络异常 [%s]: %s", url, exc)
                    continue

            if not html_text:
                continue

            metrics = parse_commodity_weekly_metrics(html_text, prod_name, sym)
            rel_date = parse_page_release_date(html_text)
            report_day = date.fromisoformat(d_str)

            record = existing_records.get(
                key,
                {
                    "trade_date": report_day,
                    "report_date": report_day,
                    "product_name": prod_name,
                    "symbol": sym,
                    "operating_rate_pct": None,
                    "weekly_output_w_tons": None,
                    "factory_inventory_w_tons": None,
                    "shipment_rate_pct": None,
                    "source": source_name,
                    "source_url": url,
                    "release_date": rel_date,
                    "data_status": "actual",
                    "collected_at": now_iso,
                    "raw_content_sha256": h_hash,
                    "raw_snapshot_path": snap_path_val,
                },
            )
            record["raw_content_sha256"] = h_hash
            record["raw_snapshot_path"] = snap_path_val
            record["release_date"] = rel_date or report_day
            if "data_status" not in record:
                record["data_status"] = "actual"

            if metrics.get("operating_rate_pct") is not None:
                record["operating_rate_pct"] = metrics["operating_rate_pct"]
            if metrics.get("weekly_output_w_tons") is not None:
                record["weekly_output_w_tons"] = metrics["weekly_output_w_tons"]
            if metrics.get("factory_inventory_w_tons") is not None:
                record["factory_inventory_w_tons"] = metrics["factory_inventory_w_tons"]
            if metrics.get("shipment_rate_pct") is not None:
                record["shipment_rate_pct"] = metrics["shipment_rate_pct"]

            existing_records[key] = record
            newly_added += 1

            time.sleep(0.05)

        self.collector._save_raw_csv(existing_records)
        logger.info(
            "Mysteel 解析完成，当前 RAW CSV 总记录数: %d, 新增/更新: %d",
            len(existing_records),
            newly_added,
        )
        return newly_added


__all__ = [
    "SODA_ASH_LIST_URL_TEMPLATE",
    "STANDARD_PRODUCT_MAPPINGS",
    "MysteelWeeklyBackfiller",
]
