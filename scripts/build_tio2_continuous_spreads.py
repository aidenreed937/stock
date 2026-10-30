#!/usr/bin/env python3
"""钛白粉 (TiO2) 连续周频理论价差与利润序列生成器。

模型规范 (依据 config/industry/chemicals/tio2/cost_models.yaml，品种级唯一维护源；ChemicalSpreadCalculator 在默认门面路径下自动回退加载该文件):
- 硫酸法金红石型钛白粉理论毛利:
  毛利 = TiO2现货价 - (2.0 * 钛精矿46%现货价 + 3.5 * 浓硫酸98%现货价) - 3800
- 硫酸法边际现金保本线:
  现金保本线 = 2.0 * 钛精矿46%现货价 + 3.5 * 浓硫酸98%现货价 + 2600
- 原材料输入来源:
  - 钛白粉现货出厂价 (PPID: 645, 金红石型R2硫酸法)
  - 钛精矿现货出厂价 (PPID: 1627, 46%攀西品位)
  - 浓硫酸现货出厂价 (PPID: 236, 98%工业浓硫酸；2026-09 校准：原 515 为空数据页，经 100ppi 商品页核验为 236)
  优先从 Curated chemical_spot_price.parquet 读取，若不存在则回退至 100ppi RAW JSON 快照。
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.fetcher.industry.chemicals.collectors.spreads import ChemicalSpreadCalculator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tio2_spreads")

BASE_DIR = Path(__file__).resolve().parents[1]
CURATED_DIR = BASE_DIR / "data" / "curated"
RAW_DIR = BASE_DIR / "data" / "raw"
SPREAD_RAW_CSV = RAW_DIR / "industry" / "chemicals" / "chemical_spreads.csv"
SPREAD_CURATED_PARQUET = CURATED_DIR / "industry" / "chemical_spreads.parquet"
PPI_RAW_DIR = RAW_DIR / "industry" / "chemicals" / "100ppi"


def _load_spot_series_from_snapshot(json_path: Path) -> pl.DataFrame:
    """从 100ppi RAW JSON 文件加载日度价格时序。"""
    if not json_path.exists():
        return pl.DataFrame(schema={"trade_date": pl.Date, "price": pl.Float64})
    data = json.loads(json_path.read_text(encoding="utf-8"))
    dates = data.get("dates", [])
    prices = data.get("prices", [])
    rows: list[dict[str, Any]] = []
    for d_str, p_val in zip(dates, prices, strict=False):
        if not d_str or p_val is None or p_val == "-":
            continue
        try:
            t_d = date.fromisoformat(str(d_str).strip())
            p = float(p_val)
            rows.append({"trade_date": t_d, "price": p})
        except (ValueError, TypeError):
            continue
    if not rows:
        return pl.DataFrame(schema={"trade_date": pl.Date, "price": pl.Float64})
    return pl.DataFrame(rows).sort("trade_date")


def _load_spot_daily(symbol: str, fallback_filename: str) -> pl.DataFrame:
    """加载单品种现货价格（Curated 优先，次选研报周度调查 CSV，后备 RAW 快照）。"""
    spot_file = CURATED_DIR / "industry" / "chemical_spot_price.parquet"
    if spot_file.exists():
        try:
            df = pl.read_parquet(spot_file)
            filtered = (
                df.filter(pl.col("symbol") == symbol)
                .select(
                    [pl.col("trade_date").cast(pl.Date), pl.col("spot_price_cny").alias("price")]
                )
                .sort("trade_date")
            )
            if not filtered.is_empty():
                return filtered
        except Exception as exc:
            logger.debug("从 Curated 读取 %s 现货失败: %s", symbol, exc)

    survey_csv = RAW_DIR / "industry" / "chemicals" / "operating_rates" / "expert_prices_survey.csv"
    if survey_csv.exists():
        try:
            survey_df = pl.read_csv(survey_csv)
            filtered_survey = (
                survey_df.filter(pl.col("symbol") == symbol)
                .select(
                    [
                        pl.col("trade_date").str.to_date("%Y-%m-%d"),
                        pl.col("spot_price_cny").cast(pl.Float64).alias("price"),
                    ]
                )
                .sort("trade_date")
            )
            if not filtered_survey.is_empty():
                return filtered_survey
        except Exception as exc:
            logger.debug("从 expert_prices_survey.csv 读取 %s 失败: %s", symbol, exc)

    return _load_spot_series_from_snapshot(PPI_RAW_DIR / fallback_filename)


def generate_tio2_weekly_spreads() -> pl.DataFrame:
    """生成钛白粉周频连续硫酸法金红石型理论价差与利润状态序列。"""
    tio2_df = _load_spot_daily("TiO2", "TiO2.json").rename({"price": "tio2_price"})
    ilmenite_df = _load_spot_daily("ilmenite", "ilmenite.json").rename({"price": "ilmenite_price"})
    h2so4_df = _load_spot_daily("H2SO4", "H2SO4.json").rename({"price": "h2so4_price"})

    if tio2_df.is_empty():
        logger.warning("未找到 TiO2 现货价格时序")
        return pl.DataFrame()

    tio2_sorted = tio2_df.sort("trade_date")
    ilmenite_sorted = ilmenite_df.sort("trade_date")
    h2so4_sorted = h2so4_df.sort("trade_date")

    merged = (
        tio2_sorted.join_asof(ilmenite_sorted, on="trade_date", strategy="backward")
        .join_asof(h2so4_sorted, on="trade_date", strategy="backward")
        .with_columns(
            [
                pl.col("ilmenite_price").forward_fill().backward_fill().fill_null(2200.0),
                # 硫酸 2026-09 起接入 Curated (H2SO4)；仅前向填充，避免回溯改写历史，
                # 历史缺失保持旧假设 350 元/吨并如实披露（真实酸价 2026 年已升至 1300+）
                pl.col("h2so4_price").forward_fill().fill_null(350.0),
            ]
        )
    )

    # 按周聚合：取当周最后一个交易日的价格作为周度代表
    weekly = (
        merged.with_columns(
            pl.col("trade_date").dt.year().alias("year"),
            pl.col("trade_date").dt.week().alias("week"),
        )
        .group_by(["year", "week"])
        .agg(
            [
                pl.col("trade_date").last().alias("trade_date"),
                pl.col("tio2_price").last().alias("tio2_price"),
                pl.col("ilmenite_price").last().alias("ilmenite_price"),
                pl.col("h2so4_price").last().alias("h2so4_price"),
            ]
        )
        .sort("trade_date")
    )

    calc = ChemicalSpreadCalculator(raw_dir=RAW_DIR / "industry")
    now_iso = datetime.now(UTC).isoformat()
    rows: list[dict[str, Any]] = []

    for r in weekly.iter_rows(named=True):
        t_d = r["trade_date"]
        p_tio2 = r["tio2_price"]
        p_ilmenite = r["ilmenite_price"]
        p_acid = r["h2so4_price"]

        margin = calc.calculate_tio2_sulfate_margin(p_tio2, p_ilmenite, p_acid)
        cash_breakeven = calc.calculate_tio2_sulfate_cash_cost(p_ilmenite, p_acid)
        raw_cost = round(2.0 * p_ilmenite + 3.5 * p_acid, 2)
        regime = calc.get_margin_regime(margin, product="tio2")

        rows.append(
            {
                "trade_date": t_d,
                "product_name": "钛白粉",
                "symbol": "TiO2",
                "process_type": "硫酸法金红石型",
                "product_price_cny": round(p_tio2, 2),
                "byproduct_price_cny": None,
                "raw_material_cost_cny": raw_cost,
                "spread_margin_cny": margin,
                "cash_breakeven_cost_cny": cash_breakeven,
                "margin_regime": regime,
                "source": "100ppi/Spot_Benchmark",
                "release_date": t_d,
                "collected_at": now_iso,
                "data_status": "spot_benchmark",
            }
        )

    df = pl.DataFrame(rows)
    if not df.is_empty():
        logger.info(
            "生成钛白粉周频连续基准价差: %d 周 (%s ~ %s)",
            len(df),
            df["trade_date"].min(),
            df["trade_date"].max(),
        )
    return df


def materialize_continuous_spreads() -> None:
    """合并现有价差记录与 TiO2 连续基准序列，并物化更新 Curated 事实表。"""
    benchmark_df = generate_tio2_weekly_spreads()
    if benchmark_df.is_empty():
        logger.warning("生成的 TiO2 基准价差序列为空，跳过物化")
        return

    actual_rows: list[dict[str, Any]] = []
    actual_tio2_dates: set[date] = set()

    if SPREAD_RAW_CSV.exists():
        with SPREAD_RAW_CSV.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                d_str = str(row.get("trade_date") or "").strip()
                if not d_str:
                    continue
                t_date = date.fromisoformat(d_str)
                is_tio2_actual = row.get("symbol") == "TiO2" and row.get("data_status") in {
                    "actual",
                    "source_reported",
                }
                if is_tio2_actual:
                    actual_tio2_dates.add(t_date)
                    actual_rows.append(row)
                elif row.get("symbol") != "TiO2":
                    actual_rows.append(row)

    merged_rows = list(actual_rows)
    added_count = 0
    for r in benchmark_df.to_dicts():
        t_d = r["trade_date"]
        # 避免与真实 actual 记录重叠
        has_overlap = any(abs((t_d - exist_d).days) < 4 for exist_d in actual_tio2_dates)
        if not has_overlap:
            merged_rows.append(
                {
                    "trade_date": t_d.isoformat(),
                    "product_name": r["product_name"],
                    "symbol": r["symbol"],
                    "process_type": r["process_type"],
                    "product_price_cny": f"{r['product_price_cny']:.2f}",
                    "byproduct_price_cny": "",
                    "raw_material_cost_cny": f"{r['raw_material_cost_cny']:.2f}",
                    "spread_margin_cny": f"{r['spread_margin_cny']:.2f}",
                    "cash_breakeven_cost_cny": f"{r['cash_breakeven_cost_cny']:.2f}",
                    "margin_regime": r["margin_regime"],
                    "source": r["source"],
                    "release_date": r["release_date"].isoformat(),
                    "collected_at": r["collected_at"],
                    "data_status": r["data_status"],
                }
            )
            added_count += 1

    merged_rows.sort(key=lambda item: (item["product_name"], item["trade_date"]))

    fieldnames = [
        "trade_date",
        "product_name",
        "symbol",
        "process_type",
        "product_price_cny",
        "byproduct_price_cny",
        "raw_material_cost_cny",
        "spread_margin_cny",
        "cash_breakeven_cost_cny",
        "margin_regime",
        "source",
        "release_date",
        "collected_at",
        "data_status",
    ]

    with SPREAD_RAW_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged_rows)

    logger.info(
        "已更新 RAW CSV: %s (总行数: %d, 新增 TiO2 基准周数: %d)",
        SPREAD_RAW_CSV,
        len(merged_rows),
        added_count,
    )

    calc = ChemicalSpreadCalculator(raw_dir=RAW_DIR / "industry")
    curated_df = calc.build_historical_spreads()
    if not curated_df.is_empty():
        SPREAD_CURATED_PARQUET.parent.mkdir(parents=True, exist_ok=True)
        curated_df.write_parquet(SPREAD_CURATED_PARQUET)
        logger.info("成功物化 Curated 事实表: %s (%d 行)", SPREAD_CURATED_PARQUET, len(curated_df))
    else:
        logger.warning("物化 Curated 事实表为空！")


if __name__ == "__main__":
    materialize_continuous_spreads()
