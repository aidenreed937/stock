"""daily_basic 数据质量治理与量纲修复工具。

负责清洗 RAW 侧混杂的分区记录，恢复丢失的估值指标，并将 Curated 侧市值统一收敛至标准“元”量纲。
"""

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from stock.data.normalizer.bar_normalizer import infer_market_exchange_currency
from stock.utils.date import parse_mixed_date
from stock.utils.logger import logger

_RAW_DIR = Path("data/raw/tushare/market=CN/daily_basic")
_CURATED_DIR = Path("data/curated/tushare/market=CN/daily_basic")


def _is_artifact(path: Path) -> bool:
    return path.name.endswith((".bak.parquet", ".tmp.parquet", ".migration.tmp.parquet"))


def clean_partition_daily_basic(
    raw_path: Path,
    curated_path: Path | None,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """清洗单个分区的 RAW 与 Curated daily_basic 数据。"""
    raw_df = pl.read_parquet(raw_path)
    raw_before_count = len(raw_df)

    date_col = "trade_date" if "trade_date" in raw_df.columns else "date"
    sym_col = "ts_code" if "ts_code" in raw_df.columns else "symbol"

    date_str = pl.col(date_col).cast(pl.Utf8, strict=False).str.strip_chars()
    is_hyphen = date_str.str.contains("-")

    # 1. 拆分原始 18~21 列记录与被裁剪的 8 列记录
    raw_full = raw_df.filter(~is_hyphen)
    raw_hyphen = raw_df.filter(is_hyphen)

    raw_full_keys = (
        raw_full.select(
            [
                pl.col(sym_col).cast(pl.Utf8).alias("_sym"),
                pl.col(date_col).cast(pl.Utf8).str.replace_all("-", "").alias("_date"),
            ]
        )
        if not raw_full.is_empty()
        else pl.DataFrame(schema={"_sym": pl.Utf8, "_date": pl.Utf8})
    )

    # 仅保留在 raw_full 中不存在的 raw_hyphen 行
    if not raw_hyphen.is_empty() and not raw_full.is_empty():
        hyphen_with_keys = raw_hyphen.with_columns(
            [
                pl.col(sym_col).cast(pl.Utf8).alias("_sym"),
                pl.col(date_col).cast(pl.Utf8).str.replace_all("-", "").alias("_date"),
            ]
        )
        hyphen_only = hyphen_with_keys.join(
            raw_full_keys, on=["_sym", "_date"], how="anti"
        ).drop(["_sym", "_date"])
    else:
        hyphen_only = raw_hyphen

    # 组合为纯净 RAW 数据 (全部 trade_date 规整为 YYYYMMDD)
    if not hyphen_only.is_empty():
        hyphen_clean = hyphen_only.with_columns(
            pl.col(date_col).cast(pl.Utf8).str.replace_all("-", "").alias(date_col)
        )
        cleaned_raw = pl.concat([raw_full, hyphen_clean], how="diagonal_relaxed")
    else:
        cleaned_raw = raw_full

    cleaned_raw_count = len(cleaned_raw)

    # 2. 构建标准化的 Curated 数据
    # 对 raw_full: total_mv/circ_mv 单位为万元 -> * 10000.0
    # 对 hyphen_only: total_mv/circ_mv 单位已为元 -> * 1.0
    cur_parts = []
    if not raw_full.is_empty():
        rf_cur = raw_full.with_columns(
            [
                (pl.col("total_mv").cast(pl.Float64, strict=False) * 10000.0).alias("total_mv")
                if "total_mv" in raw_full.columns
                else pl.lit(None, dtype=pl.Float64).alias("total_mv"),
                (pl.col("circ_mv").cast(pl.Float64, strict=False) * 10000.0).alias("circ_mv")
                if "circ_mv" in raw_full.columns
                else pl.lit(None, dtype=pl.Float64).alias("circ_mv"),
            ]
        )
        cur_parts.append(rf_cur)

    if not hyphen_only.is_empty():
        ho_cur = hyphen_only.with_columns(
            [
                (pl.col("total_mv").cast(pl.Float64, strict=False) * 1.0).alias("total_mv")
                if "total_mv" in hyphen_only.columns
                else pl.lit(None, dtype=pl.Float64).alias("total_mv"),
                (pl.col("circ_mv").cast(pl.Float64, strict=False) * 1.0).alias("circ_mv")
                if "circ_mv" in hyphen_only.columns
                else pl.lit(None, dtype=pl.Float64).alias("circ_mv"),
            ]
        )
        cur_parts.append(ho_cur)

    cleaned_cur = pl.concat(cur_parts, how="diagonal_relaxed") if cur_parts else pl.DataFrame()

    if not cleaned_cur.is_empty():
        # 统一 symbol 与 trade_date
        if "ts_code" in cleaned_cur.columns and "symbol" not in cleaned_cur.columns:
            cleaned_cur = cleaned_cur.rename({"ts_code": "symbol"})
        elif "ts_code" in cleaned_cur.columns and "symbol" in cleaned_cur.columns:
            cleaned_cur = cleaned_cur.with_columns(
                pl.coalesce([pl.col("symbol"), pl.col("ts_code")]).alias("symbol")
            ).drop("ts_code")

        cleaned_cur = cleaned_cur.with_columns(
            parse_mixed_date(date_col).alias("trade_date")
        )
        if date_col != "trade_date" and date_col in cleaned_cur.columns:
            cleaned_cur = cleaned_cur.drop(date_col)

        # 补齐元数据
        market_expr, exch_expr, curr_expr = infer_market_exchange_currency(
            pl.col("symbol"), "tushare"
        )
        partition_name = "/".join(p for p in raw_path.parts if p.startswith(("year=", "month=")))
        now_utc = datetime.now(timezone.utc)

        meta_exprs = [
            pl.col("data_source").fill_null("tushare").alias("data_source")
            if "data_source" in cleaned_cur.columns
            else pl.lit("tushare").alias("data_source"),
            market_expr.alias("market")
            if "market" not in cleaned_cur.columns
            else pl.col("market").fill_null(market_expr).alias("market"),
            exch_expr.alias("exchange")
            if "exchange" not in cleaned_cur.columns
            else pl.col("exchange").fill_null(exch_expr).alias("exchange"),
            curr_expr.alias("currency")
            if "currency" not in cleaned_cur.columns
            else pl.col("currency").fill_null(curr_expr).alias("currency"),
            pl.lit("raw").alias("adjustment")
            if "adjustment" not in cleaned_cur.columns
            else pl.col("adjustment").fill_null("raw").alias("adjustment"),
            pl.lit("v2").alias("schema_version")
            if "schema_version" not in cleaned_cur.columns
            else pl.col("schema_version").fill_null("v2").alias("schema_version"),
            pl.lit("daily_basic").alias("source_endpoint")
            if "source_endpoint" not in cleaned_cur.columns
            else pl.col("source_endpoint").fill_null("daily_basic").alias("source_endpoint"),
            pl.lit(f"repair:daily_basic:{partition_name or raw_path.name}").alias("request_id")
            if "request_id" not in cleaned_cur.columns
            else pl.col("request_id").alias("request_id"),
            pl.lit(now_utc).alias("updated_at")
            if "updated_at" not in cleaned_cur.columns
            else pl.col("updated_at").fill_null(now_utc).alias("updated_at"),
        ]
        cleaned_cur = cleaned_cur.with_columns(meta_exprs)

        # 按主键排序与去重
        cleaned_cur = cleaned_cur.sort(["symbol", "trade_date"]).unique(
            subset=["symbol", "trade_date"], keep="last", maintain_order=True
        )

    cur_before_count = 0
    if curated_path and curated_path.exists():
        try:
            cur_before_count = len(pl.read_parquet(curated_path))
        except Exception:
            cur_before_count = 0

    cur_after_count = len(cleaned_cur)

    # 3. 实际写回 (若 apply=True)
    if apply:
        # 写 RAW
        raw_tmp = raw_path.with_suffix(".tmp.parquet")
        raw_bak = raw_path.with_suffix(".bak.parquet")
        cleaned_raw.write_parquet(raw_tmp)
        if not raw_bak.exists():
            shutil.copy2(raw_path, raw_bak)
        raw_tmp.replace(raw_path)

        # 写 Curated
        if curated_path:
            curated_path.parent.mkdir(parents=True, exist_ok=True)
            cur_tmp = curated_path.with_suffix(".tmp.parquet")
            cur_bak = curated_path.with_suffix(".bak.parquet")
            cleaned_cur.write_parquet(cur_tmp)
            if curated_path.exists() and not cur_bak.exists():
                shutil.copy2(curated_path, cur_bak)
            cur_tmp.replace(curated_path)

    # 检查异常市值数 (total_mv >= 1e12)
    abnormal_mv_count = 0
    if "total_mv" in cleaned_cur.columns:
        abnormal_mv_count = int(
            cleaned_cur.filter(pl.col("total_mv") >= 1e12).height
        )

    return {
        "raw_path": str(raw_path),
        "raw_before": raw_before_count,
        "raw_after": cleaned_raw_count,
        "cur_before": cur_before_count,
        "cur_after": cur_after_count,
        "abnormal_mv_count": abnormal_mv_count,
    }


def repair_all_daily_basic(
    raw_root: str | Path = _RAW_DIR,
    curated_root: str | Path = _CURATED_DIR,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """遍历并修复全量 daily_basic 数据。"""
    raw_base = Path(raw_root)
    cur_base = Path(curated_root)

    raw_files = sorted(
        [p for p in raw_base.rglob("*.parquet") if not _is_artifact(p)]
    ) if raw_base.exists() else []

    results = []
    total_raw_before = 0
    total_raw_after = 0
    total_cur_before = 0
    total_cur_after = 0
    total_abnormal_mv = 0

    for raw_file in raw_files:
        # 计算对应的 curated 路径
        rel = raw_file.relative_to(raw_base)
        cur_file = cur_base / rel

        res = clean_partition_daily_basic(raw_file, cur_file, apply=apply)
        results.append(res)

        total_raw_before += res["raw_before"]
        total_raw_after += res["raw_after"]
        total_cur_before += res["cur_before"]
        total_cur_after += res["cur_after"]
        total_abnormal_mv += res["abnormal_mv_count"]

    logger.info(
        f"daily_basic 修复完成 [apply={apply}]: 处理文件 {len(raw_files)} 个, "
        f"RAW 行数: {total_raw_before:,} -> {total_raw_after:,}, "
        f"Curated 行数: {total_cur_before:,} -> {total_cur_after:,}, "
        f"异常市值 (>=1e12) 行数: {total_abnormal_mv}"
    )

    return {
        "files_processed": len(raw_files),
        "raw_before": total_raw_before,
        "raw_after": total_raw_after,
        "cur_before": total_cur_before,
        "cur_after": total_cur_after,
        "abnormal_mv_count": total_abnormal_mv,
        "applied": apply,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="daily_basic 数据质量与量纲修复工具")
    parser.add_argument("--raw-root", default=str(_RAW_DIR), help="RAW daily_basic 根目录")
    parser.add_argument(
        "--curated-root",
        default=str(_CURATED_DIR),
        help="Curated daily_basic 根目录",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="执行实际写入与替换备份 (默认只读预览)",
    )
    args = parser.parse_args()

    repair_all_daily_basic(args.raw_root, args.curated_root, apply=args.apply)


if __name__ == "__main__":
    main()
