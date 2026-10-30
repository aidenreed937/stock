#!/usr/bin/env python3
"""纯碱 (SA) 连续周频理论价差与利润序列生成器。

模型规范 (唯一信任源: config/industry/chemicals/soda_ash/cost_models.yaml):
- 联碱法双吨理论利润:
  双吨利润 = 纯碱价格 + 氯化铵价格 - (1.2 * 原盐 + 0.135 * 合成氨 + 0.4 * 动力煤) - 450
- 原材料输入:
  - 纯碱价格: 场内 SA 主力连续合约周结算价
  - 动力煤价格: CCTD Q5500 平仓价 (data/curated/industry/coal_market.parquet)
  - 合成氨/尿素价格: 场内 UR 主力合约周结算价 * 1.15 (折合成氨基准)
  - 氯化铵价格: UR 主力合约 * 0.45 (氮当量折算)
  - 工业原盐: 280.0 元/吨
  - 现金加工与固定费: 450.0 元/吨 (依据 cost_models.yaml)
"""

from __future__ import annotations

import csv
import logging
from datetime import date, datetime
from pathlib import Path

import polars as pl
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("soda_ash_spreads")

BASE_DIR = Path(__file__).resolve().parents[1]
CURATED_DIR = BASE_DIR / "data" / "curated"
RAW_DIR = BASE_DIR / "data" / "raw"
SPREAD_RAW_CSV = RAW_DIR / "industry" / "chemicals" / "chemical_spreads.csv"
SPREAD_CURATED_PARQUET = CURATED_DIR / "industry" / "chemical_spreads.parquet"
COST_MODELS_PATH = BASE_DIR / "config" / "industry" / "chemicals" / "soda_ash" / "cost_models.yaml"


def _load_soda_ash_cost_config() -> tuple[dict[str, float], float, dict[str, float]]:
    """从最新 cost_models.yaml 提取联碱双吨单耗、固定加工费与利润区间阈值。"""
    default_coeffs = {"raw_salt": 1.2, "synthetic_ammonia": 0.135, "thermal_coal": 0.4}
    default_fc = 450.0
    default_thresholds = {"high_profit": 300.0, "profitable": 0.0, "near_breakeven": -150.0}

    if not COST_MODELS_PATH.exists():
        return default_coeffs, default_fc, default_thresholds

    try:
        data = yaml.safe_load(COST_MODELS_PATH.read_text(encoding="utf-8")) or {}
        hou_cfg = data.get("models", {}).get("hou_process", {})
        coeffs_raw = hou_cfg.get("coefficients", {})
        coeffs = {
            "raw_salt": float(coeffs_raw.get("raw_salt", 1.2)),
            "synthetic_ammonia": float(coeffs_raw.get("synthetic_ammonia", 0.135)),
            "thermal_coal": float(coeffs_raw.get("thermal_coal", 0.4)),
        }
        fc = float(hou_cfg.get("fixed_cost", 450.0))
        th_raw = data.get("regime_thresholds", {})
        thresholds = {
            "high_profit": float(th_raw.get("high_profit", 300.0)),
            "profitable": float(th_raw.get("profitable", 0.0)),
            "near_breakeven": float(th_raw.get("near_breakeven", -150.0)),
        }
        return coeffs, fc, thresholds
    except Exception as exc:
        logger.warning("解析 cost_models.yaml 异常: %s，使用默认参数", exc)
        return default_coeffs, default_fc, default_thresholds


