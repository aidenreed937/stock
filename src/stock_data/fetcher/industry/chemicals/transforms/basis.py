"""生意社现期基差记录转换与 Curated 黄金事实表物化 (basis.py)。

负责将 ChemicalBasisRow 记录分别物化至：
1. 现货出厂价黄金表 (chemical_spot_price.parquet) - 增量补充历史深度；
2. 现期基差黄金表 (chemical_futures_basis.parquet) - 保存基差与主力合约结构。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.chemicals.parsers.basis_table import ChemicalBasisRow

logger = logging.getLogger(__name__)


def materialize_basis_records_to_curated(
    records: Sequence[ChemicalBasisRow],
    curated_dir: Path | str = "data/curated/industry",
    update_spot_price: bool = True,
) -> tuple[int, int]:
    """将采集的现期基差记录物化并幂等合并写入 Curated 事实表。

    Args:
        records: 解析得到的 ChemicalBasisRow 序列。
        curated_dir: Curated 根目录。
        update_spot_price: 是否将现货价格同步增量合并至 chemical_spot_price.parquet。

    Returns:
        (spot_price_added_or_updated_count, basis_table_total_count)
    """
    if not records:
        logger.info("未提供现期基差记录，跳过物化")
        return 0, 0

    c_dir = Path(curated_dir)
    c_dir.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now(UTC).isoformat()

    # 1. 构造基差事实表 DataFrame
    basis_rows = []
    spot_rows = []

    for r in records:
        basis_rows.append(
            {
                "trade_date": r.trade_date,
                "product_name": r.product_name,
                "symbol": r.symbol,
                "spot_price_cny": float(r.spot_price_cny),
                "near_contract": str(r.near_contract),
                "near_contract_price": float(r.near_contract_price)
                if r.near_contract_price is not None
                else None,
                "dom_contract": str(r.dom_contract),
                "dom_contract_price": float(r.dom_contract_price)
                if r.dom_contract_price is not None
                else None,
                "basis_cny": float(r.basis_cny) if r.basis_cny is not None else None,
                "basis_rate_pct": float(r.basis_rate_pct) if r.basis_rate_pct is not None else None,
                "unit": r.unit,
                "source": r.source,
                "source_url": f"https://www.100ppi.com/sf/day-{r.trade_date.isoformat()}.html",
                "release_date": r.trade_date,
                "collected_at": now_iso,
            }
        )

        if update_spot_price:
            spot_rows.append(
                {
                    "trade_date": r.trade_date,
                    "product_name": r.product_name,
                    "symbol": r.symbol,
                    "spot_price_cny": float(r.spot_price_cny),
                    "spec": "期货基准交割品/现货基准",
                    "region": "国内基准",
                    "unit": r.unit,
                    "source": r.source,
                    "source_url": f"https://www.100ppi.com/sf/day-{r.trade_date.isoformat()}.html",
                    "release_date": r.trade_date,
                    "data_status": "spot_benchmark",
                    "collected_at": now_iso,
                }
            )

    # 2. 物化 chemical_futures_basis.parquet
    basis_path = c_dir / "chemical_futures_basis.parquet"
    new_basis_df = pl.DataFrame(basis_rows).with_columns(
        [
            pl.col("trade_date").cast(pl.Date),
            pl.col("release_date").cast(pl.Date),
        ]
    )

    if basis_path.exists():
        try:
            old_basis_df = pl.read_parquet(basis_path)
            # 按 (symbol, trade_date) 唯一化，新数据优先覆盖旧数据
            combined_basis = (
                pl.concat([old_basis_df, new_basis_df], how="diagonal")
                .unique(subset=["symbol", "trade_date"], keep="last")
                .sort(["symbol", "trade_date"])
            )
        except Exception as e:
            logger.warning(f"读取旧基差表失败: {e}，将直接使用新采集数据")
            combined_basis = new_basis_df.sort(["symbol", "trade_date"])
    else:
        combined_basis = new_basis_df.sort(["symbol", "trade_date"])

    # 原子写入 Parquet 与 CSV
    tmp_basis_path = basis_path.with_suffix(".parquet.tmp")
    combined_basis.write_parquet(tmp_basis_path, compression="zstd")
    tmp_basis_path.replace(basis_path)
    combined_basis.write_csv(c_dir / "chemical_futures_basis.csv")
    total_basis_count = len(combined_basis)

    # 3. 增量更新 chemical_spot_price.parquet
    spot_updated_count = 0
    if update_spot_price and spot_rows:
        spot_path = c_dir / "chemical_spot_price.parquet"
        new_spot_df = pl.DataFrame(spot_rows).with_columns(
            [
                pl.col("trade_date").cast(pl.Date),
                pl.col("release_date").cast(pl.Date),
            ]
        )

        if spot_path.exists():
            try:
                old_spot_df = pl.read_parquet(spot_path)
                # 策略：优先保留 100ppi 官方 graph_ave 原有逐日高精度规格（若存在）；若不存在则填补 sf 历史数据
                combined_spot = (
                    pl.concat([new_spot_df, old_spot_df], how="diagonal")
                    .unique(subset=["symbol", "trade_date"], keep="last")
                    .sort(["symbol", "trade_date"])
                )
                spot_updated_count = len(combined_spot) - len(old_spot_df)
            except Exception as e:
                logger.warning(f"读取旧现货表失败: {e}")
                combined_spot = new_spot_df.sort(["symbol", "trade_date"])
                spot_updated_count = len(combined_spot)
        else:
            combined_spot = new_spot_df.sort(["symbol", "trade_date"])
            spot_updated_count = len(combined_spot)

        tmp_spot_path = spot_path.with_suffix(".parquet.tmp")
        combined_spot.write_parquet(tmp_spot_path, compression="zstd")
        tmp_spot_path.replace(spot_path)

    logger.info(
        f"物化完成: chemical_futures_basis={total_basis_count} 行, "
        f"chemical_spot_price 净增={spot_updated_count} 行"
    )
    return spot_updated_count, total_basis_count
