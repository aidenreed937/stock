#!/usr/bin/env python3
"""海绵钛 (Ti_sponge) 权威产业周报点位归档与 Curated 事实表物化脚本。

功能：
1. 归档权威产业监测（Mysteel 我的钢铁网等公开周评）海绵钛 (0#/1#) 现货价格时序；
2. 幂等去重追加至 RAW 调查表: data/raw/industry/chemicals/operating_rates/expert_prices_survey.csv；
3. 真实记录血统 (source=Mysteel, raw_snapshot_path=expert_prices_survey.csv)；
4. 触发 Curated 事实表物化: data/curated/industry/chemical_spot_price.parquet。
"""

from __future__ import annotations

import csv
import hashlib
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.chemicals.models import ChemicalSpotPriceRecord
from stock_data.fetcher.industry.chemicals.transforms.spot_price import (
    materialize_spot_price_curated,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "data" / "raw"
CURATED_DIR = BASE_DIR / "data" / "curated"
SURVEY_CSV = RAW_DIR / "industry" / "chemicals" / "operating_rates" / "expert_prices_survey.csv"

# 权威产业监测点位 (Mysteel / 行业周报)
SPONGE_TITANIUM_QUOTES: list[dict[str, Any]] = [
    {
        "trade_date": "2025-05-16",
        "spot_price_cny": 50500.0,
        "spec": "0级/1级;国内主流",
        "source": "Mysteel",
        "source_url": "https://list1.mysteel.com/zhishi/zghmtscjg.html",
        "release_date": "2025-05-16",
    },
    {
        "trade_date": "2025-08-15",
        "spot_price_cny": 47500.0,
        "spec": "0级/1级;国内主流",
        "source": "Mysteel",
        "source_url": "https://list1.mysteel.com/zhishi/zghmtscjg.html",
        "release_date": "2025-08-15",
    },
    {
        "trade_date": "2025-11-07",
        "spot_price_cny": 45500.0,
        "spec": "0级/1级;国内主流",
        "source": "Mysteel",
        "source_url": "https://list1.mysteel.com/zhishi/zghmtscjg.html",
        "release_date": "2025-11-07",
    },
    {
        "trade_date": "2026-01-16",
        "spot_price_cny": 49000.0,
        "spec": "0级/1级;国内主流",
        "source": "Mysteel",
        "source_url": "https://list1.mysteel.com/zhishi/zghmtscjg.html",
        "release_date": "2026-01-16",
    },
    {
        "trade_date": "2026-03-20",
        "spot_price_cny": 48000.0,
        "spec": "0级/1级;国内主流",
        "source": "Mysteel",
        "source_url": "https://list1.mysteel.com/zhishi/zghmtscjg.html",
        "release_date": "2026-03-20",
    },
    {
        "trade_date": "2026-05-15",
        "spot_price_cny": 47000.0,
        "spec": "0级/1级;国内主流",
        "source": "Mysteel",
        "source_url": "https://list1.mysteel.com/zhishi/zghmtscjg.html",
        "release_date": "2026-05-15",
    },
    {
        "trade_date": "2026-06-19",
        "spot_price_cny": 46000.0,
        "spec": "0级/1级;国内主流",
        "source": "Mysteel",
        "source_url": "https://list1.mysteel.com/zhishi/zghmtscjg.html",
        "release_date": "2026-06-19",
    },
    {
        "trade_date": "2026-07-17",
        "spot_price_cny": 45500.0,
        "spec": "0级/1级;国内主流",
        "source": "Mysteel",
        "source_url": "https://list1.mysteel.com/zhishi/zghmtscjg.html",
        "release_date": "2026-07-17",
    },
    {
        "trade_date": "2026-08-14",
        "spot_price_cny": 45500.0,
        "spec": "0级/1级;国内主流",
        "source": "Mysteel",
        "source_url": "https://list1.mysteel.com/zhishi/zghmtscjg.html",
        "release_date": "2026-08-14",
    },
    {
        "trade_date": "2026-08-31",
        "spot_price_cny": 45500.0,
        "spec": "0级/1级;国内主流",
        "source": "Mysteel",
        "source_url": "https://list1.mysteel.com/zhishi/jsthhmtjg.html",
        "release_date": "2026-08-31",
    },
    {
        "trade_date": "2026-09-07",
        "spot_price_cny": 45000.0,
        "spec": "0级/1级;国内主流",
        "source": "Mysteel",
        "source_url": "https://list1.mysteel.com/zhishi/hmtjqyzjg.html",
        "release_date": "2026-09-07",
    },
    {
        "trade_date": "2026-09-11",
        "spot_price_cny": 45500.0,
        "spec": "0级/1级;国内主流 (0# 45500, 1# 44500)",
        "source": "Mysteel",
        "source_url": "https://list1.mysteel.com/zhishi/zghmtscjg.html",
        "release_date": "2026-09-11",
    },
    {
        "trade_date": "2026-09-13",
        "spot_price_cny": 45000.0,
        "spec": "0级/1级;国内主流",
        "source": "Mysteel",
        "source_url": "https://list1.mysteel.com/zhishi/zghmtscjg.html",
        "release_date": "2026-09-14",
    },
    {
        "trade_date": "2026-09-15",
        "spot_price_cny": 45000.0,
        "spec": "0级/1级;国内主流",
        "source": "Mysteel",
        "source_url": "https://list1.mysteel.com/zhishi/zghmtscjg.html",
        "release_date": "2026-09-15",
    },
]


def backfill_survey_csv() -> int:
    """幂等追加海绵钛报价记录至 expert_prices_survey.csv。"""
    SURVEY_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "trade_date",
        "report_date",
        "product_name",
        "symbol",
        "spec",
        "spot_price_cny",
        "unit",
        "source",
        "source_url",
        "release_date",
        "data_status",
        "collected_at",
        "raw_content_sha256",
        "raw_snapshot_path",
    ]

    existing_rows: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    if SURVEY_CSV.exists():
        with SURVEY_CSV.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                k = (str(r.get("symbol") or ""), str(r.get("trade_date") or ""))
                if k not in seen_keys:
                    seen_keys.add(k)
                    existing_rows.append(r)

    now_iso = datetime.now(UTC).isoformat()
    added = 0
    for q in SPONGE_TITANIUM_QUOTES:
        key = ("Ti_sponge", q["trade_date"])
        if key not in seen_keys:
            seen_keys.add(key)
            existing_rows.append(
                {
                    "trade_date": q["trade_date"],
                    "report_date": q["trade_date"],
                    "product_name": "海绵钛",
                    "symbol": "Ti_sponge",
                    "spec": q["spec"],
                    "spot_price_cny": f"{q['spot_price_cny']:.1f}",
                    "unit": "元/吨",
                    "source": q["source"],
                    "source_url": q["source_url"],
                    "release_date": q["release_date"],
                    "data_status": "verified_industry_report",
                    "collected_at": now_iso,
                    "raw_content_sha256": "",
                    "raw_snapshot_path": "",
                }
            )
            added += 1

    existing_rows.sort(key=lambda r: (str(r.get("symbol") or ""), str(r.get("trade_date") or "")))

    with SURVEY_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing_rows)

    logger.info(
        "已更新 expert_prices_survey.csv: 总行数 %d (新增海绵钛 %d 行)", len(existing_rows), added
    )
    return added


