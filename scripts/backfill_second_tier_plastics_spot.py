#!/usr/bin/env python3
"""离线批量回填第二梯队通用塑料 (EB 苯乙烯 / PP 聚丙烯) 现货与基差事实。

零外网依赖：
从本地已有 RAW 缓存 (data/raw/industry/chemicals/100ppi_sf/*.html) 中解析 EB 与 PP，
增量幂等合并物化至：
1. data/curated/industry/chemical_spot_price.parquet
2. data/curated/industry/chemical_futures_basis.parquet
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.chemicals.parsers.basis_table import (
    ChemicalBasisRow,
    parse_100ppi_basis_html,
)
from stock_data.fetcher.industry.chemicals.transforms.basis import (
    materialize_basis_records_to_curated,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_plastics")

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
RAW_SF_DIR = WORKSPACE_ROOT / "data" / "raw" / "industry" / "chemicals" / "100ppi_sf"
CURATED_DIR = WORKSPACE_ROOT / "data" / "curated" / "industry"
TARGET_SYMBOLS = {"EB", "PP"}


def backfill_plastics() -> int:
    if not RAW_SF_DIR.exists():
        logger.error(f"RAW 目录不存在: {RAW_SF_DIR}")
        return 1

    html_files = sorted(RAW_SF_DIR.glob("day-*.html"))
    logger.info(f"发现本地 100ppi 现期表 HTML 缓存共 {len(html_files)} 个")

    all_records: list[ChemicalBasisRow] = []
    date_pattern = re.compile(r"day-(\d{4}-\d{2}-\d{2})\.html")

    for f in html_files:
        match = date_pattern.search(f.name)
        if not match:
            continue
        try:
            trade_d = date.fromisoformat(match.group(1))
        except ValueError:
            continue

        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            records = parse_100ppi_basis_html(content, trade_d, target_symbols=TARGET_SYMBOLS)
            for r in records:
                if r.symbol in TARGET_SYMBOLS:
                    all_records.append(r)
        except Exception as e:
            logger.warning(f"解析 {f.name} 失败: {e}")

    logger.info(f"成功从本地 HTML 解析提取 EB/PP 记录共 {len(all_records)} 条")
    if not all_records:
        logger.warning("未解析到任何 EB/PP 记录")
        return 1

    # 物化至 Curated 黄金事实表
    spot_added, basis_total = materialize_basis_records_to_curated(
        records=all_records,
        curated_dir=CURATED_DIR,
        update_spot_price=True,
    )
    logger.info(f"物化完成: 现货新增/更新 {spot_added} 条, 基差表当前总记录 {basis_total} 条")

    # 检查 Curated 表中 EB 与 PP 最新状态
    spot_df = pl.read_parquet(CURATED_DIR / "chemical_spot_price.parquet")
    for sym in TARGET_SYMBOLS:
        sub = spot_df.filter(pl.col("symbol") == sym).sort("trade_date")
        if not sub.is_empty():
            latest_row = sub.row(-1, named=True)
            logger.info(
                f"[{sym}] 最新现货日期: {latest_row['trade_date']}, 价格: {latest_row['spot_price_cny']} 元/吨"
            )
        else:
            logger.warning(f"[{sym}] 在现货表中未找到记录！")

    return 0


if __name__ == "__main__":
    raise SystemExit(backfill_plastics())
