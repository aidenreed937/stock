"""本地数据迁移与去重工具，默认只读预览，显式 --apply 才写入。"""

from pathlib import Path
import shutil

import polars as pl

from stock.constants import BAR_DATASETS
from stock.data.audit.baseline import build_baseline
from stock.data.cleaner.bar_cleaner import BarDataCleaner
from stock.data.quality.quarantine import QuarantineStore

_BAR_DATASETS = BAR_DATASETS


def _is_artifact(path: Path) -> bool:
    """跳过迁移生成的备份和临时文件，避免重复扫描旧快照。"""
    return path.name.endswith((".bak.parquet", ".tmp.parquet"))


def _endpoint_name(path: Path) -> str:
    """从 Hive 分区路径解析数据集名称。"""
    if path.parent.name.startswith("month="):
        return path.parent.parent.parent.name
    return path.stem.split(".", 1)[0]


def _primary_keys(path: Path, columns: list[str]) -> list[str]:
    """按目录 endpoint 使用注册表主键，未知数据集才回退完整行。"""
    endpoint = _endpoint_name(path)
    if endpoint in BAR_DATASETS:
        # 行情的 adjustment 是数据属性；同一市场、标的、交易日只允许一条记录。
        return [
            column
            for column in ("market", "symbol", "trade_date")
            if column in columns
        ]
    for module_name, registry_name in (
        ("stock.data.fetcher.tushare.registry", "TUSHARE_API_REGISTRY"),
        ("stock.data.fetcher.lixinger.registry", "LIXINGER_API_REGISTRY"),
    ):
        try:
            module = __import__(module_name, fromlist=[registry_name])
            meta = getattr(module, registry_name).get(endpoint)
            if meta:
                aliases = {"ts_code": "symbol", "stockCode": "symbol", "date": "trade_date"}
                keys = []
                for key in meta.primary_keys:
                    canonical = aliases.get(key, key)
                    if canonical in columns:
                        keys.append(canonical)
                    elif key in columns:
                        keys.append(key)
                if keys:
                    return keys
        except Exception:
            continue
    return []


def _normalize_identity_columns(df: pl.DataFrame) -> tuple[pl.DataFrame, bool]:
    """将历史文件中的源端身份列归一为 Curated 标准列。"""
    normalized = df
    changed = False
    for alias in ("ts_code", "stockCode", "code"):
        if alias not in normalized.columns:
            continue
        if "symbol" not in normalized.columns:
            normalized = normalized.rename({alias: "symbol"})
        else:
            normalized = normalized.with_columns(
                pl.coalesce(
                    [
                        pl.col(alias).cast(pl.Utf8, strict=False),
                        pl.col("symbol").cast(pl.Utf8, strict=False),
                    ]
                ).alias("symbol")
            ).drop(alias)
        changed = True
    if "date" in normalized.columns:
        if "trade_date" not in normalized.columns:
            normalized = normalized.rename({"date": "trade_date"})
        else:
            normalized = normalized.with_columns(
                pl.coalesce(
                    [
                        pl.col("trade_date").cast(pl.Utf8, strict=False),
                        pl.col("date").cast(pl.Utf8, strict=False),
                    ]
                ).alias("trade_date")
            ).drop("date")
        changed = True
    return normalized, changed


def _infer_data_source(path: Path) -> str | None:
    """从历史数据路径推断数据源名称。"""
    providers = {"tushare", "lixinger", "yfinance", "fred", "mock"}
    return next((part for part in path.parts if part in providers), None)


def _repair_lineage(df: pl.DataFrame, path: Path) -> tuple[pl.DataFrame, bool]:
    """为缺少血统列的历史文件补入稳定的迁移标识。"""
    endpoint = _endpoint_name(path)
    partition = "/".join(
        part for part in path.parts if part.startswith(("year=", "month="))
    )
    legacy_request_id = f"legacy:{endpoint}:{partition or path.name}"
    repaired = df
    changed = False

    data_source = _infer_data_source(path)
    if "data_source" not in repaired.columns and data_source:
        repaired = repaired.with_columns(pl.lit(data_source).alias("data_source"))
        changed = True
    elif (
        data_source
        and "data_source" in repaired.columns
        and repaired.get_column("data_source").null_count() > 0
    ):
        repaired = repaired.with_columns(
            pl.col("data_source").fill_null(data_source).alias("data_source")
        )
        changed = True

    if "source_endpoint" not in repaired.columns:
        repaired = repaired.with_columns(pl.lit(endpoint).alias("source_endpoint"))
        changed = True
    elif repaired.get_column("source_endpoint").null_count() > 0:
        repaired = repaired.with_columns(
            pl.col("source_endpoint").fill_null(endpoint).alias("source_endpoint")
        )
        changed = True

    if "request_id" not in repaired.columns:
        repaired = repaired.with_columns(pl.lit(legacy_request_id).alias("request_id"))
        changed = True
    elif repaired.get_column("request_id").null_count() > 0:
        repaired = repaired.with_columns(
            pl.col("request_id").fill_null(legacy_request_id).alias("request_id")
        )
        changed = True

    if "updated_at" not in repaired.columns:
        repaired = repaired.with_columns(
            pl.lit(None, dtype=pl.Datetime).alias("updated_at")
        )
        changed = True

    return repaired, changed


