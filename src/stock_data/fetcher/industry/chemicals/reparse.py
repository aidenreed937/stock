"""本地周报与研报快照纯离线重构引擎 (reparse.py)。

用于在脱网或规则升级后，纯离线从所有本地快照重新抽取有效指标，
彻底根据最新防误抓规则与物理常识门禁重建 RAW weekly_survey.csv。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import pypdf

from stock_data.fetcher.industry.chemicals.collectors.cfa_futures import CFA_PROGRAM_MAPPING
from stock_data.fetcher.industry.chemicals.collectors.mysteel_backfill import (
    STANDARD_PRODUCT_MAPPINGS,
)
from stock_data.fetcher.industry.chemicals.collectors.weekly_survey import (
    ChemicalWeeklySurveyCollector,
)
from stock_data.fetcher.industry.chemicals.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.chemicals.parsers.research import ResearchReportParser
from stock_data.fetcher.industry.chemicals.parsers.weekly_survey import (
    collect_100ppi_weekly_records,
    parse_commodity_weekly_metrics,
    parse_page_release_date,
)
from stock_data.fetcher.industry.common import now_utc_iso

logger = logging.getLogger(__name__)


def reparse_all_snapshots_offline(raw_dir: Path | str) -> int:
    """纯离线从所有本地快照重新解析并物化重构 RAW weekly_survey.csv。"""
    raw_path = Path(raw_dir)
    collector = ChemicalWeeklySurveyCollector(raw_dir=raw_path)
    snapshot_dir = raw_path / "chemicals" / "operating_rates" / "snapshots"
    if not snapshot_dir.exists():
        logger.warning("快照目录不存在: %s", snapshot_dir)
        return 0

    research_parser = ResearchReportParser(raw_dir=raw_path)
    new_records: dict[tuple[str, str, str], dict[str, Any]] = {}
    now_iso = now_utc_iso()

    # 1. 解析 100ppi 快照
    for p in snapshot_dir.glob("100ppi_weekly_*.html"):
        try:
            html = p.read_text(encoding="utf-8")
            h_hash = raw_content_sha256(html.encode("utf-8"))
            snap_path_val = raw_snapshot_path_value(p, raw_path)

            def _get_cached_html(_url: str, content: str = html) -> str:
                return content

            collect_100ppi_weekly_records(
                records=new_records,
                fetch_html=_get_cached_html,
                current_year=2024,
                now_iso=now_iso,
                raw_content_sha256_value=h_hash,
                raw_snapshot_path=snap_path_val,
            )
        except Exception as exc:
            logger.debug("解析 100ppi 快照失败 %s: %s", p.name, exc)

    # 2. 解析 Mysteel 快照 (mysteel_{sym}_{date}_{hash}.html)
    for p in sorted(snapshot_dir.glob("mysteel_*.html")):
        parts = p.name.split("_")
        if len(parts) < 3:
            continue
        sym = parts[1]
        d_str = parts[2]
        p_name = STANDARD_PRODUCT_MAPPINGS.get(sym, sym)
        try:
            html = p.read_text(encoding="utf-8")
            h_hash = raw_content_sha256(html.encode("utf-8"))
            snap_path_val = raw_snapshot_path_value(p, raw_path)
            metrics = parse_commodity_weekly_metrics(html, p_name, sym)
            rel_date = parse_page_release_date(html)
            report_day = date.fromisoformat(d_str)
            key = (p_name, d_str, "Longzhong_Oilchem")
            rec = {
                "trade_date": report_day,
                "report_date": report_day,
                "product_name": p_name,
                "symbol": sym,
                "operating_rate_pct": metrics.get("operating_rate_pct"),
                "weekly_output_w_tons": metrics.get("weekly_output_w_tons"),
                "factory_inventory_w_tons": metrics.get("factory_inventory_w_tons"),
                "shipment_rate_pct": metrics.get("shipment_rate_pct"),
                "source": "Longzhong_Oilchem",
                "source_url": "",
                "release_date": rel_date or report_day,
                "data_status": "actual",
                "collected_at": now_iso,
                "raw_content_sha256": h_hash,
                "raw_snapshot_path": snap_path_val,
            }
            if any(
                rec.get(k) is not None
                for k in ("operating_rate_pct", "weekly_output_w_tons", "factory_inventory_w_tons")
            ):
                new_records[key] = rec
        except Exception as exc:
            logger.debug("解析 Mysteel 快照失败 %s: %s", p.name, exc)

    logging.getLogger("pypdf").setLevel(logging.ERROR)

    # 3. 解析 CFA China 期货研报快照 (cfachina_{sym}_{date}_{hash}.pdf)
    pdf_files = sorted(snapshot_dir.glob("cfachina_*.pdf"))
    total_pdfs = len(pdf_files)
    logger.info("开始离线重新解析 %d 份 CFA 期货研报快照...", total_pdfs)
    for idx, p in enumerate(pdf_files):
        parts = p.name.split("_")
        if len(parts) < 3:
            continue
        sym = parts[1]
        d_str = parts[2]
        p_name = CFA_PROGRAM_MAPPING.get(sym, {}).get("product_name", sym)
        try:
            content_bytes = p.read_bytes()
            h_hash = raw_content_sha256(content_bytes)
            snap_path_val = raw_snapshot_path_value(p, raw_path)
            report_day = date.fromisoformat(d_str)

            reader = pypdf.PdfReader(str(p))
            # 周报基本面核心指标均在前 10 页内，限制页数以防在深层附录损坏对象卡顿
            full_text = "\n".join(page.extract_text() or "" for page in reader.pages[:10])

            # 优先使用多品种通用 ResearchReportParser
            extracted_items = research_parser.extract_metrics_from_text(
                text=full_text,
                product_name=p_name,
                publish_date=report_day,
                source_name="CFA_Futures_Report",
                source_url="",
                raw_content_sha256=h_hash,
                raw_snapshot_path=snap_path_val,
            )
            if extracted_items:
                for item in extracted_items:
                    t_day = item["trade_date"]
                    t_d_str = t_day.isoformat() if isinstance(t_day, date) else str(t_day)
                    rec_key = (p_name, t_d_str, "CFA_Futures_Report")
                    new_records[rec_key] = item
            else:
                # 兼容降级到 parse_commodity_weekly_metrics
                metrics = parse_commodity_weekly_metrics(full_text, p_name, sym)
                if any(
                    metrics.get(k) is not None
                    for k in (
                        "operating_rate_pct",
                        "weekly_output_w_tons",
                        "factory_inventory_w_tons",
                    )
                ):
                    rec_key = (p_name, d_str, "CFA_Futures_Report")
                    new_records[rec_key] = {
                        "trade_date": report_day,
                        "report_date": report_day,
                        "product_name": p_name,
                        "symbol": sym,
                        "operating_rate_pct": metrics.get("operating_rate_pct"),
                        "weekly_output_w_tons": metrics.get("weekly_output_w_tons"),
                        "factory_inventory_w_tons": metrics.get("factory_inventory_w_tons"),
                        "shipment_rate_pct": metrics.get("shipment_rate_pct"),
                        "source": "CFA_Futures_Report",
                        "source_url": "",
                        "release_date": report_day,
                        "data_status": "actual",
                        "collected_at": now_iso,
                        "raw_content_sha256": h_hash,
                        "raw_snapshot_path": snap_path_val,
                    }
        except Exception as exc:
            logger.debug("解析 CFA 快照失败 %s: %s", p.name, exc)

        if (idx + 1) % 200 == 0 or (idx + 1) == total_pdfs:
            logger.info("CFA 研报快照解析进度: %d/%d", idx + 1, total_pdfs)

    collector._save_raw_csv(new_records)
    logger.info("离线重构 RAW CSV 完成，纯净有效记录数: %d", len(new_records))
    return len(new_records)


__all__ = ["reparse_all_snapshots_offline"]
