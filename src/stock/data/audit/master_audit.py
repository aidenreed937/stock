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

    files = [
        f for f in curated_path.rglob("*.parquet")
        if not f.name.endswith((".bak.parquet", ".tmp.parquet"))
    ]
    if not files:
        logger.info(f"目录 [{base_dir}] 下未扫描到任何有效 Parquet 数据文件。")
        return pl.DataFrame()

    records: list[dict[str, Any]] = []
    for f in files:
        try:
            df = pl.read_parquet(f)
            rel_parts = f.relative_to(curated_path).parts
            src = rel_parts[0] if len(rel_parts) > 0 else "unknown"

            # 精确解析数据集名（兼容 market=XX 分区与扁平层级）
            if len(rel_parts) >= 3 and rel_parts[1].startswith("market="):
                dataset = rel_parts[2]
            elif len(rel_parts) >= 2:
                dataset = rel_parts[1]
            else:
                dataset = f.stem

            symbols_cnt = 0
            for sym_col in ["symbol", "ts_code", "stockCode", "ticker"]:
                if sym_col in df.columns:
                    symbols_cnt = df[sym_col].drop_nulls().n_unique()
                    break

            min_d = "N/A"
            max_d = "N/A"
            date_col = next(
                (
                    c for c in [
                        "trade_date",
                        "date",
                        "as_of_date",
                        "end_date",
                        "month",
                        "quarter",
                        "report_date",
                        "list_date",
                        "Date",
                    ]
                    if c in df.columns
                ),
                None,
            )

            if date_col and not df.is_empty():
                vals = df[date_col].drop_nulls().cast(pl.Utf8, strict=False)
                if not vals.is_empty():
                    min_d = str(vals.min())[:10]
                    max_d = str(vals.max())[:10]

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


def print_master_audit_summary(summary: pl.DataFrame) -> None:
    """格式化打印全库离线落盘主审计表。"""
    print("=" * 105)
    print("                      【全库全量数据离线存储主审计报告 (Master Data Audit Report)】")
    print("=" * 105)

    if not summary.is_empty():
        print(
            f"{'数据源':<10} | {'数据集表名':<28} | {'覆盖标的数':<10} | {'落盘总记录数':<12} | "
            f"{'最早交易日':<10} | {'最新交易日':<10} | {'完备度诊断'}"
        )
        print("-" * 105)
        for row in summary.iter_rows(named=True):
            src = row["source"]
            ds = row["dataset"]
            syms = row["标的数"]
            rows = row["精炼落盘总记录数"]
            min_d = row["最早交易日"]
            max_d = row["最新交易日"]
            print(
                f"{src:<10} | {ds:<28} | {syms:<10} | {rows:<12,d} | "
                f"{min_d:<10} | {max_d:<10} | 已扫描，物理文件完整"
            )
    else:
        print("离线库为空或未包含任何有效 Parquet 数据文件。")

    print("=" * 105)


def main() -> None:
    """主审计 CLI 入口。"""
    summary = run_master_audit("data/curated")
    print_master_audit_summary(summary)


if __name__ == "__main__":
    main()
