"""生意社商品定基指数记录转换与 Curated 黄金事实表物化。

负责将 CommodityIndexRow 记录幂等合并写入：
data/curated/industry/chemical_commodity_index.parquet
以 (trade_date, ppid) 为复合主键，去重更新并累积连续日频时间序列。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.chemicals.parsers.commodity_index import CommodityIndexRow

logger = logging.getLogger(__name__)

COMMODITY_INDEX_SCHEMA = {
    "trade_date": pl.Date,
    "ppid": pl.Int64,
    "symbol": pl.Utf8,
    "product_name": pl.Utf8,
    "ci_value": pl.Float64,
    "pct_change_1d": pl.Float64,
    "direction": pl.Utf8,
    "cumulative_points": pl.Float64,
    "cumulative_change_pct": pl.Float64,
    "source": pl.Utf8,
    "source_url": pl.Utf8,
    "collected_at": pl.Utf8,
}


def records_to_commodity_index_curated_frame(
    records: Sequence[CommodityIndexRow],
) -> pl.DataFrame:
    """将 CommodityIndexRow 序列转换为标准 Curated DataFrame。"""
    if not records:
        return pl.DataFrame(schema=COMMODITY_INDEX_SCHEMA)

    now_iso = datetime.now(UTC).isoformat()
    rows = []
    for r in records:
        rows.append(
            {
                "trade_date": r.trade_date,
                "ppid": int(r.ppid),
                "symbol": str(r.symbol),
                "product_name": str(r.product_name),
                "ci_value": float(r.ci_value),
                "pct_change_1d": float(r.pct_change_1d) if r.pct_change_1d is not None else None,
                "direction": str(r.direction),
                "cumulative_points": (
                    float(r.cumulative_points) if r.cumulative_points is not None else None
                ),
                "cumulative_change_pct": (
                    float(r.cumulative_change_pct) if r.cumulative_change_pct is not None else None
                ),
                "source": r.source,
                "source_url": f"https://www.100ppi.com/cindex/ptrade-{r.ppid}.html",
                "collected_at": now_iso,
            }
        )
    return pl.DataFrame(rows, schema=COMMODITY_INDEX_SCHEMA)


def materialize_commodity_index_to_curated(
    records: Sequence[CommodityIndexRow],
    curated_dir: Path | str = "data/curated/industry",
) -> tuple[int, int]:
    """将商品定基指数记录物化并幂等合并写入 Curated 黄金事实表。

    Args:
        records: CommodityIndexRow 记录列表。
        curated_dir: Curated 目录路径。

    Returns:
        (新增或更新记录数, 库中总记录数)。
    """
    if not records:
        logger.info("未提供商品指数记录，跳过物化")
        return 0, 0

    c_dir = Path(curated_dir)
    c_dir.mkdir(parents=True, exist_ok=True)
    curated_file = c_dir / "chemical_commodity_index.parquet"

    new_df = records_to_commodity_index_curated_frame(records)

    if curated_file.exists():
        try:
            existing_df = pl.read_parquet(curated_file)
            existing_count = len(existing_df)

            # 按复合主键 (trade_date, ppid) 进行去重合并，新采集记录更新既有记录
            combined_df = pl.concat([existing_df, new_df], how="vertical_relaxed")
            final_df = combined_df.unique(subset=["trade_date", "ppid"], keep="last").sort(
                ["symbol", "trade_date"]
            )
            total_count = len(final_df)
            net_added = total_count - existing_count
            logger.info(
                f"Curated chemical_commodity_index.parquet 增量合并完成: "
                f"原有 {existing_count} 行, 净增 {net_added} 行, 当前共 {total_count} 行"
            )
        except Exception as e:
            logger.error(f"读取合并现有 {curated_file} 失败: {e}，将直接使用新数据重写")
            final_df = new_df.unique(subset=["trade_date", "ppid"], keep="last").sort(
                ["symbol", "trade_date"]
            )
            net_added = len(final_df)
            total_count = len(final_df)
    else:
        final_df = new_df.unique(subset=["trade_date", "ppid"], keep="last").sort(
            ["symbol", "trade_date"]
        )
        net_added = len(final_df)
        total_count = len(final_df)
        logger.info(f"新建 Curated chemical_commodity_index.parquet: 共 {total_count} 行")

    # 原子落盘
    tmp_path = curated_file.with_suffix(".tmp")
    final_df.write_parquet(tmp_path)
    tmp_path.replace(curated_file)

    return net_added, total_count
