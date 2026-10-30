"""基础化工现货出厂基准价 RAW/Curated 转换。"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.chemicals.models import ChemicalSpotPriceRecord
from stock_data.fetcher.industry.chemicals.quality import validate_spot_price_records
from stock_data.fetcher.industry.chemicals.schemas import (
    CHEMICAL_SPOT_PRICE_RAW_SCHEMA,
    CHEMICAL_SPOT_PRICE_SCHEMA,
)

logger = logging.getLogger(__name__)


def build_spot_price_raw_frame(df: pl.DataFrame) -> pl.DataFrame:
    """将采集结果转换为源值文本优先的 RAW 表。"""
    if df.is_empty():
        return pl.DataFrame(schema=CHEMICAL_SPOT_PRICE_RAW_SCHEMA)
    for column in ("raw_content_sha256", "raw_snapshot_path"):
        if column not in df.columns:
            df = df.with_columns(pl.lit("").alias(column))
    exprs = []
    for col, dtype in CHEMICAL_SPOT_PRICE_RAW_SCHEMA.items():
        if col in df.columns:
            exprs.append(pl.col(col).cast(dtype))
        elif col.endswith("_raw"):
            base_col = col[:-4]
            if base_col in df.columns:
                exprs.append(pl.col(base_col).cast(pl.String).alias(col))
            else:
                exprs.append(pl.lit(None, dtype=dtype).alias(col))
        else:
            exprs.append(pl.lit(None, dtype=dtype).alias(col))
    return (
        df.select(exprs)
        .unique(subset=["symbol", "trade_date"], keep="last")
        .sort(["symbol", "trade_date"])
    )


def build_spot_price_curated_frame(df: pl.DataFrame) -> pl.DataFrame:
    """从 RAW 源值文本恢复标准化现货价格事实表。"""
    if df.is_empty():
        return pl.DataFrame(schema=CHEMICAL_SPOT_PRICE_SCHEMA)
    exprs = []
    for col, dtype in CHEMICAL_SPOT_PRICE_SCHEMA.items():
        if col in df.columns:
            exprs.append(pl.col(col).cast(dtype, strict=False))
        else:
            raw_col = f"{col}_raw"
            if raw_col in df.columns:
                exprs.append(pl.col(raw_col).cast(dtype, strict=False).alias(col))
            else:
                exprs.append(pl.lit(None, dtype=dtype).alias(col))
    return (
        df.select(exprs)
        .unique(subset=["symbol", "trade_date"], keep="last")
        .sort(["symbol", "trade_date"])
    )


def records_to_spot_price_curated_frame(
    records: list[ChemicalSpotPriceRecord],
) -> pl.DataFrame:
    """将采集记录转换为 Curated 黄金事实帧（供 registry/replay 统一转换）。"""
    if not records:
        return pl.DataFrame(schema=CHEMICAL_SPOT_PRICE_SCHEMA)
    return build_spot_price_curated_frame(pl.DataFrame([asdict(r) for r in records]))


def records_to_spot_price_raw_frame(
    records: list[ChemicalSpotPriceRecord],
) -> pl.DataFrame:
    """将采集记录转换为 RAW 事实帧（含源值文本与血统字段）。"""
    if not records:
        return pl.DataFrame(schema=CHEMICAL_SPOT_PRICE_RAW_SCHEMA)
    return build_spot_price_raw_frame(pl.DataFrame([asdict(r) for r in records]))


def materialize_spot_price_curated(
    records_dict: dict[str, list[ChemicalSpotPriceRecord]],
    curated_dir: Path | str,
) -> pl.DataFrame:
    """质检过滤后合并写入 Curated chemical_spot_price.parquet。"""
    all_records: list[ChemicalSpotPriceRecord] = []
    for recs in records_dict.values():
        valid_recs, validation_errors = validate_spot_price_records(recs)
        if validation_errors:
            logger.warning(
                "100ppi 现货质检拒绝 %d/%d 条记录: %s",
                len(recs) - len(valid_recs),
                len(recs),
                "; ".join(validation_errors),
            )
        all_records.extend(valid_recs)

    if not all_records:
        return pl.DataFrame()

    rows = [asdict(r) for r in all_records]
    raw_df = pl.DataFrame(rows)
    curated_frame = build_spot_price_curated_frame(raw_df)

    curated_file = Path(curated_dir) / "chemical_spot_price.parquet"
    curated_file.parent.mkdir(parents=True, exist_ok=True)
    if curated_file.exists():
        existing = build_spot_price_curated_frame(pl.read_parquet(curated_file))
        merged = (
            pl.concat([existing, curated_frame])
            .unique(subset=["symbol", "trade_date"], keep="last")
            .sort(["symbol", "trade_date"])
        )
    else:
        merged = curated_frame

    merged.write_parquet(curated_file)
    return merged


__all__ = [
    "build_spot_price_curated_frame",
    "build_spot_price_raw_frame",
    "materialize_spot_price_curated",
    "records_to_spot_price_curated_frame",
    "records_to_spot_price_raw_frame",
]
