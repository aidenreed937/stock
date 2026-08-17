"""数据完整性审计差异集中修复工具 (repair_audit_discrepancies.py)。"""

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from stock_core.utils.logger import logger
from stock_data.cleaner.bar_cleaner import BarDataCleaner
from stock_data.cleaner.generic_cleaner import GenericCleaner
from stock_data.normalizer.bar_normalizer import (
    BarDataNormalizer,
    infer_market_exchange_currency,
)
from stock_data.normalizer.generic_normalizer import GenericNormalizer
from stock_data.normalizer.unit_normalizer import UnitNormalizer
from stock_data.storage.compat import StorageCompat


def _is_artifact(path: Path) -> bool:
    return path.name.endswith((".bak.parquet", ".tmp.parquet", ".migration.tmp.parquet"))


def _save_repaired_partition(df: pl.DataFrame, dataset: str, target_path: Path) -> pl.DataFrame:
    """标准后处理、去重、排序并原子写入 Curated 分区。"""
    final_df = StorageCompat.post_process_dataset(
        dataset, StorageCompat.normalize_identity_columns(df)
    )
    final_df = StorageCompat.normalize_datetime_columns(final_df)
    dedup_cols = StorageCompat.resolve_dedup_keys(dataset, "tushare", "tushare", final_df)
    if dedup_cols:
        final_df = final_df.unique(subset=dedup_cols, keep="last")
    sort_cols = [c for c in ["trade_date", "symbol"] if c in final_df.columns]
    if sort_cols:
        final_df = final_df.sort(sort_cols)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_suffix(".tmp.parquet")
    final_df.write_parquet(tmp_path)
    tmp_path.replace(target_path)
    return final_df


def repair_report_rc(
    raw_root: Path = Path("data/raw/tushare/market=CN/report_rc"),
    curated_root: Path = Path("data/curated/tushare/market=CN/report_rc"),
) -> dict[str, int]:
    """重放 report_rc 数据至 Curated 黄金表。"""
    logger.info("=== [1/4] 开始修复 tushare/report_rc 研报数据 ===")
    if not raw_root.exists():
        return {"raw_total": 0, "curated_total": 0}

    raw_files = sorted([f for f in raw_root.rglob("*.parquet") if not _is_artifact(f)])
    cleaner = GenericCleaner(primary_keys=["ts_code", "report_date", "org_name", "quarter"])
    normalizer = GenericNormalizer()
    unit_norm = UnitNormalizer("tushare", "report_rc")

    total_raw = 0
    total_curated = 0

    for rf in raw_files:
        df = pl.read_parquet(rf)
        if df.is_empty():
            continue
        total_raw += len(df)
        df = StorageCompat.normalize_identity_columns(df)
        norm_df = normalizer.normalize(cleaner.clean(unit_norm.normalize_units(df)))

        now_utc = datetime.now(UTC)
        meta_cols = [
            pl.lit("tushare").alias("data_source"),
            pl.lit("report_rc").alias("source_endpoint"),
            pl.lit("repair_run").alias("request_id"),
            pl.lit(now_utc).cast(pl.Datetime("us", "UTC")).alias("updated_at"),
            pl.lit("CN").alias("market"),
            pl.lit("SOURCE").alias("exchange"),
            pl.lit("CNY").alias("currency"),
            pl.lit("raw").alias("adjustment"),
            pl.lit("v2").alias("schema_version"),
        ]
        target_path = curated_root / rf.parent.parent.name / rf.parent.name / "data.parquet"
        saved = _save_repaired_partition(norm_df.with_columns(meta_cols), "report_rc", target_path)
        total_curated += len(saved)

    logger.info(f"report_rc 修复完成: RAW {total_raw:,} -> Curated {total_curated:,}")
    return {"raw_total": total_raw, "curated_total": total_curated}


def repair_etf_share_size(
    raw_root: Path = Path("data/raw/tushare/market=CN/etf_share_size"),
    curated_root: Path = Path("data/curated/tushare/market=CN/etf_share_size"),
) -> dict[str, int]:
    """重放 etf_share_size 历史断档与分区数据。"""
    logger.info("=== [2/4] 开始修复 tushare/etf_share_size 基金份额 ===")
    if not raw_root.exists():
        return {"raw_total": 0, "curated_total": 0}

    raw_files = sorted([f for f in raw_root.rglob("*.parquet") if not _is_artifact(f)])
    cleaner = GenericCleaner(primary_keys=["ts_code", "trade_date"])
    normalizer = GenericNormalizer()
    unit_norm = UnitNormalizer("tushare", "etf_share_size")

    total_raw = 0
    total_curated = 0

    for rf in raw_files:
        df = pl.read_parquet(rf)
        if df.is_empty():
            continue
        total_raw += len(df)
        df = StorageCompat.normalize_identity_columns(df)
        norm_df = normalizer.normalize(cleaner.clean(unit_norm.normalize_units(df)))

        m_exp, ex_exp, cur_exp = (
            infer_market_exchange_currency(pl.col("symbol"), data_source="tushare")
            if "symbol" in norm_df.columns
            else (pl.lit("CN"), pl.lit("SOURCE"), pl.lit("CNY"))
        )
        now_utc = datetime.now(UTC)
        meta_cols = [
            pl.lit("tushare").alias("data_source"),
            pl.lit("etf_share_size").alias("source_endpoint"),
            pl.lit("repair_run").alias("request_id"),
            pl.lit(now_utc).cast(pl.Datetime("us", "UTC")).alias("updated_at"),
            m_exp.alias("market"),
            ex_exp.alias("exchange"),
            cur_exp.alias("currency"),
            pl.lit("raw").alias("adjustment"),
            pl.lit("v2").alias("schema_version"),
        ]
        target_path = curated_root / rf.parent.parent.name / rf.parent.name / "data.parquet"
        saved = _save_repaired_partition(
            norm_df.with_columns(meta_cols), "etf_share_size", target_path
        )
        total_curated += len(saved)

    logger.info(f"etf_share_size 修复完成: RAW {total_raw:,} -> Curated {total_curated:,}")
    return {"raw_total": total_raw, "curated_total": total_curated}


