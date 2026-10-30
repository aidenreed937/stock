"""中国期货业协会 (CFA China) 官方研报快讯采集与回填器 (CFAFuturesReportCollector)。

负责:
1. 通过中国期货业协会官方 REST 接口自动发现真实期货研究所周报;
2. 下载 PDF 并落盘至 data/raw/industry/chemicals/operating_rates/snapshots/;
3. 驱动多品种 ResearchReportParser 提取开工率、企业库存与产量指标;
4. 增量写入 data/raw/industry/chemicals/operating_rates/weekly_survey.csv。
"""

from __future__ import annotations

import io
import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import pypdf
from curl_cffi import requests

from stock_data.fetcher.industry.chemicals.collectors.weekly_survey import (
    ChemicalWeeklySurveyCollector,
)
from stock_data.fetcher.industry.chemicals.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.chemicals.parsers.research import ResearchReportParser

logger = logging.getLogger(__name__)

CFA_PROGRAM_MAPPING: dict[str, dict[str, str]] = {
    "SA": {"program": "纯碱_5769", "product_name": "纯碱", "symbol": "SA"},
    "TA": {"program": "PTA_5763", "product_name": "精对苯二甲酸", "symbol": "TA"},
    "MA": {"program": "甲醇_5764", "product_name": "甲醇", "symbol": "MA"},
    "V": {"program": "聚氯乙烯_5771", "product_name": "聚氯乙烯", "symbol": "V"},
    "MEG": {"program": "乙二醇_5776", "product_name": "乙二醇", "symbol": "MEG"},
    "UR": {"program": "尿素_5774", "product_name": "尿素", "symbol": "UR"},
    "SH": {"program": "烧碱_5780", "product_name": "烧碱", "symbol": "SH"},
}

CFA_REST_API_URL = "https://www.cfachina.org/qx-search/api/wcmSearch/getDataByProgram"


