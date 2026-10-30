"""东方财富化工产业研报自动化采集与关键产能页抽取 CLI 工具。

用法:
    uv run python scripts/fetch_chemical_industry_reports.py --products caustic_soda,pvc,pta --max-pages 5
    uv run python scripts/fetch_chemical_industry_reports.py --products all --max-pages 10
"""

from __future__ import annotations

import argparse
import logging
import sys

from stock_data.fetcher.industry.chemicals.collectors.eastmoney_report import (
    CHEMICAL_PRODUCT_KEYWORDS,
    EastmoneyReportCollector,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fetch_reports")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="东方财富化工研报采集与产能段落抽取工具")
    parser.add_argument(
        "--products",
        type=str,
        default="caustic_soda,pvc,pta,methanol,urea,plate_glass",
        help="目标品种代码 (逗号分隔，或传 all)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="东财研报时间流检索页数 (每页 50 篇，默认 5)",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="仅获取研报元数据列表，不实际下载 PDF 物理快照",
    )
    parser.add_argument(
        "--raw-pdf-dir",
        type=str,
        default="data/raw/industry/chemicals/capacity/raw_pdfs",
        help="PDF 物理快照与 manifest 存储路径",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.products.lower() == "all":
        products = list(CHEMICAL_PRODUCT_KEYWORDS.keys())
    else:
        products = [p.strip() for p in args.products.split(",") if p.strip()]

    logger.info("================ 东方财富化工研报采集流水线 ================")
    logger.info(f"监控目标品种: {products}")
    logger.info(f"检索页数深度: {args.max_pages} 页 (约 {args.max_pages * 50} 篇全行业报告)")
    logger.info(f"物理存证目录: {args.raw_pdf_dir}")
    logger.info("============================================================")

    collector = EastmoneyReportCollector(raw_pdf_dir=args.raw_pdf_dir)
    records = collector.sync_and_extract(
        target_products=products,
        max_pages=args.max_pages,
        download_pdfs=not args.no_download,
    )

    logger.info("\n======================== 采集与对账汇总 ========================")
    logger.info(f"共捕获并处理目标化工研报: {len(records)} 篇")

    hit_count = 0
    for r in records:
        sec_count = len(r.extracted_sections)
        if sec_count > 0:
            hit_count += 1
        logger.info(
            f"  - [{r.publish_date}] {r.org_name}: 《{r.title}》 "
            f"| 涉及品种: {r.matched_products} "
            f"| 命中产能关键页: {sec_count} 页 "
            f"| 文件大小: {r.file_size_kb} KB"
        )
        if r.sha256:
            logger.info(f"    SHA-256 哈希: {r.sha256}")
        for sec in r.extracted_sections[:2]:
            kws = sec.get("matched_keywords") or []
            logger.info(f"    [P.{sec.get('page_number')} 关键段落样例] (触发词: {list(kws)[:3]}):")
            for line in str(sec.get("snippet", "")).splitlines()[:3]:
                logger.info(f"      > {line}")

    logger.info("============================================================")
    logger.info(f"命中包含产能/供需数据的报告: {hit_count}/{len(records)} 篇")
    logger.info(f"存证清单 Manifest: {collector.manifest_path}")
    logger.info("============================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