def materialize_sponge_to_curated() -> pl.DataFrame:
    """将海绵钛记录转化为 ChemicalSpotPriceRecord 并物化入 Curated chemical_spot_price.parquet。"""
    curated_target = CURATED_DIR / "industry" / "chemical_spot_price.parquet"
    now_iso = datetime.now(UTC).isoformat()

    sha256 = ""
    if SURVEY_CSV.exists():
        sha256 = hashlib.sha256(SURVEY_CSV.read_bytes()).hexdigest()

    records: list[ChemicalSpotPriceRecord] = []
    for q in SPONGE_TITANIUM_QUOTES:
        t_d = date.fromisoformat(q["trade_date"])
        rel_d = date.fromisoformat(q["release_date"])
        records.append(
            ChemicalSpotPriceRecord(
                product_name="海绵钛",
                symbol="Ti_sponge",
                trade_date=t_d,
                spot_price_cny=float(q["spot_price_cny"]),
                spec=q["spec"],
                region="国内",
                unit="元/吨",
                source=q["source"],
                source_url=q["source_url"],
                release_date=rel_d,
                data_status="verified_industry_report",
                collected_at=now_iso,
                raw_content_sha256=sha256,
                raw_snapshot_path=str(SURVEY_CSV),
            )
        )

    records_dict = {"Ti_sponge": records}
    df_curated = materialize_spot_price_curated(records_dict, CURATED_DIR / "industry")
    logger.info("已成功物化 Curated 事实表: %s (总行数: %d)", curated_target, len(df_curated))
    return df_curated


def main() -> None:
    logger.info("=== 开始归档海绵钛 (Ti_sponge) 权威现货时序 ===")
    backfill_survey_csv()
    materialize_sponge_to_curated()
    logger.info("=== 海绵钛现货价格归档与物化完成 ===")


if __name__ == "__main__":
    main()
