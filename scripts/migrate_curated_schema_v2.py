"""将 Curated 历史 Parquet 迁移到 Schema v2，默认只做 dry-run。"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import polars as pl

from stock_core.constants import BAR_DATASETS
from stock_core.contracts import get_contract_for_dataset
from stock_data.catalog.ops import dataset_name
from stock_data.pipeline.normalizer.bar_normalizer import infer_market_exchange_currency
from stock_data.storage.compat import StorageCompat
from stock_data.storage.read_compat import normalize_read_frame

_PROVIDERS = frozenset({"tushare", "lixinger", "yfinance", "fred", "alphavantage"})
_ARTIFACT_SUFFIXES = (".bak.parquet", ".tmp.parquet", ".migration.tmp.parquet")
_UTC_DATETIME = pl.Datetime("us", "UTC")
_DATASET_SCHEMA_COLUMNS: dict[str, tuple[tuple[str, pl.DataType], ...]] = {
    "etf_share_size": (
        ("trade_date", pl.Date),
        ("etf_name", pl.String),
        ("fund_type", pl.String),
        ("total_share", pl.Float64),
        ("total_size", pl.Float64),
        ("float_share", pl.Float64),
        ("float_size", pl.Float64),
        ("nav", pl.Float64),
        ("close", pl.Float64),
        ("exchange", pl.String),
        ("symbol", pl.String),
        ("source_unit_note", pl.String),
        ("source_id", pl.String),
        ("fetched_at", pl.String),
        ("data_source", pl.String),
        ("source_endpoint", pl.String),
        ("request_id", pl.String),
        ("updated_at", _UTC_DATETIME),
        ("market", pl.String),
        ("currency", pl.String),
        ("adjustment", pl.String),
        ("schema_version", pl.String),
    ),
    "express": (
        ("symbol", pl.String),
        ("ann_date", pl.Date),
        ("end_date", pl.Date),
        ("revenue", pl.Float64),
        ("operate_profit", pl.Float64),
        ("total_profit", pl.Float64),
        ("n_income", pl.Float64),
        ("total_assets", pl.Float64),
        ("total_hldr_eqy_exc_min_int", pl.Float64),
        ("diluted_eps", pl.Float64),
        ("diluted_roe", pl.Float64),
        ("prior_period_net_profit", pl.Float64),
        ("bps", pl.Float64),
        ("open_net_assets", pl.Float64),
        ("open_bps", pl.Float64),
        ("perf_summary", pl.String),
        ("update_flag", pl.String),
        ("data_source", pl.String),
        ("source_endpoint", pl.String),
        ("request_id", pl.String),
        ("updated_at", _UTC_DATETIME),
        ("market", pl.String),
        ("exchange", pl.String),
        ("currency", pl.String),
        ("adjustment", pl.String),
        ("schema_version", pl.String),
    ),
}


def _curated_root(root: str | Path) -> Path:
    resolved = Path(root).expanduser().resolve()
    if resolved.name != "curated":
        raise ValueError(f"迁移根目录必须是 data/curated，实际: {resolved}")
    return resolved


def _iter_curated_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.parquet")
        if path.relative_to(root).parts and path.relative_to(root).parts[0] in _PROVIDERS
        if not path.name.endswith(_ARTIFACT_SUFFIXES)
    )


def _provider_from_path(path: Path) -> str:
    for provider in _PROVIDERS:
        if provider in path.parts:
            return provider
    raise ValueError(f"无法从 Curated 路径识别数据源: {path}")


def _legacy_request_id(dataset: str, path: Path) -> str:
    partition = "/".join(
        part for part in path.parts if part.startswith(("market=", "year=", "month="))
    )
    return f"legacy:{dataset}:{partition or path.name}"


def _fill_string_column(df: pl.DataFrame, column: str, value: str) -> pl.DataFrame:
    expression = pl.col(column).cast(pl.Utf8, strict=False).fill_null(value).alias(column)
    if column not in df.columns:
        expression = pl.lit(value).alias(column)
    return df.with_columns(expression)


def _normalize_updated_at(df: pl.DataFrame) -> pl.DataFrame:
    if "updated_at" not in df.columns:
        return df.with_columns(pl.lit(None, dtype=_UTC_DATETIME).alias("updated_at"))

    dtype = df.schema["updated_at"]
    if isinstance(dtype, pl.Datetime):
        return StorageCompat.normalize_datetime_columns(df)
    if dtype in (pl.Utf8, pl.String):
        parsed = (
            pl.col("updated_at")
            .str.to_datetime(strict=False)
            .dt.replace_time_zone("UTC")
            .cast(_UTC_DATETIME, strict=False)
            .alias("updated_at")
        )
        return df.with_columns(parsed)
    return df.with_columns(
        pl.col("updated_at").cast(_UTC_DATETIME, strict=False).alias("updated_at")
    )


def _normalize_bar_metadata(df: pl.DataFrame, dataset: str, provider: str) -> pl.DataFrame:
    if dataset not in BAR_DATASETS:
        return df

    normalized = _fill_string_column(df, "adjustment", "raw")
    if "symbol" not in normalized.columns:
        return normalized

    symbol = pl.col("symbol").cast(pl.Utf8, strict=False)
    market, exchange, currency = infer_market_exchange_currency(symbol, data_source=provider)
    for column, expression in (
        ("market", market),
        ("exchange", exchange),
        ("currency", currency),
    ):
        if column not in normalized.columns:
            normalized = normalized.with_columns(expression.alias(column))
        else:
            normalized = normalized.with_columns(
                pl.col(column).cast(pl.Utf8, strict=False).fill_null(expression).alias(column)
            )
    return normalized


def _normalize_dataset_schema(df: pl.DataFrame, dataset: str) -> pl.DataFrame:
    """补齐已登记的历史可选列，并固定其物理类型与列顺序。"""
    specification = _DATASET_SCHEMA_COLUMNS.get(dataset)
    if specification is None or df.is_empty():
        return df

    normalized = df
    expected_columns = [column for column, _ in specification]
    for column, dtype in specification:
        if column not in normalized.columns:
            normalized = normalized.with_columns(pl.lit(None, dtype=dtype).alias(column))
        elif normalized.schema[column] != dtype:
            normalized = normalized.with_columns(
                pl.col(column).cast(dtype, strict=False).alias(column)
            )

    extras = [column for column in normalized.columns if column not in expected_columns]
    return normalized.select([*expected_columns, *extras])


def normalize_curated_frame(df: pl.DataFrame, path: Path) -> pl.DataFrame:
    """按路径数据集契约将单个历史 Curated 文件规范化为 v2。"""
    provider = _provider_from_path(path)
    dataset = dataset_name(path)
    normalized = normalize_read_frame(dataset, df)
    normalized = _normalize_bar_metadata(normalized, dataset, provider)
    normalized = _fill_string_column(normalized, "data_source", provider)
    normalized = _fill_string_column(normalized, "source_endpoint", dataset)
    normalized = _fill_string_column(
        normalized,
        "request_id",
        _legacy_request_id(dataset, path),
    )
    normalized = _normalize_updated_at(normalized)
    normalized = _fill_string_column(normalized, "schema_version", "v2")

    if "schema_version" in normalized.columns:
        normalized = normalized.with_columns(pl.lit("v2").alias("schema_version"))

    normalized = _normalize_dataset_schema(normalized, dataset)

    dedup_keys = StorageCompat.resolve_dedup_keys(
        dataset,
        provider,
        provider,
        normalized,
    )
    if dedup_keys and all(column in normalized.columns for column in dedup_keys):
        normalized = normalized.unique(subset=dedup_keys, keep="last", maintain_order=True)

    sort_columns = [column for column in ("trade_date", "symbol") if column in normalized.columns]
    if sort_columns:
        normalized = normalized.sort(sort_columns)

    contract = get_contract_for_dataset(dataset)
    if contract is not None:
        contract.validate(normalized)
    return normalized


def _changed(before: pl.DataFrame, after: pl.DataFrame) -> bool:
    return (
        before.schema != after.schema
        or before.shape != after.shape
        or not before.equals(after, null_equal=True)
    )


def _inspect_file(path: Path) -> dict[str, Any]:
    before = pl.read_parquet(path)
    after = normalize_curated_frame(before, path)
    return {
        "path": str(path),
        "changed": _changed(before, after),
        "rows_before": len(before),
        "rows_after": len(after),
        "columns_added": sorted(set(after.columns) - set(before.columns)),
        "columns_removed": sorted(set(before.columns) - set(after.columns)),
    }


def _write_migrated_file(path: Path) -> None:
    before = pl.read_parquet(path)
    migrated = normalize_curated_frame(before, path)
    if not _changed(before, migrated):
        return

    temporary = path.with_name(f"{path.stem}.migration.tmp.parquet")
    backup = path.with_name(f"{path.stem}.bak.parquet")
    try:
        migrated.write_parquet(temporary, compression="zstd")
        if not backup.exists():
            shutil.copy2(path, backup)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def migrate_curated(root: str | Path = "data/curated", apply: bool = False) -> dict[str, Any]:
    """预检或迁移 Curated 文件；存在失败文件时 apply 阶段不会写入任何文件。"""
    curated_root = _curated_root(root)
    all_paths = (
        sorted(
            path
            for path in curated_root.rglob("*.parquet")
            if not path.name.endswith(_ARTIFACT_SUFFIXES)
        )
        if curated_root.exists()
        else []
    )
    paths = _iter_curated_files(curated_root) if curated_root.exists() else []
    reports: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for path in paths:
        try:
            reports.append(_inspect_file(path))
        except Exception as exc:
            errors.append({"path": str(path), "error": str(exc)})

    changed_reports = [report for report in reports if report["changed"]]
    applied = False
    if apply and not errors:
        for report in changed_reports:
            _write_migrated_file(Path(report["path"]))
        applied = True

    return {
        "root": str(curated_root),
        "files_scanned": len(paths),
        "files_skipped": len(all_paths) - len(paths),
        "files_changed": len(changed_reports),
        "rows_removed": sum(report["rows_before"] - report["rows_after"] for report in reports),
        "files_failed": len(errors),
        "applied": applied,
        "errors": errors[:20],
        "changed_examples": changed_reports[:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Curated Schema v2 迁移工具")
    parser.add_argument("--root", default="data/curated", help="Curated 根目录")
    parser.add_argument("--apply", action="store_true", help="确认后写入并保留 .bak.parquet")
    args = parser.parse_args()
    result = migrate_curated(args.root, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["files_failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
