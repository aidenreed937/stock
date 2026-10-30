"""申万行业成分版本化 Curated 黄金表构建。"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from stock_data.catalog.compat import load_dataset_compat
from stock_data.core.derived_datasets import resolve_derived_dataset
from stock_data.pipeline.cleaner.date_utils import parse_mixed_date

if TYPE_CHECKING:
    from stock_core.contracts import MarketDataCatalog
    from stock_data.core.runtime import DataRuntimeContext
    from stock_data.storage.duckdb_store import DuckDBMarketStore

INDEX_MEMBER_VERSIONED_DATASET = "index_member_versioned"
INDEX_MEMBER_VERSIONED_SOURCE_ENDPOINT = "derived:index_member+index_classify"
_DERIVED_SPEC = resolve_derived_dataset("tushare", "index_member_versioned")
if _DERIVED_SPEC is None:
    raise RuntimeError("index_member_versioned 派生数据集契约未注册")

INDEX_MEMBER_VERSIONED_PRIMARY_KEYS: tuple[str, ...] = _DERIVED_SPEC.primary_keys
INDEX_MEMBER_VERSIONED_MEMBER_COLUMNS: tuple[str, ...] = (
    "index_code",
    "con_code",
    "in_date",
    "out_date",
    "is_new",
    "symbol",
)
UNRESOLVED_SRC = "UNRESOLVED"

_VERSIONED_COLUMNS: tuple[str, ...] = (
    *INDEX_MEMBER_VERSIONED_MEMBER_COLUMNS,
    "src",
    "src_status",
)
_LINEAGE_COLUMNS: tuple[str, ...] = (
    "data_source",
    "source_endpoint",
    "request_id",
    "updated_at",
    "market",
    "exchange",
    "currency",
    "adjustment",
    "schema_version",
    "source_scope",
    "field_provenance",
)


def empty_index_member_versioned() -> pl.DataFrame:
    """返回带稳定业务 Schema 的空版本化成分表。"""
    return pl.DataFrame(
        schema={
            "index_code": pl.String,
            "con_code": pl.String,
            "in_date": pl.Date,
            "out_date": pl.Date,
            "is_new": pl.String,
            "symbol": pl.String,
            "src": pl.String,
            "src_status": pl.String,
        }
    )


def build_index_member_versioned(
    index_member: pl.DataFrame,
    index_classify: pl.DataFrame,
) -> pl.DataFrame:
    """将无版本的成分记录按 ``index_classify.src`` 展开为版本化记录。

    ``index_member`` 是 TuShare 的原始成分事实，本身不携带申万版本；版本来自
    ``index_classify``。同一行业代码属于多个版本时保留多条记录，无法关联版本时
    保留一条 ``src=UNRESOLVED`` 记录，避免静默丢失原始成分。
    """
    if index_member.is_empty() or not {"index_code", "con_code"}.issubset(index_member.columns):
        return empty_index_member_versioned()

    members = _prepare_member_frame(index_member)
    if members.is_empty():
        return empty_index_member_versioned()

    classify = _prepare_classify_frame(index_classify)
    if classify.is_empty():
        return _with_unresolved_status(members)

    src_counts = classify.group_by("index_code").agg(pl.col("src").n_unique().alias("_src_count"))
    joined = members.join(classify, on="index_code", how="left").join(
        src_counts, on="index_code", how="left"
    )
    result = joined.with_columns(
        pl.when(pl.col("src").is_null())
        .then(pl.lit(UNRESOLVED_SRC))
        .otherwise(pl.col("src"))
        .alias("src")
    ).with_columns(
        pl.when(pl.col("src") == UNRESOLVED_SRC)
        .then(pl.lit("unresolved"))
        .when(pl.col("_src_count") > 1)
        .then(pl.lit("shared_code"))
        .otherwise(pl.lit("unique_code"))
        .alias("src_status")
    )
    return _finalize_versioned_frame(result)


def materialize_index_member_versioned(
    catalog: MarketDataCatalog | None = None,
    store: DuckDBMarketStore | None = None,
    *,
    storage_dir: Path | str | None = None,
    runtime: DataRuntimeContext | None = None,
    dry_run: bool = False,
) -> pl.DataFrame:
    """从现有 Curated 输入构建并可选写入版本化成员黄金表。"""
    active_catalog, active_store = _resolve_catalog_and_store(
        catalog,
        store,
        storage_dir=storage_dir,
        runtime=runtime,
    )
    if getattr(active_catalog, "data_source", "tushare") != "tushare":
        raise ValueError("index_member_versioned 只支持从 tushare Curated 输入构建")
    if active_store is not None and getattr(active_store, "data_source", "tushare") != "tushare":
        raise ValueError("index_member_versioned 只允许写入 tushare Curated 存储")
    members = _load_catalog_dataset(
        active_catalog,
        "index_member",
        columns=(*INDEX_MEMBER_VERSIONED_MEMBER_COLUMNS, "request_id"),
    )
    classify = _load_catalog_dataset(
        active_catalog,
        "index_classify",
        columns=("index_code", "src", "request_id"),
    )
    versioned = build_index_member_versioned(members, classify)
    if versioned.is_empty():
        return versioned

    materialized = _with_lineage(versioned, members, classify)
    if not dry_run:
        if active_store is None:
            raise ValueError("写入版本化成员表需要提供 store 或 storage_dir")
        _replace_materialized_file(active_store, materialized)
    return materialized


def _prepare_member_frame(index_member: pl.DataFrame) -> pl.DataFrame:
    expressions: list[pl.Expr] = []
    for column in INDEX_MEMBER_VERSIONED_MEMBER_COLUMNS:
        if column not in index_member.columns:
            dtype = pl.Date if column in {"in_date", "out_date"} else pl.String
            expressions.append(pl.lit(None, dtype=dtype).alias(column))
        elif column in {"in_date", "out_date"}:
            expressions.append(parse_mixed_date(column).alias(column))
        else:
            expressions.append(pl.col(column).cast(pl.String, strict=False).alias(column))
    return index_member.select(expressions).drop_nulls(subset=["index_code", "con_code"])


def _prepare_classify_frame(index_classify: pl.DataFrame) -> pl.DataFrame:
    required = {"index_code", "src"}
    if index_classify.is_empty() or not required.issubset(index_classify.columns):
        return pl.DataFrame(schema={"index_code": pl.String, "src": pl.String})
    return (
        index_classify.select(
            pl.col("index_code").cast(pl.String, strict=False).alias("index_code"),
            pl.col("src").cast(pl.String, strict=False).str.strip_chars().alias("src"),
        )
        .filter(
            pl.col("index_code").is_not_null() & pl.col("src").is_not_null() & (pl.col("src") != "")
        )
        .unique()
    )


def _with_unresolved_status(members: pl.DataFrame) -> pl.DataFrame:
    return _finalize_versioned_frame(
        members.with_columns(
            [
                pl.lit(UNRESOLVED_SRC).alias("src"),
                pl.lit("unresolved").alias("src_status"),
            ]
        )
    )


def _finalize_versioned_frame(frame: pl.DataFrame) -> pl.DataFrame:
    return (
        frame.select(_VERSIONED_COLUMNS)
        .unique(
            subset=list(INDEX_MEMBER_VERSIONED_PRIMARY_KEYS),
            keep="last",
        )
        .sort(["src", "index_code", "con_code", "in_date", "out_date"])
    )


def _with_lineage(
    versioned: pl.DataFrame,
    index_member: pl.DataFrame,
    index_classify: pl.DataFrame,
) -> pl.DataFrame:
    request_id = _lineage_request_id(index_member, index_classify)
    provenance = json.dumps(
        {
            "index_code": "tushare.index_member.index_code",
            "con_code": "tushare.index_member.con_code",
            "in_date": "tushare.index_member.in_date",
            "out_date": "tushare.index_member.out_date",
            "is_new": "tushare.index_member.is_new",
            "symbol": "tushare.index_member.symbol",
            "src": "tushare.index_classify.src",
            "src_status": "derived from index_classify.src cardinality",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    updated_at = datetime.now(UTC)
    return versioned.with_columns(
        [
            pl.lit("tushare").alias("data_source"),
            pl.lit(INDEX_MEMBER_VERSIONED_SOURCE_ENDPOINT).alias("source_endpoint"),
            pl.lit(request_id).alias("request_id"),
            pl.lit(updated_at).cast(pl.Datetime("us", "UTC")).alias("updated_at"),
            pl.lit("CN").alias("market"),
            pl.lit("CN").alias("exchange"),
            pl.lit("CNY").alias("currency"),
            pl.lit("raw").alias("adjustment"),
            pl.lit("v2").alias("schema_version"),
            pl.lit("index_member JOIN index_classify ON index_code").alias("source_scope"),
            pl.lit(provenance).alias("field_provenance"),
        ]
    ).select([*_VERSIONED_COLUMNS, *_LINEAGE_COLUMNS])


def _lineage_request_id(*frames: pl.DataFrame) -> str:
    source_ids: list[str] = []
    for frame in frames:
        if "request_id" in frame.columns:
            source_ids.extend(
                str(value)
                for value in frame.get_column("request_id").drop_nulls().unique().to_list()
            )
    payload = {
        "source_request_ids": sorted(set(source_ids)),
        "source_rows": [frame.height for frame in frames],
        "source_columns": [frame.columns for frame in frames],
    }
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def _load_catalog_dataset(
    catalog: MarketDataCatalog,
    dataset: str,
    *,
    columns: tuple[str, ...],
) -> pl.DataFrame:
    try:
        return load_dataset_compat(catalog, dataset, columns=columns, dedup=False)
    except Exception:
        return pl.DataFrame()


def _resolve_catalog_and_store(
    catalog: MarketDataCatalog | None,
    store: DuckDBMarketStore | None,
    *,
    storage_dir: Path | str | None,
    runtime: DataRuntimeContext | None,
) -> tuple[MarketDataCatalog, DuckDBMarketStore | None]:
    from stock_data.catalog import DataCatalog
    from stock_data.storage import DuckDBMarketStore

    active_catalog = catalog
    active_store = store
    root = Path(storage_dir) if storage_dir is not None else None
    if active_catalog is None:
        if root is None and active_store is not None:
            store_dir = Path(active_store.storage_dir)
            root = store_dir.parent if store_dir.name == "tushare" else store_dir
        active_catalog = DataCatalog(data_source="tushare", storage_dir=root, runtime=runtime)
    if active_store is None and root is None and active_catalog is not None:
        catalog_root = getattr(active_catalog, "storage_dir", None)
        if catalog_root is not None:
            root = Path(catalog_root)
    if active_store is None and root is not None:
        active_store = DuckDBMarketStore(storage_dir=root, data_source="tushare")
    elif active_store is None and runtime is not None:
        active_store = DuckDBMarketStore(data_source="tushare", runtime=runtime)
    return active_catalog, active_store


def _replace_materialized_file(store: DuckDBMarketStore, frame: pl.DataFrame) -> None:
    """原子替换派生表，避免重建时保留已失效的旧版本成员。"""
    import uuid

    target = store.get_parquet_path(INDEX_MEMBER_VERSIONED_DATASET, date(1970, 1, 1))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.tmp.parquet")
    try:
        frame.write_parquet(temporary)
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()


__all__ = [
    "INDEX_MEMBER_VERSIONED_DATASET",
    "INDEX_MEMBER_VERSIONED_PRIMARY_KEYS",
    "INDEX_MEMBER_VERSIONED_SOURCE_ENDPOINT",
    "UNRESOLVED_SRC",
    "build_index_member_versioned",
    "empty_index_member_versioned",
    "materialize_index_member_versioned",
]
