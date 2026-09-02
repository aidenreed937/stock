"""全球半导体 IDM 龙头季度存货周转天数 (DOI / Days of Inventory) 2-Tier ETL 转换与物化。

数据源:
1. RAW 层: data/raw/industry/semiconductors/inventory/idm_quarterly_financials_10y.csv (SEC 10-Q/10-K & yfinance)
2. Curated 层: data/curated/industry/semiconductor_inventory_days.parquet

核心指标:
- 个股 DOI (天) = (期末存货 / 季度营业成本) * 90
- 综合加权 DOI (天) = sum(存货) / sum(营业成本) * 90
- 库存周期相态 (inventory_regime):
  * high_overstocked: DOI >= 150 天 (严重累库去化压力)
  * elevated_destocking: 130 <= DOI < 150 天 (去库存周期中)
  * normal_balanced: 105 <= DOI < 130 天 (健康供需平衡)
  * tight_restocking: DOI < 105 天 (低库存强补库需求)
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.common import now_utc_iso


def _determine_inventory_regime(weighted_doi: float) -> str:
    """根据 IDM 加权存货周转天数判定库存周期相态。"""
    if weighted_doi >= 150.0:
        return "high_overstocked"
    if weighted_doi >= 130.0:
        return "elevated_destocking"
    if weighted_doi >= 105.0:
        return "normal_balanced"
    return "tight_restocking"


class SemiconductorInventoryCollector:
    """全球半导体 IDM 龙头存货周转天数 (DOI) 采集与转换器。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.raw_csv = (
            self.raw_dir / "semiconductors" / "inventory" / "idm_quarterly_financials_10y.csv"
        )

    def collect(self) -> pl.DataFrame:
        """从本地 RAW CSV 解析 4 大龙头财报并计算 DOI 黄金事实表。"""
        if not self.raw_csv.exists():
            return pl.DataFrame()

        rows: list[dict[str, Any]] = []
        with self.raw_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                sym = r["symbol"].strip()
                q_str = r["report_quarter"].strip()
                t_str = r["trade_date"].strip()
                inv_val = float(r["inventory_usd"])
                cogs_val = float(r["cost_of_revenue_usd"])
                doi = round((inv_val / cogs_val) * 90.0, 1) if cogs_val > 0 else None

                yr = int(q_str[:4])
                q_num = int(q_str[-1])
                mo = q_num * 3
                rel_mo = mo + 2 if mo <= 10 else (mo + 2) - 12
                rel_yr = yr if mo <= 10 else yr + 1
                rel_d = date(rel_yr, rel_mo, 10)

                t_d = date.fromisoformat(t_str)

                rows.append(
                    {
                        "symbol": sym,
                        "report_quarter": q_str,
                        "trade_date": t_d,
                        "inventory_usd_million": inv_val,
                        "cost_of_revenue_usd_million": cogs_val,
                        "doi_days": doi,
                        "release_date": rel_d,
                    }
                )

        if not rows:
            return pl.DataFrame()

        df_raw = pl.DataFrame(rows)

        q_agg = (
            df_raw.group_by("report_quarter")
            .agg(
                pl.col("inventory_usd_million").sum().alias("total_inventory_usd_million"),
                pl.col("cost_of_revenue_usd_million")
                .sum()
                .alias("total_cost_of_revenue_usd_million"),
                pl.col("doi_days").mean().round(1).alias("idm_equal_doi_days"),
            )
            .with_columns(
                (
                    pl.col("total_inventory_usd_million")
                    / pl.col("total_cost_of_revenue_usd_million")
                    * 90.0
                )
                .round(1)
                .alias("idm_weighted_doi_days")
            )
            .with_columns(
                pl.col("idm_weighted_doi_days")
                .map_elements(_determine_inventory_regime, return_dtype=pl.String)
                .alias("inventory_regime")
            )
        )

        now_iso = now_utc_iso()
        df_out = (
            df_raw.join(q_agg, on="report_quarter", how="left")
            .with_columns(
                pl.lit("SEC_10Q_yfinance").alias("source"),
                pl.lit("days").alias("unit"),
                pl.lit("actual").alias("data_status"),
                pl.lit(now_iso).alias("collected_at"),
            )
            .sort(["report_quarter", "symbol"])
        )

        return df_out

    def save_curated(self, curated_dir: Path | str = "data/curated/industry") -> Path:
        """物化保存至 Curated Parquet。"""
        out_dir = Path(curated_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "semiconductor_inventory_days.parquet"
        df = self.collect()
        df.write_parquet(out_path)
        return out_path
