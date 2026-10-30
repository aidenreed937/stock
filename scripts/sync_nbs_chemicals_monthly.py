#!/usr/bin/env python3
"""国家统计局 (NBS) 化工大宗与建材实物月度产量自动同步脚本。

基于升级后的 ``ChemicalCapacityUtilization10Y`` 与 ``NbsChemicalsCrawler``，
执行 2-Tier 统一存储流程：
1. 自动探测或定向抓取 NBS 官方月度实物产量；
2. 固化带 SHA-256 的原始快照 (.json.gz)；
3. 原子追加合并至统一底层 ``data/raw/industry/chemicals/data.parquet``；
4. 自动物化刷新黄金事实表 ``data/curated/industry/chemical_capacity_utilization_10y.parquet``。
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.chemicals.collectors.capacity import (
    ChemicalCapacityUtilization10Y,
)
from stock_data.fetcher.industry.common import parse_month_string

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sync_nbs_monthly")

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = WORKSPACE_ROOT / "data" / "raw" / "industry"
DEFAULT_PRODUCTS = ["纯碱", "平板玻璃", "烧碱"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="国家统计局 (NBS) 化工实物产量月度增量同步并物化 Parquet 底座"
    )
    parser.add_argument(
        "--month",
        type=str,
        default=None,
        help="目标报告月份 (YYYY-MM)，不传则自动探测缺失月份",
    )
    parser.add_argument(
        "--products",
        nargs="+",
        default=DEFAULT_PRODUCTS,
        help=f"同步产品列表 (默认: {' '.join(DEFAULT_PRODUCTS)})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新拉取并覆盖已有月份",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help="RAW 根目录路径 (默认: data/raw/industry)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    start_date: date | None = None
    end_date: date | None = None
    if args.month:
        try:
            yr, mo = parse_month_string(args.month)
            start_date = date(yr, mo, 1)
            end_date = date(yr, mo, 1)
        except Exception as exc:
            logger.error("无效的月份格式 [%s]: %s", args.month, exc)
            return 1

    logger.info(
        "开始执行 NBS 化工产量同步: 目标产品=%s, 指定月份=%s, 强制覆盖=%s",
        args.products,
        args.month or "自动探测增量",
        args.force,
    )

    builder = ChemicalCapacityUtilization10Y(raw_dir=args.raw_dir, enable_online=True)
    raw_result, curated_frame = builder.sync_and_curate(
        start_date=start_date,
        end_date=end_date,
        force=args.force,
        product_names=args.products,
    )

    logger.info("================ NBS 产量同步与对账看板 ================")
    logger.info("同步状态: %s (updated=%s)", raw_result.status, raw_result.updated)
    logger.info("新增抓取周期: %s", raw_result.fetched_periods or ("无新增",))
    if raw_result.errors:
        logger.warning("同步异常提示: %s", raw_result.errors)

    raw_frame = raw_result.frame
    logger.info(
        "RAW 底表: %s (总记录数=%d, 涉及品种数=%d)",
        builder.paths.chemicals_parquet,
        raw_frame.height,
        raw_frame["product_name"].n_unique() if "product_name" in raw_frame.columns else 0,
    )
    logger.info(
        "Curated 黄金表: %d 行",
        curated_frame.height,
    )

    # 打印目标产品最新状态
    for p_name in args.products:
        sub_raw = raw_frame.filter(pl.col("product_name") == p_name).sort(
            "report_month", descending=True
        )
        if sub_raw.is_empty():
            logger.info("  [%s]: RAW 表中暂无记录", p_name)
            continue
        latest_r = sub_raw.to_dicts()[0]
        cur_vol = latest_r.get("output_current_raw") or "-"
        yoy = latest_r.get("output_yoy_raw") or "-"
        mo_str = latest_r.get("report_month")
        if not mo_str:
            continue
        mo_str_val = str(mo_str)
        u_str = latest_r.get("unit") or "万吨"

        # 查询对应的 Curated 利用率与血统来源
        util_str = "-"
        src_tag = ""
        if "implied_capacity_utilization_pct" in curated_frame.columns:
            sub_cur = curated_frame.filter(
                (pl.col("product_name") == p_name)
                & (pl.col("year") == int(mo_str_val[:4]))
                & (pl.col("month") == int(mo_str_val[5:7]))
            )
            if not sub_cur.is_empty():
                val = sub_cur.get_column("implied_capacity_utilization_pct").item(0)
                if val is not None:
                    util_str = f"{float(val):.2f}%"
                if "source" in sub_cur.columns:
                    src_val = sub_cur.get_column("source").item(0)
                    if src_val:
                        src_tag = f" ({src_val})"

        logger.info(
            "  [%s] 最新月份 %s: 当月产量=%s %s, 同比=%s%%, 测算产能利用率=%s%s",
            p_name,
            mo_str_val,
            cur_vol,
            u_str,
            yoy,
            util_str,
            src_tag,
        )

    logger.info("注: 产能利用率分母基于【研报共识非审计估算/前瞻规划】测算，仅供景气度趋势分析。")
    logger.info("=======================================================")
    return 0 if raw_result.status != "FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
