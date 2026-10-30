#!/usr/bin/env python3
"""郑商所纯碱 (CZCE SA) 期货全历史注册仓单回填脚本（仅写 RAW）。

数据权威源:
- 郑州商品交易所 (CZCE) 官方仓单日报:
  https://www.czce.com.cn/cn/DFSStaticFiles/Future/{year}/{date}/FutureDataWhsheet.xls (或 .xlsx)

特性:
- 覆盖 2019-12-06 (纯碱期货上市日) 至最新交易日全量历史;
- 本地断点续传缓存 (data/raw/industry/chemicals/futures_inventory/czce_daily/);
- 多线程并发下载与有限重试;
- 严格遵循 Ground Truth First 铁律与 2-Tier ETL 规范，保留 sha256 与 snapshot_ref;
- 只写 RAW（SA.csv + 官方快照），Curated futures_inventory.parquet 由
  ``make sync SOURCE=industry ENDPOINT=chemical_futures_inventory`` 统一物化。

下载与解析原语复用
``stock_data.fetcher.industry.chemicals.collectors.official``。
"""

from __future__ import annotations

import csv
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.chemicals.collectors.official import (
    download_czce_inventory_file,
    parse_czce_inventory_frame,
    snapshot_ref,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("czce_backfill")

BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "data" / "raw"
CURATED_DIR = BASE_DIR / "data" / "curated"
DAILY_CACHE_DIR = RAW_DIR / "industry" / "chemicals" / "futures_inventory" / "czce_daily"
SA_CSV_PATH = RAW_DIR / "industry" / "chemicals" / "futures_inventory" / "SA.csv"

SA_META = {"name": "纯碱", "industry_code": "220200", "unit": "contracts"}

SA_FIRST_RECEIPT_DATE = date(2020, 4, 7)
SA_LIST_DATE = date(2019, 12, 6)


def get_all_trading_dates() -> list[date]:
    """从本地已验证的申万二级行业黄金事实表提取 2019-12-06 以来的全部交易日。"""
    l2_path = CURATED_DIR / "mart" / "industry_l2_daily.parquet"
    if not l2_path.exists():
        raise FileNotFoundError(f"未找到 L2 交易日历来源: {l2_path}")
    df = pl.read_parquet(l2_path)
    dates = [d for d in df["trade_date"].unique().to_list() if d >= SA_LIST_DATE]
    dates.sort()
    return dates


def backfill_sa_inventory(max_workers: int = 12) -> None:
    """执行全历史回填（只写 RAW CSV 与官方快照缓存）。"""
    trading_dates = get_all_trading_dates()
    logger.info(
        "待处理交易日总数: %d (起始: %s, 截止: %s)",
        len(trading_dates),
        trading_dates[0],
        trading_dates[-1],
    )

    results: dict[date, dict[str, Any]] = {}
    now_iso = datetime.now().astimezone().isoformat()

    # 1. 2020-04-07 之前的交易日全部设为 0.0 (纯碱首批仓单注册前)
    for d in trading_dates:
        if d < SA_FIRST_RECEIPT_DATE:
            results[d] = {
                "trade_date": d,
                "symbol": "SA",
                "name": "纯碱",
                "industry_code": "220200",
                "inventory": 0.0,
                "change": 0.0 if d > SA_LIST_DATE else None,
                "unit": "contracts",
                "source": "Exchange_Official/CZCE",
                "source_url": "https://www.czce.com.cn/cn/jysj/cdrb/H770310index_1.htm",
                "release_date": d,
                "collected_at": now_iso,
                "raw_content_sha256": "0" * 64,
                "raw_snapshot_path": "synthetic_initial_zero",
            }

    dates_to_fetch = [d for d in trading_dates if d >= SA_FIRST_RECEIPT_DATE]
    logger.info("需要下载与解析的交易日数量: %d", len(dates_to_fetch))

    # 2. 并发下载（缓存优先）与解析
    completed_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(download_czce_inventory_file, d, DAILY_CACHE_DIR): d
            for d in dates_to_fetch
        }

        for future in as_completed(future_map):
            d = future_map[future]
            completed_count += 1
            if completed_count % 100 == 0 or completed_count == len(dates_to_fetch):
                logger.info(
                    "进度: %d/%d (%.1f%%)",
                    completed_count,
                    len(dates_to_fetch),
                    (completed_count / len(dates_to_fetch)) * 100,
                )

            try:
                _, local_path, ext, content = future.result()
                if content is None or local_path is None or ext is None:
                    continue

                parsed = parse_czce_inventory_frame(content, ext, {"SA": SA_META})
                inv_val, chg_val = parsed["SA"]
                sha = hashlib.sha256(content).hexdigest()
                source_url = (
                    "https://www.czce.com.cn/cn/DFSStaticFiles/Future/"
                    f"{d.year}/{d.strftime('%Y%m%d')}/FutureDataWhsheet.{ext}"
                )
                results[d] = {
                    "trade_date": d,
                    "symbol": "SA",
                    "name": "纯碱",
                    "industry_code": "220200",
                    "inventory": inv_val,
                    "change": chg_val,
                    "unit": "contracts",
                    "source": "Exchange_Official/CZCE",
                    "source_url": source_url,
                    "release_date": d,
                    "collected_at": now_iso,
                    "raw_content_sha256": sha,
                    "raw_snapshot_path": snapshot_ref(local_path, RAW_DIR),
                }
            except Exception as exc:
                logger.warning("处理 %s 异常: %s", d, exc)

    # 3. 排序并写入 RAW CSV
    sorted_records = [results[d] for d in trading_dates if d in results]
    logger.info("成功收集记录数: %d / %d", len(sorted_records), len(trading_dates))

    SA_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "trade_date",
        "symbol",
        "name",
        "industry_code",
        "inventory",
        "change",
        "unit",
        "source",
        "source_url",
        "release_date",
        "collected_at",
        "raw_content_sha256",
        "raw_snapshot_path",
    ]

    with SA_CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in sorted_records:
            writer.writerow(
                {
                    "trade_date": r["trade_date"].isoformat(),
                    "symbol": r["symbol"],
                    "name": r["name"],
                    "industry_code": r["industry_code"],
                    "inventory": f"{r['inventory']:.1f}" if r["inventory"] is not None else "",
                    "change": f"{r['change']:.1f}" if r["change"] is not None else "",
                    "unit": r["unit"],
                    "source": r["source"],
                    "source_url": r["source_url"],
                    "release_date": r["release_date"].isoformat() if r["release_date"] else "",
                    "collected_at": r["collected_at"],
                    "raw_content_sha256": r["raw_content_sha256"],
                    "raw_snapshot_path": r["raw_snapshot_path"],
                }
            )

    logger.info("已更新 RAW CSV: %s (%d 行)", SA_CSV_PATH, len(sorted_records))
    logger.info("Curated 请通过 make sync SOURCE=industry ENDPOINT=chemical_futures_inventory 物化")


if __name__ == "__main__":
    backfill_sa_inventory(max_workers=10)