def _dedupe_frame(df: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
    """按主键去重，优先保留字段完整且更新时间较新的记录。"""
    if not keys:
        return df.unique(keep="last")

    quality_columns = [column for column in df.columns if column not in keys]
    work = df.with_row_index("_migration_order")
    if "updated_at" in work.columns:
        updated_at = work.schema["updated_at"]
        if isinstance(updated_at, pl.Datetime):
            updated_at_expr = pl.col("updated_at").cast(pl.Int64, strict=False)
        else:
            updated_at_expr = (
                pl.col("updated_at")
                .cast(pl.Utf8, strict=False)
                .str.to_datetime(strict=False)
                .cast(pl.Int64, strict=False)
            )
        work = work.with_columns(
            updated_at_expr.alias("_migration_updated_at"),
            pl.col("updated_at").is_not_null().cast(pl.UInt8).alias("_migration_has_updated_at"),
        )
    else:
        work = work.with_columns(
            pl.lit(None, dtype=pl.Int64).alias("_migration_updated_at"),
            pl.lit(0, dtype=pl.UInt8).alias("_migration_has_updated_at"),
        )
    work = work.with_columns(
        pl.col("_migration_updated_at")
        .fill_null(0)
        .alias("_migration_updated_sort")
    )

    if quality_columns:
        work = work.with_columns(
            pl.sum_horizontal(
                *[pl.col(column).is_not_null().cast(pl.UInt16) for column in quality_columns]
            ).alias("_migration_completeness")
        )
    else:
        work = work.with_columns(pl.lit(0, dtype=pl.UInt16).alias("_migration_completeness"))

    return (
        work.sort(
            keys
            + [
                "_migration_has_updated_at",
                "_migration_updated_sort",
                "_migration_completeness",
                "_migration_order",
            ],
            nulls_last=True,
        )
        .unique(subset=keys, keep="last", maintain_order=True)
        .drop(
            [
                "_migration_order",
                "_migration_updated_at",
                "_migration_has_updated_at",
                "_migration_updated_sort",
                "_migration_completeness",
            ]
        )
    )


def _repair_bar_quality(
    df: pl.DataFrame,
    path: Path,
    *,
    apply: bool,
    quarantine_root: str | Path,
) -> tuple[pl.DataFrame, int]:
    """按行情清洗规则移除历史非法 OHLC，并在应用时写入隔离区。"""
    endpoint = _endpoint_name(path)
    required = {"symbol", "trade_date", "open", "high", "low", "close"}
    if endpoint not in _BAR_DATASETS or not required.issubset(df.columns):
        return df, 0

    cleaned = BarDataCleaner().clean(df)
    removed = len(df) - len(cleaned)
    if removed and apply:
        rejected = df.join(cleaned, on=df.columns, how="anti")
        partition = "/".join(
            part for part in path.parts if part.startswith(("year=", "month="))
        )
        QuarantineStore(quarantine_root).write(
            rejected,
            endpoint=endpoint,
            reason="historical_bar_quality_rejected",
            request_id=f"legacy:{endpoint}:{partition or path.name}",
            data_source="",
        )
    return cleaned, removed

def migrate_parquet(
    root: str = "data",
    apply: bool = False,
    repair_lineage: bool = False,
    repair_bar_quality: bool = False,
    quarantine_root: str | Path = "data/quarantine",
) -> dict[str, int]:
    """按自然键去重并可修复历史行情质量；写入保留 `.bak` 备份。"""
    changed = 0
    rows_removed = 0
    lineage_files_changed = 0
    schema_files_changed = 0
    quality_files_changed = 0
    quality_rows_removed = 0
    base = Path(root)
    paths = [path for path in base.rglob("*.parquet") if not _is_artifact(path)] if base.exists() else []
    for path in sorted(paths):
        df = pl.read_parquet(path)
        normalized, schema_changed = _normalize_identity_columns(df)
        keys = _primary_keys(path, normalized.columns)
        deduped = _dedupe_frame(normalized, keys)
        removed = len(df) - len(deduped)
        repaired = deduped
        quality_removed = 0
        if repair_bar_quality:
            repaired, quality_removed = _repair_bar_quality(
                repaired,
                path,
                apply=apply,
                quarantine_root=quarantine_root,
            )
        lineage_changed = False
        if repair_lineage:
            repaired, lineage_changed = _repair_lineage(repaired, path)
        if quality_removed:
            quality_files_changed += 1
            quality_rows_removed += quality_removed
        if not removed and not quality_removed and not lineage_changed and not schema_changed:
            continue
        changed += 1
        rows_removed += removed + quality_removed
        lineage_files_changed += int(lineage_changed)
        schema_files_changed += int(schema_changed)
        if apply:
            tmp = path.with_suffix(".migration.tmp.parquet")
            backup = path.with_suffix(".bak.parquet")
            repaired.write_parquet(tmp)
            if not backup.exists():
                shutil.copy2(path, backup)
            tmp.replace(path)
    return {
        "files_changed": changed,
        "rows_removed": rows_removed,
        "lineage_files_changed": lineage_files_changed,
        "schema_files_changed": schema_files_changed,
        "quality_files_changed": quality_files_changed,
        "quality_rows_removed": quality_rows_removed,
        "applied": int(apply),
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="本地 Parquet 去重迁移")
    parser.add_argument("--root", default="data")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--repair-lineage", action="store_true")
    parser.add_argument("--repair-bar-quality", action="store_true")
    parser.add_argument("--quarantine-root", default="data/quarantine")
    args = parser.parse_args()
    before = build_baseline(args.root)
    result = migrate_parquet(
        args.root,
        args.apply,
        args.repair_lineage,
        args.repair_bar_quality,
        args.quarantine_root,
    )
    after = build_baseline(args.root)
    print(json.dumps({"before_files": len(before["files"]), "after_files": len(after["files"]), **result}, ensure_ascii=False, indent=2))
