"""market_daily 构建血缘、版本指纹与长表转换。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import polars as pl

from stock.analytics.features.registry import FeatureRegistry
from stock.analytics.features.spec import EntityType

if TYPE_CHECKING:
    from datetime import date

    from stock.analytics.features.spec import FeatureSpec
    from stock.data.catalog import DataCatalog


def build_market_daily_metadata(catalog: DataCatalog, end_date: date) -> dict[str, object]:
    """生成宽表定义版本、源水位和文件级输入指纹。"""
    specs = _market_specs()
    manifest = [asdict(spec) for spec in specs]
    definition_fingerprint = _fingerprint(manifest)
    source_watermarks = _source_watermarks(catalog, specs, end_date)
    source_files = _source_file_snapshot(catalog, set(source_watermarks))
    return {
        "table": "market_daily",
        "available_at": datetime.now(UTC).isoformat(),
        "definition_fingerprint": definition_fingerprint,
        "feature_versions": {spec.feature_id: spec.definition_version for spec in specs},
        "source_watermarks": source_watermarks,
        "source_files": source_files,
        "input_fingerprint": _fingerprint(
            {
                "definition_fingerprint": definition_fingerprint,
                "source_watermarks": source_watermarks,
                "source_files": source_files,
            }
        ),
    }


def build_feature_values(df: pl.DataFrame, metadata: dict[str, object]) -> pl.DataFrame:
    """将 market_daily 宽表转换为带血缘字段的通用 Feature 长表。"""
    source_watermarks = metadata["source_watermarks"]
    source_files = metadata["source_files"]
    if not isinstance(source_watermarks, dict) or not isinstance(source_files, dict):
        raise ValueError("market_daily 构建元数据缺少源水位或文件快照")

    frames = [
        _feature_frame(
            df,
            spec,
            str(metadata["available_at"]),
            source_watermarks,
            source_files,
        )
        for spec in _market_specs()
        if spec.feature_id in df.columns
    ]
    return pl.concat(frames, how="vertical") if frames else pl.DataFrame()


def _market_specs() -> list[FeatureSpec]:
    return sorted(
        (
            spec
            for spec in FeatureRegistry.list_by_entity_type(EntityType.MARKET)
            if spec.is_materialized_wide
        ),
        key=lambda spec: spec.feature_id,
    )


def _source_watermarks(
    catalog: DataCatalog, specs: list[FeatureSpec], end_date: date
) -> dict[str, str]:
    datasets = {dataset for spec in specs for dataset in spec.required_datasets}
    available = {entry.dataset for entry in catalog.available_datasets()}
    watermarks: dict[str, str] = {}
    for dataset in sorted(datasets):
        if dataset == "opt_basic":
            watermarks[dataset] = "static" if dataset in available else "missing"
            continue
        dates = catalog.latest_trade_dates(dataset, n=1)
        if dates and dates[0] <= end_date:
            watermarks[dataset] = dates[0].isoformat()
            continue
        frame = catalog.load_dataset(dataset, end_date=end_date, columns=["trade_date"])
        values = frame["trade_date"].drop_nulls() if "trade_date" in frame.columns else pl.Series()
        latest_date = cast("date | None", values.max())
        watermarks[dataset] = latest_date.isoformat() if latest_date is not None else "missing"
    return watermarks


def _source_file_snapshot(
    catalog: DataCatalog, datasets: set[str]
) -> dict[str, list[dict[str, object]]]:
    snapshots: dict[str, list[dict[str, object]]] = {}
    entries = {entry.dataset: entry for entry in catalog.available_datasets()}
    for dataset in sorted(datasets):
        files = entries.get(dataset)
        snapshots[dataset] = []
        if files is None:
            continue
        for path in files.files:
            stat = path.stat()
            snapshots[dataset].append(
                {
                    "path": str(path.relative_to(catalog.storage_dir)),
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
    return snapshots


def _feature_frame(
    df: pl.DataFrame,
    spec: FeatureSpec,
    available_at: str,
    source_watermarks: dict[object, object],
    source_files: dict[object, object],
) -> pl.DataFrame:
    watermark = {
        dataset: source_watermarks.get(dataset, "missing") for dataset in spec.required_datasets
    }
    fingerprint = _fingerprint(
        {
            "spec": asdict(spec),
            "source_watermarks": watermark,
            "source_files": {
                dataset: source_files.get(dataset, []) for dataset in spec.required_datasets
            },
        }
    )
    return df.select(
        pl.lit(spec.feature_id).alias("feature_id"),
        pl.lit(spec.kind.value).alias("kind"),
        pl.lit(spec.entity_type.value).alias("entity_type"),
        pl.lit("CN").alias("entity_id"),
        pl.lit(spec.frequency).alias("frequency"),
        pl.col("trade_date").alias("observation_date"),
        pl.lit(available_at).alias("available_at"),
        pl.lit(spec.unit.value).alias("unit"),
        pl.col(spec.feature_id).cast(pl.Float64, strict=False).alias("value_float"),
        pl.lit(None, dtype=pl.Utf8).alias("value_str"),
        pl.lit(None, dtype=pl.Int64).alias("sample_size"),
        pl.when(pl.col(spec.feature_id).is_null())
        .then(pl.lit("insufficient"))
        .otherwise(pl.lit("ok"))
        .alias("status"),
        pl.lit(spec.definition_version).alias("definition_version"),
        pl.lit(json.dumps(watermark, ensure_ascii=True, sort_keys=True)).alias("source_watermark"),
        pl.lit(fingerprint).alias("input_fingerprint"),
    )


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
