"""将新能源汽车历史产销 CSV 数据标准化转换为 2-Tier RAW Parquet 与 Curated Parquet。"""

from __future__ import annotations

import calendar
import hashlib
import logging
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

NEV_MONTHLY_RAW_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "wholesale_volume_raw": pl.String,
    "total_volume_raw": pl.String,
    "retail_volume_raw": pl.String,
    "export_volume_raw": pl.String,
    "penetration_rate_raw": pl.String,
    "battery_installation_gwh_raw": pl.String,
    "yoy_growth_raw": pl.String,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
    "raw_content_sha256": pl.String,
    "raw_snapshot_path": pl.String,
}

NEV_MONTHLY_SCHEMA = {
    "report_month": pl.String,
    "trade_date": pl.Date,
    "wholesale_volume_ten_thousand": pl.Float64,
    "wholesale_volume_3mma": pl.Float64,
    "retail_volume_ten_thousand": pl.Float64,
    "export_volume_ten_thousand": pl.Float64,
    "penetration_rate": pl.Float64,
    "battery_installation_gwh": pl.Float64,
    "yoy_growth": pl.Float64,
    "yoy_growth_3mma": pl.Float64,
    "mom_growth_3mma": pl.Float64,
    "unit": pl.String,
    "source": pl.String,
    "source_url": pl.String,
    "release_date": pl.Date,
    "data_status": pl.String,
    "collected_at": pl.String,
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _month_end(year: int, month: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


def _next_month_tenth(year: int, month: int) -> date:
    rel_year = year if month < 12 else year + 1
    rel_month = month + 1 if month < 12 else 1
    return date(rel_year, rel_month, 10)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    if s == "" or s.lower() in ("nan", "none", "null"):
        return None
    return s


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_root = repo_root / "data" / "raw" / "industry"
    curated_root = repo_root / "data" / "curated" / "industry"

    csv_path = raw_root / "automotive" / "cpca" / "nev_sales_real.csv"
    if not csv_path.exists():
        legacy_csv = raw_root / "cpca" / "nev_sales_real.csv"
        if legacy_csv.exists():
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil

            shutil.copy2(legacy_csv, csv_path)
            logger.info("已从旧路径拷贝底表至: %s", csv_path)
        else:
            raise FileNotFoundError(f"未找到历史底表 CSV: {csv_path}")

    csv_sha256 = _file_sha256(csv_path)
    logger.info("读取历史 CSV 底表: %s (SHA256: %s)", csv_path, csv_sha256)

    csv_df = pl.read_csv(csv_path)
    logger.info(
        "CSV 底表总行数: %d 行 (区间: %s ~ %s)",
        len(csv_df),
        csv_df["report_month"].min(),
        csv_df["report_month"].max(),
    )

    # 读取现存的 RAW data.parquet (包含最近在线抓取的 19 个月)
    raw_parquet_path = raw_root / "automotive" / "data.parquet"
    existing_raw_by_month: dict[str, dict[str, Any]] = {}
    if raw_parquet_path.exists():
        existing_raw_df = pl.read_parquet(raw_parquet_path)
        logger.info(
            "读取现存 RAW Parquet: %d 行 (区间: %s ~ %s)",
            len(existing_raw_df),
            existing_raw_df["report_month"].min(),
            existing_raw_df["report_month"].max(),
        )
        for row in existing_raw_df.iter_rows(named=True):
            existing_raw_by_month[str(row["report_month"])] = row

    # 构建合并后的 RAW 记录列表
    combined_raw_rows: list[dict[str, Any]] = []

    for row in csv_df.iter_rows(named=True):
        m_str = str(row["report_month"]).strip()
        year = int(m_str[:4])
        month = int(m_str[5:7])
        t_date = _month_end(year, month)
        rel_date = _next_month_tenth(year, month)

        if m_str <= "2024-12":
            # 2018-01 ~ 2024-12: 使用经核准的真实公报底表数据，并规范标注来源
            raw_row = {
                "report_month": m_str,
                "trade_date": t_date,
                "wholesale_volume_raw": _safe_str(row.get("wholesale_volume_ten_thousand")),
                "total_volume_raw": None,
                "retail_volume_raw": _safe_str(row.get("retail_volume_ten_thousand")),
                "export_volume_raw": _safe_str(row.get("export_volume_ten_thousand")),
                "penetration_rate_raw": _safe_str(row.get("penetration_rate")),
                "battery_installation_gwh_raw": _safe_str(row.get("battery_installation_gwh")),
                "yoy_growth_raw": _safe_str(row.get("yoy_growth")),
                "unit": "ten_thousand_units",
                "source": "CPCA/CABIA",
                "source_url": "http://www.cpcaauto.com/;http://www.cabr-ac.com/",
                "release_date": rel_date,
                "data_status": "actual",
                "collected_at": _safe_str(row.get("collected_at"))
                or "2026-08-31T07:19:22.345900+00:00",
                "raw_content_sha256": csv_sha256,
                "raw_snapshot_path": "automotive/cpca/nev_sales_real.csv",
            }
            combined_raw_rows.append(raw_row)
        else:
            # 2025-01 之后：优先采用在线抓取的实时接口数据，同时从 CSV 补充动力电池等缺失字段
            online_row = existing_raw_by_month.get(m_str)
            if online_row:
                merged_row = dict(online_row)
                csv_battery = _safe_str(row.get("battery_installation_gwh"))
                if csv_battery:
                    merged_row["battery_installation_gwh_raw"] = csv_battery
                    current_src = merged_row.get("source") or "CPCA"
                    if "CABIA" not in current_src:
                        merged_row["source"] = f"{current_src}/CABIA"
                combined_raw_rows.append(merged_row)
            else:
                # 若在线抓取不存在此月份，则使用 CSV 兜底
                raw_row = {
                    "report_month": m_str,
                    "trade_date": t_date,
                    "wholesale_volume_raw": _safe_str(row.get("wholesale_volume_ten_thousand")),
                    "total_volume_raw": None,
                    "retail_volume_raw": _safe_str(row.get("retail_volume_ten_thousand")),
                    "export_volume_raw": _safe_str(row.get("export_volume_ten_thousand")),
                    "penetration_rate_raw": _safe_str(row.get("penetration_rate")),
                    "battery_installation_gwh_raw": _safe_str(row.get("battery_installation_gwh")),
                    "yoy_growth_raw": _safe_str(row.get("yoy_growth")),
                    "unit": "ten_thousand_units",
                    "source": "CPCA/CABIA",
                    "source_url": "http://www.cpcaauto.com/;https://batteryalliancechina.org/",
                    "release_date": rel_date,
                    "data_status": "actual",
                    "collected_at": _safe_str(row.get("collected_at"))
                    or "2026-08-31T07:19:22.345900+00:00",
                    "raw_content_sha256": csv_sha256,
                    "raw_snapshot_path": "automotive/cpca/nev_sales_real.csv",
                }
                combined_raw_rows.append(raw_row)

    # 排序去重
    combined_raw_rows.sort(key=lambda r: r["trade_date"])
    new_raw_df = (
        pl.DataFrame(combined_raw_rows, schema=NEV_MONTHLY_RAW_SCHEMA)
        .unique(subset=["report_month"], keep="last")
        .sort("trade_date")
    )
    raw_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    new_raw_df.write_parquet(raw_parquet_path)
    logger.info(
        "已生成标准 RAW Parquet: %s (共 %d 行, 区间: %s ~ %s)",
        raw_parquet_path,
        len(new_raw_df),
        new_raw_df["report_month"].min(),
        new_raw_df["report_month"].max(),
    )

    alias_raw_path = raw_root / "automotive" / "nev_monthly_sales.parquet"
    if not alias_raw_path.exists():
        import os

        os.symlink("data.parquet", alias_raw_path)
        logger.info("已创建兼容软链接: %s -> data.parquet", alias_raw_path)

    # 构建 Curated 表
    def _to_float(v: Any) -> float | None:
        if v is None:
            return None
        try:
            return float(str(v).replace(",", ""))
        except (ValueError, TypeError):
            return None

    curated_rows = []
    for r in combined_raw_rows:
        ws_val = _to_float(r.get("wholesale_volume_raw"))
        ret_val = _to_float(r.get("retail_volume_raw"))
        exp_val = _to_float(r.get("export_volume_raw"))
        pen_val = _to_float(r.get("penetration_rate_raw"))
        bat_val = _to_float(r.get("battery_installation_gwh_raw"))
        curated_rows.append(
            {
                "report_month": r["report_month"],
                "trade_date": r["trade_date"],
                "wholesale_volume_ten_thousand": ws_val,
                "wholesale_volume_3mma": None,
                "retail_volume_ten_thousand": ret_val,
                "export_volume_ten_thousand": exp_val,
                "penetration_rate": pen_val,
                "battery_installation_gwh": bat_val,
                "yoy_growth": None,
                "yoy_growth_3mma": None,
                "mom_growth_3mma": None,
                "unit": r.get("unit") or "ten_thousand_units",
                "source": r.get("source") or "CPCA",
                "source_url": r.get("source_url") or "",
                "release_date": r.get("release_date"),
                "data_status": r.get("data_status") or "actual",
                "collected_at": r.get("collected_at") or "",
            }
        )

    curated_df = pl.DataFrame(curated_rows, schema=NEV_MONTHLY_SCHEMA).sort("trade_date")
    curated_df = curated_df.with_columns(
        pl.col("wholesale_volume_ten_thousand")
        .rolling_mean(window_size=3, min_samples=1)
        .alias("wholesale_volume_3mma")
    ).with_columns(
        (pl.col("wholesale_volume_3mma") / pl.col("wholesale_volume_3mma").shift(12) - 1.0).alias(
            "yoy_growth_3mma"
        ),
        (pl.col("wholesale_volume_3mma") / pl.col("wholesale_volume_3mma").shift(1) - 1.0).alias(
            "mom_growth_3mma"
        ),
        (
            pl.col("wholesale_volume_ten_thousand")
            / pl.col("wholesale_volume_ten_thousand").shift(12)
            - 1.0
        ).alias("yoy_growth"),
    )

    curated_parquet_path = curated_root / "nev_monthly_sales.parquet"
    curated_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    curated_df.write_parquet(curated_parquet_path)
    logger.info(
        "已生成标准 Curated Parquet: %s (共 %d 行, 区间: %s ~ %s)",
        curated_parquet_path,
        len(curated_df),
        curated_df["report_month"].min(),
        curated_df["report_month"].max(),
    )


if __name__ == "__main__":
    main()