def generate_soda_ash_weekly_spreads() -> pl.DataFrame:
    coeffs, fixed_cost, thresholds = _load_soda_ash_cost_config()
    salt_coeff = coeffs["raw_salt"]
    nh3_coeff = coeffs["synthetic_ammonia"]
    coal_coeff = coeffs["thermal_coal"]
    # 1. 读取期货日线数据
    futures_df = pl.read_parquet(CURATED_DIR / "industry" / "futures_daily.parquet")
    sa_df = (
        futures_df.filter(pl.col("symbol") == "SA")
        .select(["trade_date", "settle", "close"])
        .sort("trade_date")
    )
    ur_df = (
        futures_df.filter(pl.col("symbol") == "UR")
        .select(
            ["trade_date", pl.col("settle").alias("ur_settle"), pl.col("close").alias("ur_close")]
        )
        .sort("trade_date")
    )

    # 2. 读取煤炭周度事实表
    coal_df = (
        pl.read_parquet(CURATED_DIR / "industry" / "coal_market.parquet")
        .select(["trade_date", "q5500_fob_price_cny"])
        .sort("trade_date")
    )

    # 3. 读取 100ppi 现货出厂基准表 (若存在)
    spot_file = CURATED_DIR / "industry" / "chemical_spot_price.parquet"
    spot_sa_weekly = pl.DataFrame()
    spot_ur_weekly = pl.DataFrame()
    if spot_file.exists():
        spot_df = pl.read_parquet(spot_file)
        sa_spot = (
            spot_df.filter(pl.col("symbol") == "SA_light")
            .select(["trade_date", pl.col("spot_price_cny").alias("sa_spot_light")])
            .sort("trade_date")
        )
        sa_heavy_spot = (
            spot_df.filter(pl.col("symbol") == "SA")
            .select(["trade_date", pl.col("spot_price_cny").alias("sa_spot_heavy")])
            .sort("trade_date")
        )
        ur_spot = (
            spot_df.filter(pl.col("symbol") == "UR")
            .select(["trade_date", pl.col("spot_price_cny").alias("ur_spot")])
            .sort("trade_date")
        )
        sa_spot_all = sa_spot.join(sa_heavy_spot, on="trade_date", how="full", coalesce=True)
        if not sa_spot_all.is_empty():
            spot_sa_weekly = (
                sa_spot_all.with_columns(
                    pl.col("trade_date").dt.year().alias("year"),
                    pl.col("trade_date").dt.week().alias("week"),
                )
                .group_by(["year", "week"])
                .agg(
                    [
                        pl.col("trade_date").last().alias("trade_date"),
                        pl.col("sa_spot_light").last().alias("sa_spot_light"),
                        pl.col("sa_spot_heavy").last().alias("sa_spot_heavy"),
                    ]
                )
                .sort("trade_date")
            )
        if not ur_spot.is_empty():
            spot_ur_weekly = (
                ur_spot.with_columns(
                    pl.col("trade_date").dt.year().alias("year"),
                    pl.col("trade_date").dt.week().alias("week"),
                )
                .group_by(["year", "week"])
                .agg(
                    [
                        pl.col("trade_date").last().alias("trade_date"),
                        pl.col("ur_spot").last().alias("ur_spot"),
                    ]
                )
                .sort("trade_date")
            )

    # 4. 将日线数据对齐为周度 (取每周最后一个交易日)
    sa_weekly = (
        sa_df.with_columns(
            pl.col("trade_date").dt.year().alias("year"),
            pl.col("trade_date").dt.week().alias("week"),
        )
        .group_by(["year", "week"])
        .agg(
            [
                pl.col("trade_date").last().alias("trade_date"),
                pl.col("settle").last().alias("sa_price"),
            ]
        )
        .sort("trade_date")
    )

    ur_weekly = (
        ur_df.with_columns(
            pl.col("trade_date").dt.year().alias("year"),
            pl.col("trade_date").dt.week().alias("week"),
        )
        .group_by(["year", "week"])
        .agg(
            [
                pl.col("trade_date").last().alias("trade_date"),
                pl.col("ur_settle").last().alias("ur_price"),
            ]
        )
        .sort("trade_date")
    )

    # 5. 合并纯碱、尿素、煤炭与现货基准 (按业务周对齐)
    coal_weekly = (
        coal_df.with_columns(
            pl.col("trade_date").dt.year().alias("year"),
            pl.col("trade_date").dt.week().alias("week"),
        )
        .group_by(["year", "week"])
        .agg(pl.col("q5500_fob_price_cny").last().alias("coal_price"))
    )

    merged = (
        sa_weekly.join(
            ur_weekly.select(["year", "week", "ur_price"]),
            on=["year", "week"],
            how="left",
        )
        .join(coal_weekly, on=["year", "week"], how="left")
        .sort("trade_date")
    )

    if not spot_sa_weekly.is_empty():
        merged = merged.join(
            spot_sa_weekly.select(["year", "week", "sa_spot_light", "sa_spot_heavy"]),
            on=["year", "week"],
            how="left",
        )
    else:
        merged = merged.with_columns(
            [
                pl.lit(None, dtype=pl.Float64).alias("sa_spot_light"),
                pl.lit(None, dtype=pl.Float64).alias("sa_spot_heavy"),
            ]
        )

    if not spot_ur_weekly.is_empty():
        merged = merged.join(
            spot_ur_weekly.select(["year", "week", "ur_spot"]),
            on=["year", "week"],
            how="left",
        )
    else:
        merged = merged.with_columns(pl.lit(None, dtype=pl.Float64).alias("ur_spot"))

    # 煤炭与尿素向前填充 (防止微小时滞)
    merged = merged.with_columns(
        [
            pl.col("coal_price").forward_fill().backward_fill(),
            pl.col("ur_price").forward_fill().backward_fill(),
        ]
    )

    # 6. 计算双吨理论成本与利润
    salt_price = 280.0
    fixed_cost = 450.0

    calc_rows = []
    now_iso = datetime.now().astimezone().isoformat()

    for r in merged.iter_rows(named=True):
        t_d = r["trade_date"]
        sa_futures_p = r["sa_price"]
        ur_futures_p = r["ur_price"]
        coal_p = r["coal_price"]
        sa_spot_light = r.get("sa_spot_light")
        ur_spot = r.get("ur_spot")

        if sa_futures_p is None or coal_p is None:
            continue

        # 现货优先：当且仅当 100ppi 现货出厂价存在时使用现货价格
        has_spot = sa_spot_light is not None and sa_spot_light > 0
        sa_p = sa_spot_light if has_spot else sa_futures_p
        ur_p = ur_spot if (ur_spot is not None and ur_spot > 0) else ur_futures_p

        # 副产氯化铵价格 (按尿素折算)
        nh4cl_p = round(ur_p * 0.45, 1) if ur_p else 450.0
        # 合成氨折算价
        nh3_p = round(ur_p * 1.15, 1) if ur_p else 2800.0

        # 原材料成本: salt_coeff*盐 + nh3_coeff*氨 + coal_coeff*煤
        raw_cost = round(salt_coeff * salt_price + nh3_coeff * nh3_p + coal_coeff * coal_p, 2)
        # 双吨理论利润
        margin = round((sa_p + nh4cl_p) - raw_cost - fixed_cost, 2)
        cash_breakeven = round(raw_cost + fixed_cost - nh4cl_p, 2)

        # 利润状态判定 (依据 cost_models.yaml regime_thresholds)
        if margin > thresholds["high_profit"]:
            regime = "high_profit"
        elif margin >= thresholds["profitable"]:
            regime = "profitable"
        elif margin >= thresholds["near_breakeven"]:
            regime = "near_breakeven"
        else:
            regime = "deep_loss"

        source = "100ppi/Spot_Benchmark" if has_spot else "Exchange_Official/CZCE_Futures_Benchmark"
        data_status = "spot_benchmark" if has_spot else "benchmark"

        calc_rows.append(
            {
                "trade_date": t_d,
                "product_name": "纯碱",
                "symbol": "SA",
                "process_type": "联碱法双吨",
                "product_price_cny": sa_p,
                "byproduct_price_cny": nh4cl_p,
                "raw_material_cost_cny": raw_cost,
                "spread_margin_cny": margin,
                "cash_breakeven_cost_cny": cash_breakeven,
                "margin_regime": regime,
                "source": source,
                "release_date": t_d,
                "collected_at": now_iso,
                "data_status": data_status,
            }
        )

    benchmark_df = pl.DataFrame(calc_rows)
    min_date_str = str(benchmark_df["trade_date"].min())
    max_date_str = str(benchmark_df["trade_date"].max())
    spot_count = len(benchmark_df.filter(pl.col("data_status") == "spot_benchmark"))
    logger.info(
        f"生成纯碱周频连续基准价差: {len(benchmark_df)} 周 ({min_date_str} ~ {max_date_str})，其中现货出厂基准 {spot_count} 周"
    )
    return benchmark_df


