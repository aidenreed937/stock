#!/usr/bin/env python3
"""钛白粉双雄（龙佰集团 002601.SZ 与钛能化学 002145.SZ）企业动态加工毛利时序生成器。

模型规范：
- 依据 config/industry/chemicals/tio2/cost_models.yaml（工艺理论模型）与 company_projections.yaml（企业微观模型单一信任源）；
- 整合 TiO2 现货出厂基准、攀西钛精矿现货、浓硫酸现货等多源输入；
- 动态测算龙佰集团（一体化矿石自给+硫酸/氯化双路线）与钛能化学（纯外购硫酸法加工费）单吨毛利；
- 计算 60 日滚动平滑均值 (Rolling 60D Mean)，模拟物理库存周转与月末加权平均结转时滞；
- 物化输出至 data/curated/industry/chemical_company_margins.parquet 与 RAW CSV。
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
logger = logging.getLogger("company_margins")

BASE_DIR = Path(__file__).resolve().parents[1]
CURATED_DIR = BASE_DIR / "data" / "curated"
RAW_DIR = BASE_DIR / "data" / "raw"
COMPANY_MARGINS_RAW_CSV = RAW_DIR / "industry" / "chemicals" / "chemical_company_margins.csv"
COMPANY_MARGINS_CURATED_PARQUET = CURATED_DIR / "industry" / "chemical_company_margins.parquet"
PPI_RAW_DIR = RAW_DIR / "industry" / "chemicals" / "100ppi"

COMPANY_SYMBOLS = ["002601.SZ", "002145.SZ"]


def _load_spot_series_from_snapshot(json_path: Path) -> pl.DataFrame:
    """从 100ppi RAW JSON 快照加载日度价格。"""
    if not json_path.exists():
        return pl.DataFrame(schema={"trade_date": pl.Date, "price": pl.Float64})
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return pl.DataFrame(schema={"trade_date": pl.Date, "price": pl.Float64})
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
    """加载单品种现货日频价格 (Curated -> 调研 CSV -> RAW 快照)。"""
    spot_file = CURATED_DIR / "industry" / "chemical_spot_price.parquet"
    if spot_file.exists():
        try:
            df = pl.read_parquet(spot_file)
            filtered = (
                df.filter(pl.col("symbol") == symbol)
                .select(
                    [
                        pl.col("trade_date").cast(pl.Date),
                        pl.col("spot_price_cny").alias("price"),
                    ]
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


def generate_company_margins_weekly(
    calc: ChemicalSpreadCalculator | None = None,
) -> pl.DataFrame:
    """生成企业周频动态理论毛利与滚动平滑指标。"""
    calculator = calc or ChemicalSpreadCalculator(raw_dir=RAW_DIR / "industry")

    tio2_df = _load_spot_daily("TiO2", "TiO2.json").rename({"price": "tio2_price"})
    ilmenite_df = _load_spot_daily("ilmenite", "ilmenite.json").rename({"price": "ilmenite_price"})
    h2so4_df = _load_spot_daily("H2SO4", "H2SO4.json").rename({"price": "h2so4_price"})

    if tio2_df.is_empty():
        logger.warning("未找到 TiO2 现货基准价格时序")
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
                pl.col("h2so4_price").forward_fill().backward_fill().fill_null(350.0),
            ]
        )
    )

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

    now_iso = datetime.now(UTC).isoformat()
    raw_rows: list[dict[str, Any]] = []

    for r in weekly.iter_rows(named=True):
        t_d = r["trade_date"]
        p_tio2 = float(r["tio2_price"])
        p_ilmenite = float(r["ilmenite_price"])
        p_acid = float(r["h2so4_price"])

        for sym in COMPANY_SYMBOLS:
            res = calculator.calculate_tio2_company_margins(
                symbol=sym,
                tio2_price=p_tio2,
                ilmenite_price=p_ilmenite,
                acid_price=p_acid,
            )
            raw_rows.append(
                {
                    "trade_date": t_d,
                    "symbol": res["symbol"],
                    "company_name": res["company_name"],
                    "tio2_spot_price_cny": round(p_tio2, 2),
                    "ilmenite_price_cny": round(p_ilmenite, 2),
                    "acid_price_cny": round(p_acid, 2),
                    "unit_gross_margin_cny": res["unit_gross_margin_cny"],
                    "unit_cash_margin_cny": res["unit_cash_margin_cny"],
                    "gross_margin_ratio": res["gross_margin_ratio"],
                    "alpha_spread_cny": res["alpha_spread_cny"],
                    "sulfate_alpha_cny": res["sulfate_alpha_cny"],
                    "sulfate_margin_cny": res["sulfate_margin_cny"],
                    "chloride_margin_cny": res["chloride_margin_cny"],
                    "blended_cash_cost_cny": res["blended_cash_cost_cny"],
                    "ore_captive_ratio": res["ore_captive_ratio"],
                    "source": "100ppi/Spot_Benchmark",
                    "data_status": "spot_benchmark",
                    "collected_at": now_iso,
                }
            )

    if not raw_rows:
        return pl.DataFrame()

    df = pl.DataFrame(raw_rows)

    # 计算 8 周 (~60日) 移动平均平滑指标
    df = df.sort(["symbol", "trade_date"]).with_columns(
        [
            pl.col("unit_gross_margin_cny")
            .rolling_mean(window_size=8, min_samples=1)
            .over("symbol")
            .round(2)
            .alias("rolling_60d_gross_margin_cny"),
            pl.col("gross_margin_ratio")
            .rolling_mean(window_size=8, min_samples=1)
            .over("symbol")
            .round(4)
            .alias("rolling_60d_gpm_ratio"),
        ]
    )

    # 规范列序
    cols = [
        "trade_date",
        "symbol",
        "company_name",
        "tio2_spot_price_cny",
        "ilmenite_price_cny",
        "acid_price_cny",
        "unit_gross_margin_cny",
        "unit_cash_margin_cny",
        "gross_margin_ratio",
        "alpha_spread_cny",
        "sulfate_alpha_cny",
        "sulfate_margin_cny",
        "chloride_margin_cny",
        "blended_cash_cost_cny",
        "ore_captive_ratio",
        "rolling_60d_gross_margin_cny",
        "rolling_60d_gpm_ratio",
        "source",
        "data_status",
        "collected_at",
    ]
    return df.select(cols).sort(["trade_date", "symbol"])


def materialize_company_margins() -> None:
    """生成并物化钛白粉核心企业动态毛利事实表。"""
    df = generate_company_margins_weekly()
    if df.is_empty():
        logger.warning("生成的企业毛利时序为空，跳过物化")
        return

    # 保存 Curated Parquet
    COMPANY_MARGINS_CURATED_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(COMPANY_MARGINS_CURATED_PARQUET)
    logger.info(
        "成功物化 Curated 事实表: %s (%d 行, 跨度 %s ~ %s)",
        COMPANY_MARGINS_CURATED_PARQUET,
        len(df),
        df["trade_date"].min(),
        df["trade_date"].max(),
    )

    # 保存 RAW CSV
    COMPANY_MARGINS_RAW_CSV.parent.mkdir(parents=True, exist_ok=True)
    csv_rows = df.to_dicts()
    fieldnames = list(csv_rows[0].keys())
    with COMPANY_MARGINS_RAW_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in csv_rows:
            if isinstance(r.get("trade_date"), date):
                r["trade_date"] = r["trade_date"].isoformat()
            writer.writerow(r)
    logger.info("已同步更新 RAW CSV: %s (%d 行)", COMPANY_MARGINS_RAW_CSV, len(csv_rows))


if __name__ == "__main__":
    materialize_company_margins()
