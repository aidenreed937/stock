"""fund_portfolio 的 RAW -> Curated 重建工具。

背景：通用归一化器曾把源端两个语义不同的标识列错误合并——
``ts_code``（基金自身代码）与 ``symbol``（被持有股票代码）被
``coalesce([ts_code, symbol])`` 合并为 ``symbol`` 并丢弃 ``ts_code``，
导致 Curated 侧 ``symbol`` 存入基金代码、被持有股票代码永久丢失。

修复方式：端点契约新增 ``identity_renames={"ts_code": "fund_code"}``，
归一化器在别名合并之前先改名，两个代码得以并存。
RAW 侧未受影响，因此只需从 RAW 重放重建 Curated，无需重新调用上游 API。

用法::

    uv run python -m stock_data.governance.ops.rebuild_fund_portfolio --apply
"""

import argparse
import shutil
from pathlib import Path
from typing import Any

import polars as pl

from stock_core.utils.logger import logger
from stock_data.fetcher.tushare.registry import TUSHARE_API_REGISTRY
from stock_data.pipeline.cleaner.generic_cleaner import GenericCleaner
from stock_data.pipeline.normalizer.generic_normalizer import GenericNormalizer
from stock_data.pipeline.stages import NormalizerStage

_ENDPOINT = "fund_portfolio"
_RAW_DIR = Path("data/raw/tushare/market=CN") / _ENDPOINT
_CURATED_DIR = Path("data/curated/tushare/market=CN") / _ENDPOINT

# 重建后的主键：基金代码 + 公告日 + 报告期 + 被持有股票代码
_CURATED_PRIMARY_KEYS = ["fund_code", "ann_date", "end_date", "symbol"]

# 列顺序与既有 Curated 保持一致，仅在被持有股票代码前插入基金代码
_CURATED_COLUMN_ORDER = [
    "ann_date",
    "end_date",
    "fund_code",
    "symbol",
    "mkv",
    "amount",
    "stk_mkv_ratio",
    "stk_float_ratio",
    "data_source",
    "source_endpoint",
    "request_id",
    "updated_at",
    "market",
    "exchange",
    "currency",
    "adjustment",
    "schema_version",
]


def _is_artifact(path: Path) -> bool:
    return path.name.endswith((".bak.parquet", ".tmp.parquet", ".migration.tmp.parquet"))


def _partition_label(raw_path: Path, raw_root: Path) -> str:
    return "/".join(
        part
        for part in raw_path.relative_to(raw_root).parts
        if part.startswith(("year=", "month="))
    )


def rebuild_partition(
    raw_path: Path,
    curated_path: Path,
    *,
    raw_root: Path,
    cleaner: GenericCleaner,
    stage: NormalizerStage,
    apply: bool = False,
) -> dict[str, Any]:
    """重放单个 RAW 分区并重建对应的 Curated 分区。"""
    raw_df = pl.read_parquet(raw_path)
    raw_count = len(raw_df)

    cleaned = cleaner.clean(raw_df)
    decorated = stage.normalize(
        cleaned,
        None,
        _ENDPOINT,
        f"rebuild:{_ENDPOINT}:{_partition_label(raw_path, raw_root)}",
        dataset=_ENDPOINT,
    )

    if decorated.is_empty():
        return {"partition": str(raw_path), "raw": raw_count, "curated": 0, "duplicates": 0}

    missing = [column for column in _CURATED_PRIMARY_KEYS if column not in decorated.columns]
    if missing:
        raise ValueError(f"重建结果缺少主键列 {missing}: {raw_path}")

    ordered = decorated.select(
        [column for column in _CURATED_COLUMN_ORDER if column in decorated.columns]
    ).sort(_CURATED_PRIMARY_KEYS)
    deduped = ordered.unique(subset=_CURATED_PRIMARY_KEYS, keep="last", maintain_order=True)
    duplicates = len(ordered) - len(deduped)

    if apply:
        curated_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = curated_path.with_suffix(".tmp.parquet")
        bak_path = curated_path.with_suffix(".bak.parquet")
        deduped.write_parquet(tmp_path)
        if curated_path.exists() and not bak_path.exists():
            shutil.copy2(curated_path, bak_path)
        tmp_path.replace(curated_path)

    return {
        "partition": str(raw_path),
        "raw": raw_count,
        "curated": len(deduped),
        "duplicates": duplicates,
    }


def rebuild_fund_portfolio(
    raw_root: str | Path = _RAW_DIR,
    curated_root: str | Path = _CURATED_DIR,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """遍历全部分区，从 RAW 重建 Curated fund_portfolio。"""
    meta = TUSHARE_API_REGISTRY[_ENDPOINT]
    cleaner = GenericCleaner(primary_keys=list(meta.primary_keys))
    stage = NormalizerStage(
        GenericNormalizer(
            date_columns=list(meta.date_columns) or None,
            identity_renames=meta.identity_renames,
        ),
        data_source="tushare",
    )

    raw_base, curated_base = Path(raw_root), Path(curated_root)
    raw_files = (
        sorted(p for p in raw_base.rglob("*.parquet") if not _is_artifact(p))
        if raw_base.exists()
        else []
    )

    results: list[dict[str, Any]] = []
    total_raw = total_curated = total_duplicates = 0
    for raw_file in raw_files:
        curated_file = curated_base / raw_file.relative_to(raw_base)
        result = rebuild_partition(
            raw_file,
            curated_file,
            raw_root=raw_base,
            cleaner=cleaner,
            stage=stage,
            apply=apply,
        )
        results.append(result)
        total_raw += result["raw"]
        total_curated += result["curated"]
        total_duplicates += result["duplicates"]

    logger.info(
        f"fund_portfolio 重建完成 [apply={apply}]: 分区 {len(raw_files)} 个, "
        f"RAW 行 {total_raw:,} -> Curated 行 {total_curated:,}, 去重 {total_duplicates:,}"
    )

    return {
        "files_processed": len(raw_files),
        "raw_rows": total_raw,
        "curated_rows": total_curated,
        "duplicates": total_duplicates,
        "applied": apply,
        "partitions": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="fund_portfolio RAW -> Curated 重建工具")
    parser.add_argument("--raw-root", default=str(_RAW_DIR), help="RAW fund_portfolio 根目录")
    parser.add_argument("--curated-root", default=str(_CURATED_DIR), help="Curated 根目录")
    parser.add_argument("--apply", action="store_true", help="执行实际写入 (默认只读预览)")
    args = parser.parse_args()

    rebuild_fund_portfolio(args.raw_root, args.curated_root, apply=args.apply)


if __name__ == "__main__":
    main()
