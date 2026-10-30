"""基础化工周度调查数据历史回填自动化编排脚本 (backfill_chemical_weekly_survey.py)。

涵盖:
1. 驱动 Mysteel 纯碱等能化周数据分析文章发现与快照回填;
2. 驱动中国期货业协会 (CFA China) 官方 REST 研报发现与多品种指标批量提取;
3. 驱动离线快照重构与 RAW CSV 净化引擎 (reparse_all_snapshots_offline);
4. 触发端点转换生成 data/curated/industry/chemical_weekly_survey.parquet 并输出覆盖率审计。
"""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path

import duckdb

from stock_data.fetcher.industry.chemicals.collectors.cfa_futures import (
    CFA_PROGRAM_MAPPING,
    CFAFuturesReportCollector,
)
from stock_data.fetcher.industry.chemicals.collectors.mysteel_backfill import (
    MysteelWeeklyBackfiller,
)
from stock_data.fetcher.industry.chemicals.registry import ENDPOINT_SPECS
from stock_data.fetcher.industry.chemicals.reparse import reparse_all_snapshots_offline
from stock_data.fetcher.industry.contracts import IndustryRunContext
from stock_data.fetcher.industry.runner import run_endpoint

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_pipeline() -> None:
    """触发 chemical_weekly_survey 端点构建黄金事实表。"""
    raw_dir = Path("data/raw/industry")
    curated_dir = Path("data/curated/industry")
    endpoint_spec = next(s for s in ENDPOINT_SPECS if s.endpoint == "chemical_weekly_survey")
    context = IndustryRunContext(
        endpoint="chemical_weekly_survey",
        raw_dir=raw_dir,
        curated_dir=curated_dir,
    )
    result = run_endpoint(endpoint_spec, context)
    records_count = (
        result.records
        if isinstance(result.records, int)
        else (len(result.records) if result.records is not None else 0)
    )
    logger.info("端点同步完成: status=%s, 记录条数=%d", result.status, records_count)


def print_summary(curated_dir: Path) -> None:
    """输出 Curated 黄金事实表覆盖率总览。"""
    parquet_path = curated_dir / "chemical_weekly_survey.parquet"
    if not parquet_path.exists():
        logger.warning("未找到产物文件: %s", parquet_path)
        return

    con = duckdb.connect()
    df_summary = con.execute(f"""
        SELECT
            product_name,
            symbol,
            min(trade_date) AS start_date,
            max(trade_date) AS end_date,
            count(*) AS total_records,
            count(operating_rate_pct) AS non_null_util,
            count(factory_inventory_w_tons) AS non_null_inv,
            count(weekly_output_w_tons) AS non_null_out
        FROM '{parquet_path}'
        GROUP BY product_name, symbol
        ORDER BY symbol
    """).df()

    logger.info("\n=== 黄金事实表覆盖率总览 (全品种) ===\n%s", df_summary.to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="回填化工周度高频产业调查数据")
    parser.add_argument(
        "--source", choices=["all", "mysteel", "cfa"], default="all", help="执行源通道"
    )
    parser.add_argument(
        "--symbol",
        default="all",
        help="指定回填的品种符号 (ALL, NON_SA, SA, TA, MEG, MA, V, TiO2)",
    )
    parser.add_argument("--mysteel-pages", type=int, default=3, help="Mysteel 扫描列表页数")
    parser.add_argument("--cfa-pages", type=int, default=35, help="CFA China 扫描列表页数")
    parser.add_argument("--max-fetch", type=int, default=None, help="最大抓取研报数")
    parser.add_argument("--force", action="store_true", help="强制覆盖已存在数据")
    parser.add_argument(
        "--reparse-offline", action="store_true", help="仅从本地已下载快照离线重新解析并物化"
    )
    args = parser.parse_args()

    raw_dir = Path("data/raw/industry")
    curated_dir = Path("data/curated/industry")
    config_csv = Path("config/data_sources/chemicals_weekly_sources.csv")

    if args.reparse_offline:
        logger.info("=== 执行纯离线快照重放与 RAW CSV 净化 ===")
        reparse_all_snapshots_offline(raw_dir)
        logger.info("=== 触发端点管线同步生成 Curated 黄金表 ===")
        curated_parquet = curated_dir / "chemical_weekly_survey.parquet"
        if curated_parquet.exists():
            curated_parquet.unlink()
        run_pipeline()
        logger.info("=== 打印产物审计与统计分析 ===")
        print_summary(curated_dir)
        return

    if args.source in ("all", "mysteel"):
        logger.info("=== 阶段 1: 读取 Mysteel 周报清单并执行回填解析 ===")
        all_sources: list[dict[str, str]] = []
        if config_csv.exists():
            with config_csv.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                all_sources = list(reader)

        backfiller = MysteelWeeklyBackfiller(raw_dir=raw_dir)
        target_sym = args.symbol.upper()
        if target_sym in ("ALL", "SA"):
            discovered_mysteel = backfiller.discover_soda_ash_articles(max_pages=args.mysteel_pages)
            if discovered_mysteel:
                backfiller.sync_sources_csv(discovered_mysteel, config_csv)

        backfiller.backfill_and_parse(
            sources=all_sources,
            force=args.force,
            max_count=args.max_fetch,
            target_symbol=args.symbol,
        )

    if args.source in ("all", "cfa"):
        logger.info("=== 阶段 2: 扫描并解析 CFA 期货研报历史周报 (官方 REST API) ===")
        cfa_collector = CFAFuturesReportCollector(raw_dir=raw_dir)
        target_sym = args.symbol.upper()
        if target_sym == "NON_SA":
            cfa_symbols = ["TA", "MEG", "MA", "V"]
        elif target_sym == "ALL":
            cfa_symbols = list(CFA_PROGRAM_MAPPING.keys())
        elif target_sym in CFA_PROGRAM_MAPPING:
            cfa_symbols = [target_sym]
        else:
            cfa_symbols = []

        for c_sym in cfa_symbols:
            cfg = CFA_PROGRAM_MAPPING[c_sym]
            p_name = cfg["product_name"]
            cfa_reports = cfa_collector.discover_reports(c_sym, max_pages=args.cfa_pages)
            if cfa_reports:
                cfa_collector.backfill_and_parse(
                    reports=cfa_reports,
                    symbol=c_sym,
                    product_name=p_name,
                    force=args.force,
                    max_count=args.max_fetch,
                )

    logger.info("=== 阶段 3: 触发端点管线同步生成 Curated 黄金表 ===")
    curated_parquet = curated_dir / "chemical_weekly_survey.parquet"
    if curated_parquet.exists():
        curated_parquet.unlink()
    run_pipeline()

    logger.info("=== 阶段 4: 打印产物审计与统计分析 ===")
    print_summary(curated_dir)


if __name__ == "__main__":
    main()