def repair_stock_daily_bar(
    raw_root: Path = Path("data/raw/tushare/market=CN/stock_daily_bar"),
    curated_root: Path = Path("data/curated/tushare/market=CN/stock_daily_bar"),
) -> dict[str, int]:
    """利用优化后的 BarDataCleaner 容错规则重新重放日线数据。"""
    logger.info("=== [3/4] 开始修复 tushare/stock_daily_bar 边界缺失记录 ===")
    if not raw_root.exists():
        return {"repaired_files": 0, "total_rows": 0}

    raw_files = sorted([f for f in raw_root.rglob("*.parquet") if not _is_artifact(f)])
    cleaner = BarDataCleaner()
    normalizer = BarDataNormalizer()
    unit_norm = UnitNormalizer("tushare", "stock_daily_bar")

    repaired_files = 0
    total_repaired_rows = 0

    for rf in raw_files:
        df = pl.read_parquet(rf)
        if df.is_empty():
            continue
        sym_col = "symbol" if "symbol" in df.columns else "ts_code"
        has_anomalies = (
            df.filter(
                (pl.col(sym_col).is_in(["302132.SZ", "920768.BJ"]))
                | (
                    pl.col("open").is_not_null()
                    & (pl.col("open") > 0)
                    & (pl.col("high").is_null() | pl.col("low").is_null())
                )
            ).shape[0]
            > 0
        )
        if not has_anomalies:
            continue

        df = StorageCompat.normalize_identity_columns(df)
        norm_df = normalizer.normalize(cleaner.clean(unit_norm.normalize_units(df)))
        m_exp, ex_exp, cur_exp = infer_market_exchange_currency(
            pl.col("symbol"), data_source="tushare"
        )
        now_utc = datetime.now(UTC)
        meta_cols = [
            pl.lit("tushare").alias("data_source"),
            pl.lit("stock_daily_bar").alias("source_endpoint"),
            pl.lit("repair_run").alias("request_id"),
            pl.lit(now_utc).cast(pl.Datetime("us", "UTC")).alias("updated_at"),
            m_exp.alias("market"),
            ex_exp.alias("exchange"),
            cur_exp.alias("currency"),
            pl.lit("raw").alias("adjustment"),
            pl.lit("v2").alias("schema_version"),
        ]
        target_path = curated_root / rf.parent.parent.name / rf.parent.name / "data.parquet"
        saved = _save_repaired_partition(
            norm_df.with_columns(meta_cols), "stock_daily_bar", target_path
        )
        repaired_files += 1
        total_repaired_rows += len(saved)

    logger.info(
        f"stock_daily_bar 修复完成: 重写 {repaired_files} 分区, 共 {total_repaired_rows:,} 条"
    )
    return {"repaired_files": repaired_files, "total_rows": total_repaired_rows}


def repair_margin_raw_lineage(
    raw_margin_path: Path = Path("data/raw/tushare/market=CN/margin/data.parquet"),
) -> None:
    """清理 RAW 层 margin 表中混入的 Curated 血统字段。"""
    logger.info("=== [4/4] 开始治理 tushare/margin RAW 层血统列 ===")
    if not raw_margin_path.exists():
        return

    df = pl.read_parquet(raw_margin_path)
    lineage_cols = {
        "data_source",
        "updated_at",
        "market",
        "exchange",
        "currency",
        "adjustment",
        "schema_version",
        "source_endpoint",
        "request_id",
    }
    present_lineage = [c for c in df.columns if c in lineage_cols]
    if present_lineage:
        clean_cols = [c for c in df.columns if c not in lineage_cols]
        df.select(clean_cols).write_parquet(raw_margin_path)
        logger.info(f"margin RAW 已剔除血统列: {present_lineage}")


def main() -> None:
    logger.info("================ 开始执行全套系数据完整性修复 ================")
    repair_report_rc()
    repair_etf_share_size()
    repair_stock_daily_bar()
    repair_margin_raw_lineage()
    logger.info("================ 数据完整性修复全部执行完毕 ================")


if __name__ == "__main__":
    main()
