"""全库全量离线 Parquet 数据落盘物理主审计工具。"""

import logging
from pathlib import Path
from typing import Any

import polars as pl

logger = logging.getLogger(__name__)


def run_master_audit(base_dir: str = "data/curated") -> pl.DataFrame:
    """物理扫描指定目录下的全部 Parquet 文件，按数据源与数据集汇总审计信息。

    Args:
        base_dir: 离线 Parquet 存储基准根目录

    Returns:
        pl.DataFrame: 汇总审计对账结果表
    """
    curated_path = Path(base_dir)
    if not curated_path.exists():
        logger.warning(f"审计目标目录不存在: {base_dir}")
        return pl.DataFrame()

    files = list(curated_path.rglob("*.parquet"))
    if not files:
        logger.info(f"目录 [{base_dir}] 下未扫描到任何 Parquet 数据文件。")
        return pl.DataFrame()

    records: list[dict[str, Any]] = []
    for f in files:
        try:
            df = pl.read_parquet(f)
            rel_parts = f.relative_to(curated_path).parts
            src = rel_parts[0] if len(rel_parts) > 0 else "unknown"
            dataset = rel_parts[2] if len(rel_parts) > 2 else f.stem

            symbols_cnt = 0
            if "symbol" in df.columns:
                symbols_cnt = df["symbol"].n_unique()
            elif "ts_code" in df.columns:
                symbols_cnt = df["ts_code"].n_unique()

            min_d = "N/A"
            max_d = "N/A"
            date_col = None
            for col in ["trade_date", "as_of_date", "list_date", "Date"]:
                if col in df.columns:
                    date_col = col
                    break

            if date_col:
                min_d = str(df[date_col].min())[:10]
                max_d = str(df[date_col].max())[:10]

            records.append({
                "source": src,
                "dataset": dataset,
                "path": str(f),
                "rows": len(df),
                "symbols_count": symbols_cnt,
                "min_date": min_d,
                "max_date": max_d,
                "null_count": sum(df[c].null_count() for c in df.columns),
                "duplicate_rows": len(df) - len(df.unique()),
            })
        except Exception as e:
            logger.error(f"读取文件 [{f}] 发生审计解析异常: {e}")

    if not records:
        return pl.DataFrame()

    df_rec = pl.DataFrame(records)
    summary = df_rec.group_by(["source", "dataset"]).agg(
        pl.col("symbols_count").max().alias("标的数"),
        pl.col("rows").sum().alias("精炼落盘总记录数"),
        pl.col("min_date").min().alias("最早交易日"),
        pl.col("max_date").max().alias("最新交易日"),
    ).sort(["source", "dataset"])

    return summary


def main() -> None:
    """主审计 CLI 入口，打印全库离线落盘主审计表。"""
    print("=" * 105)
    print("                      【全库全量数据离线存储主审计报告 (Master Data Audit Report)】")
    print("=" * 105)

    summary = run_master_audit("data/curated")
    if not summary.is_empty():
        print(f"{'数据源':<10} | {'数据集表名':<22} | {'覆盖标的数':<10} | {'落盘总记录数':<12} | {'最早交易日':<10} | {'最新交易日':<10} | {'完备度诊断'}")
        print("-" * 105)
        for row in summary.iter_rows(named=True):
            src = row["source"]
            ds = row["dataset"]
            syms = row["标的数"]
            rows = row["精炼落盘总记录数"]
            min_d = row["最早交易日"]
            max_d = row["最新交易日"]
            print(f"{src:<10} | {ds:<22} | {syms:<10} | {rows:<12} | {min_d:<10} | {max_d:<10} | 已扫描，完整性需按接口契约判定")
    else:
        print("离线库为空或未包含任何有效 Parquet 数据文件。")

    print("=" * 105)


if __name__ == "__main__":
    main()
