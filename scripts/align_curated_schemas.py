"""全库 Curated 存量 Parquet Schema 规范化与字段对齐迁移脚本。

跳过正在运行的 adj_factor 目录。
对 etf_share_size, daily_basic, fund_daily, fund_adj, yfinance/* 数据集做对齐与清理。
"""

from pathlib import Path

import polars as pl

CURATED_ROOT = Path("data/curated")


def migrate_etf_share_size() -> int:
    """清理 etf_share_size 中的历史废弃列 (close, nav, fund_type, float_share, float_size)。"""
    drop_cols = ["close", "nav", "fund_type", "float_share", "float_size"]
    files = list(CURATED_ROOT.glob("tushare/**/etf_share_size/**/*.parquet"))
    modified = 0
    for f in files:
        if f.name.endswith((".bak.parquet", ".tmp.parquet")):
            continue
        df = pl.read_parquet(f)
        to_drop = [c for c in drop_cols if c in df.columns]
        if to_drop:
            cleaned = df.drop(to_drop)
            cleaned.write_parquet(f, compression="zstd")
            modified += 1
    return modified


def migrate_metadata_lineage(dataset_name: str, target_meta_cols: list[str]) -> int:
    """统一补齐数据血统列 (fetched_at, source_id, source_unit_note)，消除新旧批次列数差异。"""
    files = list(CURATED_ROOT.glob(f"tushare/**/{dataset_name}/**/*.parquet"))
    modified = 0
    for f in files:
        if f.name.endswith((".bak.parquet", ".tmp.parquet")):
            continue
        df = pl.read_parquet(f)
        needs_write = False
        for col in target_meta_cols:
            if col not in df.columns:
                df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias(col))
                needs_write = True
        if needs_write:
            df.write_parquet(f, compression="zstd")
            modified += 1
    return modified


def migrate_yfinance_macro_indicators() -> int:
    """归一化 yfinance 宏观资产大写字段与多余字段。"""
    files = list(CURATED_ROOT.glob("yfinance/**/macro_indicators/data.parquet"))
    modified = 0
    drop_cols = [
        "Close",
        "Date",
        "High",
        "Low",
        "Open",
        "Volume",
        "Dividends",
        "Stock Splits",
        "dividends",
        "splits",
    ]
    for f in files:
        if f.name.endswith((".bak.parquet", ".tmp.parquet")):
            continue
        df = pl.read_parquet(f)
        to_drop = [c for c in drop_cols if c in df.columns]
        if to_drop:
            df = df.drop(to_drop)
            df.write_parquet(f, compression="zstd")
            modified += 1
    return modified


def migrate_yfinance_index_valuation() -> int:
    """归一化 yfinance 指数估值所有分区的列集合。"""
    files = list(CURATED_ROOT.glob("yfinance/**/index_valuation/data.parquet"))
    modified = 0
    all_cols = [
        "symbol",
        "trade_date",
        "dividend_yield",
        "forward_pe",
        "trailing_pe",
        "price_to_book",
        "price_to_sales",
        "market_cap",
        "target_index",
        "market",
        "exchange",
        "currency",
        "data_source",
        "updated_at",
        "adjustment",
        "schema_version",
        "source_endpoint",
        "request_id",
    ]
    for f in files:
        if f.name.endswith((".bak.parquet", ".tmp.parquet")):
            continue
        df = pl.read_parquet(f)
        needs_write = False
        for c in all_cols:
            if c not in df.columns:
                dtype = pl.Utf8 if c in ("target_index",) else pl.Float64
                df = df.with_columns(pl.lit(None).cast(dtype).alias(c))
                needs_write = True
        if "total_assets" in df.columns:
            df = df.with_columns(
                pl.coalesce(
                    [
                        pl.col("market_cap").cast(pl.Float64, strict=False),
                        pl.col("total_assets").cast(pl.Float64, strict=False),
                    ]
                ).alias("market_cap")
            ).drop("total_assets")
            needs_write = True
        extra_cols = [c for c in df.columns if c not in all_cols]
        if extra_cols:
            df = df.drop(extra_cols)
            needs_write = True
        if needs_write:
            df = df.select([c for c in all_cols if c in df.columns])
            df.write_parquet(f, compression="zstd")
            modified += 1
    return modified


def main() -> None:
    print("=== 开始全库 Curated 存量 Schema 对齐与冗余清理 (跳过 adj_factor) ===")
    c1 = migrate_etf_share_size()
    print(f"1. [tushare/etf_share_size] 剔除 5 个历史冗余列: 成功处理 {c1} 个分区文件")
    c2 = migrate_metadata_lineage("daily_basic", ["fetched_at", "source_id", "source_unit_note"])
    print(f"2. [tushare/daily_basic] 补齐统一血统元数据: 成功处理 {c2} 个分区文件")
    c3 = migrate_metadata_lineage("fund_daily", ["fetched_at", "source_id", "source_unit_note"])
    print(f"3. [tushare/fund_daily] 补齐统一血统元数据: 成功处理 {c3} 个分区文件")
    c4 = migrate_metadata_lineage("fund_adj", ["fetched_at", "source_id"])
    print(f"4. [tushare/fund_adj] 补齐统一血统元数据: 成功处理 {c4} 个分区文件")
    c5 = migrate_yfinance_macro_indicators()
    print(f"5. [yfinance/macro_indicators] 归一化大写字段: 成功处理 {c5} 个文件")
    c6 = migrate_yfinance_index_valuation()
    print(f"6. [yfinance/index_valuation] 归一化别名列: 成功处理 {c6} 个文件")
    print("\n=== Curated 存量 Schema 对齐完成！===")


if __name__ == "__main__":
    main()