def materialize_continuous_spreads() -> None:
    """合并现有现货采样记录与连续基准序列，并物化 Curated 事实表。"""
    benchmark_df = generate_soda_ash_weekly_spreads()

    actual_rows = []
    actual_sa_dates = set()
    if SPREAD_RAW_CSV.exists():
        with SPREAD_RAW_CSV.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                d_str = row.get("trade_date", "").strip()
                if not d_str:
                    continue
                t_date = date.fromisoformat(d_str)
                # 仅保留真实抽样调查记录 (actual)，基准记录通过当前最新数据重新生成
                is_actual = row.get("data_status") == "actual" or "Longzhong" in row.get(
                    "source", ""
                )
                if is_actual:
                    actual_rows.append(row)
                    if row.get("symbol") == "SA":
                        actual_sa_dates.add(t_date)

    # 过滤掉与现有 actual SA 记录在同一周内的 benchmark 记录 (Ground Truth 优先)
    merged_rows = list(actual_rows)
    added_count = 0
    for r in benchmark_df.to_dicts():
        t_d = r["trade_date"]
        has_overlap = any(abs((t_d - exist_d).days) < 4 for exist_d in actual_sa_dates)
        if not has_overlap:
            merged_rows.append(
                {
                    "trade_date": t_d.isoformat(),
                    "product_name": r["product_name"],
                    "symbol": r["symbol"],
                    "process_type": r["process_type"],
                    "product_price_cny": f"{r['product_price_cny']:.2f}",
                    "byproduct_price_cny": f"{r['byproduct_price_cny']:.2f}"
                    if r["byproduct_price_cny"] is not None
                    else "",
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

    # 排序
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
        f"已更新 RAW CSV: {SPREAD_RAW_CSV} (总行数: {len(merged_rows)}, 新增基准周数: {added_count})"
    )

    # 重新构建 Curated Parquet
    from stock_data.fetcher.industry.chemicals.collectors.spreads import ChemicalSpreadCalculator

    calc = ChemicalSpreadCalculator(raw_dir=RAW_DIR / "industry")
    curated_df = calc.build_historical_spreads()
    if not curated_df.is_empty():
        SPREAD_CURATED_PARQUET.parent.mkdir(parents=True, exist_ok=True)
        curated_df.write_parquet(SPREAD_CURATED_PARQUET)
        logger.info(f"成功物化 Curated 事实表: {SPREAD_CURATED_PARQUET} ({len(curated_df)} 行)")
    else:
        logger.warning("物化 Curated 事实表为空！")


if __name__ == "__main__":
    materialize_continuous_spreads()
