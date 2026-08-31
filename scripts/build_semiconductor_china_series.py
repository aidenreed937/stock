"""构建中国半导体月度销售额推算序列并回填 semiconductor_sales.china_sales_usd。

链路:
  1. 扫描 SIA raw 新闻 (data/raw/industry/sia/*.html.gz) 解析 China YoY/MoM 与年度绝对值锚点;
  2. 以年度锚点为基准, MoM 链式推算 + YoY 双向校准, 构建连续月度序列;
  3. 落盘推算序列到 data/curated/industry/semiconductor_china_series.parquet;
  4. 将推算的 china_sales_usd 回填到 semiconductor_sales.parquet 的 china_sales_usd 列
     (同时保留原 china_yoy_growth/china_mom_growth 新闻值, 缺失月份置 null)。

用法:
    uv run python scripts/build_semiconductor_china_series.py            # 全流程
    uv run python scripts/build_semiconductor_china_series.py --series-only  # 只建推算序列
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.semiconductor.china_series import (
    build_china_series,
    parse_sia_raw_dir,
    save_china_series,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RAW_SIA_DIR = Path("data/raw/industry/sia")
CHINA_SERIES_PATH = Path("data/curated/industry/semiconductor_china_series.parquet")
SEMI_SALES_PATH = Path("data/curated/industry/semiconductor_sales.parquet")


def backfill_semiconductor_sales(series: pl.DataFrame) -> int:
    """将推算的 china_sales_usd 及同比/环比回填到 semiconductor_sales 黄金表。"""
    if series.is_empty():
        logger.warning("推算序列为空, 跳过回填")
        return 0

    sales = pl.read_parquet(SEMI_SALES_PATH)
    china_map = series.select(
        ["report_month", "china_sales_usd", "china_yoy_growth", "china_mom_growth"]
    ).rename(
        {
            "china_sales_usd": "_c_sales",
            "china_yoy_growth": "_c_yoy",
            "china_mom_growth": "_c_mom",
        }
    )
    merged = (
        sales.join(china_map, on="report_month", how="left")
        .with_columns(
            [
                pl.coalesce([pl.col("_c_sales"), pl.col("china_sales_usd")]).alias(
                    "china_sales_usd"
                ),
                pl.coalesce([pl.col("_c_yoy"), pl.col("china_yoy_growth")]).alias(
                    "china_yoy_growth"
                ),
                pl.coalesce([pl.col("_c_mom"), pl.col("china_mom_growth")]).alias(
                    "china_mom_growth"
                ),
            ]
        )
        .drop(["_c_sales", "_c_yoy", "_c_mom"])
    )

    merged.write_parquet(SEMI_SALES_PATH)
    filled = merged["china_sales_usd"].is_not_null().sum()
    logger.info(
        "semiconductor_sales 回填完成: %s 共 %d 行, china_sales_usd 非空 %d 行",
        SEMI_SALES_PATH.name,
        merged.height,
        filled,
    )
    return filled


def main() -> None:
    parser = argparse.ArgumentParser(description="构建中国半导体月度销售额推算序列")
    parser.add_argument("--series-only", action="store_true", help="只生成推算序列, 不回填")
    args = parser.parse_args()

    records = parse_sia_raw_dir(RAW_SIA_DIR)
    if not records:
        logger.error("SIA raw 解析为空, 终止")
        raise SystemExit(1)

    series = build_china_series(records)
    save_china_series(series, CHINA_SERIES_PATH)

    n_series = series["china_sales_usd"].is_not_null().sum()
    logger.info("推算序列: %d 行, 非空绝对值 %d 个月", series.height, n_series)

    if not args.series_only:
        backfill_semiconductor_sales(series)


if __name__ == "__main__":
    main()