class CFAFuturesReportCollector:
    """中国期货业协会官方研报收集器。"""

    def __init__(self, raw_dir: Path | str) -> None:
        self.raw_dir = Path(raw_dir)
        self.survey_dir = self.raw_dir / "chemicals" / "operating_rates"
        self.snapshot_dir = self.survey_dir / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.collector = ChemicalWeeklySurveyCollector(raw_dir=self.raw_dir)
        self.research_parser = ResearchReportParser(raw_dir=self.raw_dir)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

    def discover_reports(
        self,
        symbol: str,
        max_pages: int = 15,
        page_size: int = 20,
    ) -> list[dict[str, Any]]:
        """通过中国期货业协会官方 REST API 发现研报列表。"""
        cfg = CFA_PROGRAM_MAPPING.get(symbol.upper())
        if not cfg:
            logger.warning("未知的 CFA 品种代码: %s", symbol)
            return []

        program_name = cfg["program"]
        discovered: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        for page_no in range(1, max_pages + 1):
            params = {
                "pageNo": page_no,
                "pageSize": page_size,
                "programName": program_name,
            }
            try:
                resp = requests.get(
                    CFA_REST_API_URL, params=params, headers=self.headers, timeout=12
                )
                if resp.status_code != 200:
                    logger.warning("CFA API 响应非 200 (HTTP %d, 页 %d)", resp.status_code, page_no)
                    break
                data = resp.json()
                data_list = data.get("data", {}).get("dataList") or []
                if not data_list:
                    break

                for item in data_list:
                    doc_url = str(item.get("docPubUrl") or "").strip()
                    if not doc_url.lower().endswith(".pdf"):
                        continue
                    if not doc_url.startswith("http"):
                        doc_url = (
                            "https://www.cfachina.org"
                            + ("/" if not doc_url.startswith("/") else "")
                            + doc_url
                        )

                    if doc_url in seen_urls:
                        continue
                    seen_urls.add(doc_url)

                    title = str(item.get("docTitle") or "").strip()
                    rel_time = str(item.get("docRelTime") or "").strip()
                    m_date = re.search(r"(\d{4})[-/.](\d{2})[-/.](\d{2})", rel_time)
                    p_date_str = (
                        f"{m_date.group(1)}-{m_date.group(2)}-{m_date.group(3)}" if m_date else None
                    )
                    if not p_date_str:
                        m_href_date = re.search(r"P0?(\d{4})(\d{2})(\d{2})", doc_url)
                        p_date_str = (
                            f"{m_href_date.group(1)}-{m_href_date.group(2)}-{m_href_date.group(3)}"
                            if m_href_date
                            else None
                        )

                    if p_date_str:
                        discovered.append(
                            {
                                "title": title,
                                "url": doc_url,
                                "publish_date": p_date_str,
                                "author": str(item.get("docAuthor") or ""),
                                "source_name": str(
                                    item.get("docSourceName") or "CFA_Futures_Report"
                                ),
                            }
                        )
            except Exception as exc:
                logger.warning("请求 CFA API 第 %d 页异常: %s", page_no, exc)
                break

        logger.info("CFA 专栏 [%s] 共发现 %d 篇研报 PDF", program_name, len(discovered))
        return discovered

    def backfill_and_parse(
        self,
        reports: list[dict[str, Any]],
        symbol: str,
        product_name: str,
        force: bool = False,
        max_count: int | None = None,
    ) -> int:
        """批量下载研报 PDF 并通过 ResearchReportParser 提取指标入库。"""
        existing_records = self.collector._load_raw_csv()
        newly_added = 0

        items = sorted(reports, key=lambda x: x["publish_date"], reverse=True)
        if max_count is not None:
            items = items[:max_count]

        total_tasks = len(items)
        for idx, rep in enumerate(items, start=1):
            p_date_str = rep["publish_date"]
            p_date = date.fromisoformat(p_date_str)
            title = rep["title"]
            url = rep["url"]
            source_label = (
                "CFA_Futures_Report:Longzhong" if symbol == "SA" else "CFA_Futures_Report"
            )

            key = (product_name, p_date_str, source_label)
            if (
                not force
                and key in existing_records
                and existing_records[key].get("operating_rate_pct")
            ):
                continue

            logger.info(
                "[%d/%d] 真实处理期货研报 (%s-%s): %s", idx, total_tasks, symbol, p_date_str, title
            )
            content_bytes = b""
            snap_path_val = ""
            h_hash = ""

            # 优先读取本地已有快照
            existing_snaps = list(self.snapshot_dir.glob(f"cfachina_{symbol}_{p_date_str}_*.pdf"))
            if existing_snaps and not force:
                try:
                    snap_file = existing_snaps[0]
                    content_bytes = snap_file.read_bytes()
                    h_hash = raw_content_sha256(content_bytes)
                    snap_path_val = raw_snapshot_path_value(snap_file, self.raw_dir)
                except Exception as exc:
                    logger.debug("读取本地快照失败: %s", exc)

            if not content_bytes:
                try:
                    resp = requests.get(url, impersonate="chrome120", timeout=20)
                    if resp.status_code != 200:
                        logger.warning("抓取 PDF 失败 (HTTP %d): %s", resp.status_code, url)
                        continue
                    content_bytes = resp.content
                    h_hash = raw_content_sha256(content_bytes)
                    snap_file = (
                        self.snapshot_dir / f"cfachina_{symbol}_{p_date_str}_{h_hash[:16]}.pdf"
                    )
                    if not snap_file.exists():
                        snap_file.write_bytes(content_bytes)
                    snap_path_val = raw_snapshot_path_value(snap_file, self.raw_dir)
                except Exception as exc:
                    logger.warning("下载 PDF 异常 [%s]: %s", url, exc)
                    continue

            try:
                logging.getLogger("pypdf").setLevel(logging.ERROR)
                reader = pypdf.PdfReader(io.BytesIO(content_bytes))
                # 周报供需核心数据均在前 10 页内，限制页数以防深层附录损坏对象拖慢耗时
                full_text = "\n".join(page.extract_text() or "" for page in reader.pages[:10])

                extracted_items = self.research_parser.extract_metrics_from_text(
                    text=full_text,
                    product_name=product_name,
                    publish_date=p_date,
                    source_name=source_label,
                    source_url=url,
                    raw_content_sha256=h_hash,
                    raw_snapshot_path=snap_path_val,
                )

                for item in extracted_items:
                    t_day = item["trade_date"]
                    d_str = t_day.isoformat() if isinstance(t_day, date) else str(t_day)
                    rec_key = (product_name, d_str, source_label)
                    if rec_key in existing_records:
                        rec = existing_records[rec_key]
                        updated = False
                        if (
                            rec.get("operating_rate_pct") is None
                            and item.get("operating_rate_pct") is not None
                        ):
                            rec["operating_rate_pct"] = item["operating_rate_pct"]
                            updated = True
                        if (
                            rec.get("factory_inventory_w_tons") is None
                            and item.get("factory_inventory_w_tons") is not None
                        ):
                            rec["factory_inventory_w_tons"] = item["factory_inventory_w_tons"]
                            updated = True
                        if (
                            rec.get("weekly_output_w_tons") is None
                            and item.get("weekly_output_w_tons") is not None
                        ):
                            rec["weekly_output_w_tons"] = item["weekly_output_w_tons"]
                            updated = True
                        if updated:
                            rec["raw_content_sha256"] = h_hash
                            rec["raw_snapshot_path"] = snap_path_val
                            newly_added += 1
                    else:
                        existing_records[rec_key] = item
                        newly_added += 1

                time.sleep(0.05)
            except Exception as exc:
                logger.warning("解析 PDF %s 出错: %s", url, exc)

        self.collector._save_raw_csv(existing_records)
        logger.info(
            "CFA %s 研报提取完成，当前 RAW CSV 总记录数: %d, 新增/更新: %d",
            symbol,
            len(existing_records),
            newly_added,
        )
        return newly_added


__all__ = [
    "CFA_PROGRAM_MAPPING",
    "CFA_REST_API_URL",
    "CFAFuturesReportCollector",
]
