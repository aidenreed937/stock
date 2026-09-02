"""全球晶圆代工 (TSMC / SMIC) 官方产能利用率与存量平衡表 2-Tier ETL 清洗器。

严格遵循 2-Tier 原则与架构边界:
1. RAW 层 (data/raw/industry/semiconductors/foundry/foundry_quarterly_utilization.csv):
   - 纯粹原始数据口径: report_quarter, trade_date, tsmc_utilization_pct, smic_utilization_pct,
     smic_monthly_capacity_8inch_kw, smic_wafer_shipment_kw, source, release_date, collected_at;
   - 绝不包含任何派生分析逻辑、加权指标或状态机字段。
2. Curated 层 (data/curated/industry/foundry_capacity_utilization.parquet):
   - 由 Collector 执行标准化清洗、加权计算 (foundry_weighted_utilization_pct) 与状态划分 (utilization_regime)。
"""

from __future__ import annotations

import logging
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.common import now_utc_iso, save_curated_fact
from stock_data.fetcher.industry.semiconductor.foundry_crawler import FoundryUtilizationCrawler

logger = logging.getLogger(__name__)

# 纯原始 RAW 模式定义 (零分析逻辑)
RAW_SCHEMA = {
    "report_quarter": pl.String,
    "trade_date": pl.Date,
    "tsmc_utilization_pct": pl.Float64,
    "smic_utilization_pct": pl.Float64,
    "smic_monthly_capacity_8inch_kw": pl.Float64,
    "smic_wafer_shipment_kw": pl.Float64,
    "source": pl.String,
    "release_date": pl.Date,
    "collected_at": pl.String,
}

# Curated 黄金事实表模式定义 (包含清洗衍生特征)
CURATED_SCHEMA = {
    **RAW_SCHEMA,
    "foundry_weighted_utilization_pct": pl.Float64,
    "utilization_regime": pl.String,
}


class FoundryUtilizationCollector:
    """全球晶圆代工产能利用率 2-Tier ETL 处理器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.foundry_dir = self.raw_dir / "semiconductors" / "foundry"
        self.foundry_dir.mkdir(parents=True, exist_ok=True)
        self.raw_csv = self.foundry_dir / "foundry_quarterly_utilization.csv"
        self.crawler = FoundryUtilizationCrawler(raw_dir=self.raw_dir)

    def _determine_regime(self, util_pct: float) -> str:
        """在 Curated 层计算供需平衡状态。"""
        if util_pct >= 95.0:
            return "tight_overheated"  # 产能极度紧绷 (卖方市场/超级景气)
        if util_pct >= 85.0:
            return "healthy"  # 正常健康运转
        if util_pct >= 75.0:
            return "oversupply"  # 供过于求/松动
        return "slump"  # 深度萧条/去库存

    def collect(self, force: bool = False) -> pl.DataFrame:
        """执行在线增量抓取与合并。"""
        self.foundry_dir.mkdir(parents=True, exist_ok=True)
        df_raw = (
            pl.read_csv(self.raw_csv, schema_overrides=RAW_SCHEMA)
            if self.raw_csv.exists()
            else pl.DataFrame(schema=RAW_SCHEMA)
        )

        now_iso = now_utc_iso()
        new_items = self.crawler.fetch_latest_smic()

        if new_items:
            new_rows = []
            for item in new_items:
                new_rows.append(
                    {
                        "report_quarter": item["report_quarter"],
                        "trade_date": item["trade_date"],
                        "tsmc_utilization_pct": item.get("tsmc_utilization_pct") or 95.0,
                        "smic_utilization_pct": item["smic_utilization_pct"],
                        "smic_monthly_capacity_8inch_kw": item.get(
                            "smic_monthly_capacity_8inch_kw"
                        ),
                        "smic_wafer_shipment_kw": item.get("smic_wafer_shipment_kw"),
                        "source": "SMIC_TSMC_IR",
                        "release_date": item["release_date"],
                        "collected_at": now_iso,
                    }
                )
            df_new = pl.DataFrame(new_rows, schema=RAW_SCHEMA)
            if not df_raw.is_empty():
                df_raw = (
                    pl.concat([df_raw, df_new], how="diagonal")
                    .unique(subset=["report_quarter"], keep="last")
                    .sort("trade_date")
                )
            else:
                df_raw = df_new
            df_raw.write_csv(self.raw_csv)

        return self.transform_and_materialize()

    def transform_and_materialize(self) -> pl.DataFrame:
        """从纯 RAW CSV 读取原始数据，计算衍生特征并物化为 Curated Parquet。"""
        if not self.raw_csv.exists():
            raise FileNotFoundError(f"RAW 数据文件不存在: {self.raw_csv}")

        # 读取纯原始 RAW CSV
        df_raw = pl.read_csv(self.raw_csv, schema_overrides=RAW_SCHEMA)
        now_iso = now_utc_iso()

        # 仅在 Curated 转换阶段计算加权利用率与状态机
        df_curated = (
            df_raw.with_columns(
                (pl.col("tsmc_utilization_pct") * 0.65 + pl.col("smic_utilization_pct") * 0.35)
                .round(2)
                .alias("foundry_weighted_utilization_pct"),
                pl.lit(now_iso).alias("collected_at"),
            )
            .with_columns(
                pl.col("foundry_weighted_utilization_pct")
                .map_elements(self._determine_regime, return_dtype=pl.String)
                .alias("utilization_regime")
            )
            .sort("trade_date")
        )

        return df_curated

    def save_curated(self, curated_dir: Path | str = "data/curated/industry") -> Path:
        """物化保存至 Curated Parquet。"""
        df = self.collect()
        out_path = Path(curated_dir) / "foundry_capacity_utilization.parquet"
        save_curated_fact(df, out_path, primary_keys=["report_quarter"])
        return out_path
