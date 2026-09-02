"""SEMI 全球半导体设备市场统计 (WWSEMS) 季度公报 2-Tier ETL 采集与清洗器。

数据源:
- RAW 层: data/raw/industry/semiconductor/semi/semi_wwsems_quarterly.csv
- Curated 层: data/curated/industry/semiconductor_equipment_semi.parquet
"""

from __future__ import annotations

import logging
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.common import now_utc_iso, save_curated_fact
from stock_data.fetcher.industry.semiconductor.semi_crawler import SemiEquipmentCrawler

logger = logging.getLogger(__name__)

SEMI_CSV_FIELDNAMES = [
    "report_quarter",
    "trade_date",
    "global_billings_billion_usd",
    "china_billings_billion_usd",
    "china_share_pct",
    "yoy_growth",
    "qoq_growth",
    "unit",
    "source",
    "source_url",
    "release_date",
    "data_status",
    "collected_at",
]


class SemiEquipmentCollector:
    """SEMI 全球半导体设备销售公报 2-Tier ETL 采集器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.snapshot_dir = self.raw_dir / "semiconductor" / "semi"
        self.raw_csv = self.snapshot_dir / "semi_wwsems_quarterly.csv"
        self.crawler = SemiEquipmentCrawler(raw_dir=self.raw_dir)

    def load_from_raw_csv(self, file_path: Path | str) -> pl.DataFrame:
        """从本地 RAW CSV 加载历史真值底表。"""
        p = Path(file_path)
        if not p.exists():
            return pl.DataFrame()
        return (
            pl.read_csv(p)
            .with_columns(
                pl.col("trade_date").str.to_date(),
                pl.col("release_date").str.to_date(),
                pl.col("global_billings_billion_usd").cast(pl.Float64),
                pl.col("china_billings_billion_usd").cast(pl.Float64, strict=False),
                pl.col("china_share_pct").cast(pl.Float64, strict=False),
                pl.col("yoy_growth").cast(pl.Float64, strict=False),
                pl.col("qoq_growth").cast(pl.Float64, strict=False),
            )
            .sort("trade_date")
        )

    def collect(self, force: bool = False) -> pl.DataFrame:
        """执行数据采集: 读取本地 RAW 底表，在线爬取最新公报并增量对齐合并。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        df_existing = (
            self.load_from_raw_csv(self.raw_csv) if self.raw_csv.exists() else pl.DataFrame()
        )

        # 1. 在线抓取最新公报
        now_iso = now_utc_iso()
        new_items = self.crawler.fetch_latest()

        if new_items:
            new_rows = []
            for item in new_items:
                g_bill = item["global_billings_billion_usd"]
                c_bill = item.get("china_billings_billion_usd")
                c_share = round((c_bill / g_bill) * 100.0, 2) if (c_bill and g_bill > 0) else None

                new_rows.append(
                    {
                        "report_quarter": item["report_quarter"],
                        "trade_date": item["trade_date"],
                        "global_billings_billion_usd": g_bill,
                        "china_billings_billion_usd": c_bill,
                        "china_share_pct": c_share,
                        "yoy_growth": None,
                        "qoq_growth": None,
                        "unit": "billion_usd",
                        "source": "SEMI_WWSEMS",
                        "source_url": item.get("source_url")
                        or "https://www.semi.org/en/news-media/press-releases",
                        "release_date": item["release_date"],
                        "data_status": "actual",
                        "collected_at": now_iso,
                    }
                )
            df_new = pl.DataFrame(new_rows)
            if not df_existing.is_empty():
                df_merged = (
                    pl.concat([df_existing, df_new], how="diagonal")
                    .unique(subset=["report_quarter"], keep="last")
                    .sort("trade_date")
                )
            else:
                df_merged = df_new
        else:
            df_merged = df_existing

        if df_merged.is_empty():
            return pl.DataFrame()

        # 2. 重新计算 YoY, QoQ 与中国区占比
        df_curated = (
            df_merged.with_columns(
                pl.col("global_billings_billion_usd").pct_change(4).round(4).alias("_yoy"),
                pl.col("global_billings_billion_usd").pct_change(1).round(4).alias("_qoq"),
            )
            .with_columns(
                pl.when(pl.col("yoy_growth").is_null())
                .then(pl.col("_yoy"))
                .otherwise(pl.col("yoy_growth"))
                .alias("yoy_growth"),
                pl.when(pl.col("qoq_growth").is_null())
                .then(pl.col("_qoq"))
                .otherwise(pl.col("qoq_growth"))
                .alias("qoq_growth"),
                pl.when(
                    pl.col("china_share_pct").is_null()
                    & pl.col("china_billings_billion_usd").is_not_null()
                    & (pl.col("global_billings_billion_usd") > 0)
                )
                .then(
                    (
                        pl.col("china_billings_billion_usd")
                        / pl.col("global_billings_billion_usd")
                        * 100.0
                    ).round(2)
                )
                .otherwise(pl.col("china_share_pct"))
                .alias("china_share_pct"),
            )
            .drop(["_yoy", "_qoq"])
        )

        # 3. 回写更新 RAW CSV
        df_curated.write_csv(self.raw_csv)
        return df_curated

    def save_curated(self, curated_dir: Path | str = "data/curated/industry") -> Path:
        """物化保存至 Curated Parquet。"""
        df = self.collect()
        out_path = Path(curated_dir) / "semiconductor_equipment_semi.parquet"
        save_curated_fact(df, out_path, primary_keys=["report_quarter"])
        return out_path
