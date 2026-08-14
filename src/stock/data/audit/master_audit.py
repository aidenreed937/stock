"""全库全量离线 Parquet 数据落盘物理主审计工具。"""

import logging
from pathlib import Path
from typing import Any

import polars as pl

# 记录数允许较少的特定宏观与结构数据集
LOW_VOLUME_DATASETS = {
    "cn_cpi",
    "cn_gdp",
    "cn_m",
    "cn_pmi",
    "cn_ppi",
    "sf_month",
    "index_classify",
    "index_member",
}

logger = logging.getLogger(__name__)


def _parse_source_dataset(file_path: Path, base_dir: Path) -> tuple[str, str]:
    """从物理路径解析数据源和数据集名。"""
    rel_parts = file_path.relative_to(base_dir).parts
    source = rel_parts[0] if len(rel_parts) > 0 else "unknown"
    if len(rel_parts) >= 3 and rel_parts[1].startswith("market="):
        dataset = rel_parts[2]
    elif len(rel_parts) >= 2:
        dataset = rel_parts[1]
    else:
        dataset = file_path.stem
    return source, dataset


def _format_year_gaps(years: list[Any]) -> str | None:
    """分析年份列表是否存在连续跨年断档。"""
    valid_years = {int(y) for y in years if y is not None and str(y).isdigit()}
    if len(valid_years) < 2:
        return None
    min_yr = min(valid_years)
    max_yr = max(valid_years)
    if max_yr - min_yr < 2:
        return None
    missing = sorted(list(set(range(min_yr, max_yr + 1)) - valid_years))
    if not missing:
        return None
    if len(missing) == 1:
        return f"警告: 年份断档 (缺失 {missing[0]} 年)"
    return f"警告: 年份断档 (缺失 {missing[0]}..{missing[-1]} 年)"


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
        f
        for f in curated_path.rglob("*.parquet")
        if not f.name.endswith((".bak.parquet", ".tmp.parquet"))
    ]
    if not files:
        logger.info(f"目录 [{base_dir}] 下未扫描到任何有效 Parquet 数据文件。")
        return pl.DataFrame()

    records: list[dict[str, Any]] = []
    for f in files:
        src, dataset = _parse_source_dataset(f, curated_path)
        year_val: int | None = None
        for part in f.parts:
            if part.startswith("year="):
                try:
                    year_val = int(part.removeprefix("year="))
                except ValueError:
                    pass
        try:
            # 采用 Lazy API (scan_parquet) 极大地降低内存并只计算需要的列
            df_lazy = pl.scan_parquet(f)
            columns = df_lazy.collect_schema().names()

            sym_col = next((c for c in ["ts_code", "symbol", "stockCode", "ticker"] if c in columns), None)
            date_col = next(
                (
                    c
                    for c in [
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
                    if c in columns
                ),
                None,
            )

            exprs = [pl.len().alias("rows")]
            if sym_col:
                exprs.append(pl.col(sym_col).drop_nulls().n_unique().alias("symbols_count"))
            else:
                exprs.append(pl.lit(0).alias("symbols_count"))

            if date_col:
                exprs.append(pl.col(date_col).drop_nulls().cast(pl.Utf8, strict=False).min().alias("min_date"))
                exprs.append(pl.col(date_col).drop_nulls().cast(pl.Utf8, strict=False).max().alias("max_date"))
            else:
                exprs.append(pl.lit(None).alias("min_date"))
                exprs.append(pl.lit(None).alias("max_date"))

            # 触发单次图计算
            res = df_lazy.select(exprs).collect()

            min_val = res["min_date"].item() if "min_date" in res.columns else None
            max_val = res["max_date"].item() if "max_date" in res.columns else None

            # 从 min_date/max_date 兜底推断 year
            if year_val is None and min_val:
                try:
                    year_val = int(str(min_val)[:4])
                except Exception:
                    pass

            records.append(
                {
                    "source": src,
                    "dataset": dataset,
                    "path": str(f),
                    "year": year_val,
                    "rows": res["rows"].item(),
                    "symbols_count": res["symbols_count"].item(),
                    "min_date": str(min_val)[:10] if min_val is not None else "N/A",
                    "max_date": str(max_val)[:10] if max_val is not None else "N/A",
                    "audit_errors": 0,
                }
            )
        except Exception as e:
            logger.error(f"读取文件 [{f}] 发生审计解析异常: {e}")
            records.append(
                {
                    "source": src,
                    "dataset": dataset,
                    "path": str(f),
                    "year": year_val,
                    "rows": 0,
                    "symbols_count": 0,
                    "min_date": "N/A",
                    "max_date": "N/A",
                    "audit_errors": 1,
                }
            )

    if not records:
        return pl.DataFrame()

    df_rec = pl.DataFrame(records)
    grouped = (
        df_rec.group_by(["source", "dataset"])
        .agg(
            pl.len().alias("分区数"),
            pl.col("symbols_count").max().alias("标的数"),
            pl.col("rows").sum().alias("精炼落盘总记录数"),
            pl.col("min_date").filter(pl.col("min_date") != "N/A").min().alias("最早交易日"),
            pl.col("max_date").filter(pl.col("max_date") != "N/A").max().alias("最新交易日"),
            pl.col("year").drop_nulls().unique().alias("years"),
            pl.col("audit_errors").sum().alias("审计错误数"),
        )
        .with_columns(
            pl.col("最早交易日").fill_null("N/A"),
            pl.col("最新交易日").fill_null("N/A"),
        )
        .sort(["source", "dataset"])
    )

    year_warnings = [
        _format_year_gaps(row.get("years", []))
        for row in grouped.select(["years"]).iter_rows(named=True)
    ]
    return grouped.with_columns(pl.Series("year_gap_warning", year_warnings)).drop("years")


def print_master_audit_summary(summary: pl.DataFrame) -> None:
    """格式化打印全库离线落盘主审计表。"""
    print("=" * 115)
    print("                        【全库全量数据离线存储主审计报告 (Master Data Audit Report)】")
    print("=" * 115)

    if not summary.is_empty():
        # 利用 Polars 原生打印，自动处理中文字符对齐问题
        warning_col = (
            pl.col("year_gap_warning") if "year_gap_warning" in summary.columns else pl.lit(None)
        )
        final_summary = summary.with_columns(
            pl.when(pl.col("审计错误数") > 0)
            .then(pl.lit("存在文件读取错误"))
            .when(pl.col("精炼落盘总记录数") == 0)
            .then(pl.lit("空数据集 (0行)"))
            .when(warning_col.is_not_null())
            .then(warning_col)
            .when(
                pl.col("dataset").is_in(list(LOW_VOLUME_DATASETS))
                & (pl.col("精炼落盘总记录数") <= 1)
            )
            .then(pl.lit("警告: 记录数严重偏少(<=1行)"))
            .otherwise(pl.lit("已扫描，物理文件完整"))
            .alias("完备度诊断")
        )
        if "year_gap_warning" in final_summary.columns:
            final_summary = final_summary.drop("year_gap_warning")

        with pl.Config(
            tbl_rows=1000,
            tbl_width_chars=160,
            tbl_hide_column_data_types=True,
            tbl_hide_dataframe_shape=True,
        ):
            print(final_summary)
    else:
        print("离线库为空或未包含任何有效 Parquet 数据文件。")

    print("=" * 115)


def main() -> None:
    """主审计 CLI 入口。"""
    summary = run_master_audit("data/curated")
    print_master_audit_summary(summary)


if __name__ == "__main__":
    main()
