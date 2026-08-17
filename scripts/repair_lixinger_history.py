"""治理理杏仁历史 Curated 记录与 RAW 血缘差异。"""

from pathlib import Path

import polars as pl

from stock.data.quality.quarantine import QuarantineStore


def repair_pre_listing_stock_bars(
    curated_path: Path = Path("data/curated/lixinger/market=CN/stock_daily_bar/data.parquet"),
    raw_path: Path = Path("data/raw/lixinger/market=CN/stock_daily_bar/data.parquet"),
) -> dict[str, object]:
    """隔离 RAW 不存在且早于观察池上市日的旧 Curated 行。"""
    curated = pl.read_parquet(curated_path)
    raw = pl.read_parquet(raw_path)
    raw_keys = raw.select(
        pl.col("stockCode").cast(pl.Utf8).alias("symbol"),
        pl.col("date").cast(pl.Utf8).str.slice(0, 10).alias("trade_date"),
    )
    candidate = curated.filter(
        (pl.col("symbol") == "000001") & (pl.col("trade_date") < pl.date(1991, 4, 3))
    )
    candidate_keys = candidate.select(
        "symbol", pl.col("trade_date").cast(pl.Utf8).alias("trade_date")
    )
    orphan = candidate_keys.join(raw_keys, on=["symbol", "trade_date"], how="anti")
    if len(orphan) != len(candidate):
        raise RuntimeError("待隔离的历史记录无法与候选 Curated 行一一对应")

    backup_path = curated_path.with_name("data.legacy.bak.parquet")
    if not backup_path.exists():
        curated.write_parquet(backup_path)
    QuarantineStore().write_file(
        candidate,
        endpoint="stock_daily_bar",
        reason="curated_orphan_pre_listing_no_raw_lineage",
        request_id="history_repair_20260816",
        data_source="lixinger",
    )
    orphan_dates = orphan.get_column("trade_date").to_list()
    repaired = curated.filter(
        ~((pl.col("symbol") == "000001") & pl.col("trade_date").cast(pl.Utf8).is_in(orphan_dates))
    )
    repaired.write_parquet(curated_path)
    return {
        "removed_rows": len(candidate),
        "backup": str(backup_path),
        "quarantine": "data/quarantine/endpoint=stock_daily_bar/history_repair.parquet",
        "curated_rows": len(repaired),
    }


if __name__ == "__main__":
    print(repair_pre_listing_stock_bars())
