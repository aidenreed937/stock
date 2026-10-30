"""为已落盘的 LiXinger 行业财报 Curated 表补充派生 TTM 同比字段。"""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import polars as pl

from stock_data.storage.compat import StorageCompat

LIXINGER_INDUSTRY_FINANCIAL_DATASETS = tuple(
    f"sw_2021_{level}fs_{sector}"
    for level in ("", "l2_", "l3_")
    for sector in ("non_financial", "bank", "security", "insurance")
)


def _field(metric: str, name: str) -> pl.Expr:
    return pl.col("q").struct.field("ps").struct.field(metric).struct.field(name)


def _summarize(path: Path, before: pl.DataFrame, after: pl.DataFrame) -> dict[str, Any]:
    counts = after.select(
        _field("toi", "ttm_y2y").is_null().sum().alias("toi_source_null"),
        _field("toi", "ttm_y2y_derived").is_not_null().sum().alias("toi_derived_nonnull"),
        _field("np", "ttm_y2y").is_null().sum().alias("np_source_null"),
        _field("np", "ttm_y2y_derived").is_not_null().sum().alias("np_derived_nonnull"),
    ).row(0)
    return {
        "dataset": path.parent.name,
        "path": str(path),
        "rows": after.height,
        "toi_source_null": counts[0],
        "toi_derived_nonnull": counts[1],
        "np_source_null": counts[2],
        "np_derived_nonnull": counts[3],
        "schema_changed": before.schema != after.schema,
    }


def _curated_path(curated_root: Path, dataset: str) -> Path:
    source_root = curated_root / "lixinger"
    if curated_root.name == "lixinger":
        source_root = curated_root
    return source_root / "market=CN" / dataset / "data.parquet"


def rebuild_lixinger_industry_financial_ttm(
    curated_root: Path | str = "data/curated",
    *,
    datasets: tuple[str, ...] = LIXINGER_INDUSTRY_FINANCIAL_DATASETS,
    apply: bool = False,
) -> list[dict[str, Any]]:
    """预览或原子写入行业财报 Curated TTM 派生字段。"""
    root = Path(curated_root)
    updates: list[tuple[Path, pl.DataFrame, pl.DataFrame]] = []
    summaries: list[dict[str, Any]] = []
    for dataset in datasets:
        path = _curated_path(root, dataset)
        if not path.exists():
            continue
        before = pl.read_parquet(path)
        after = StorageCompat.post_process_dataset(dataset, before)
        if before.height != after.height:
            raise ValueError(f"{path} 行数发生变化: {before.height} -> {after.height}")
        summaries.append(_summarize(path, before, after))
        updates.append((path, before, after))

    if apply:
        for path, before, after in updates:
            if before.schema == after.schema and before.equals(after):
                continue
            backup = path.with_name(f"{path.stem}.pre_ttm.bak.parquet")
            if not backup.exists():
                shutil.copy2(path, backup)
            temporary = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp.parquet")
            try:
                after.write_parquet(temporary)
                temporary.replace(path)
            finally:
                if temporary.exists():
                    temporary.unlink()
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description="补充 LiXinger 行业财报 Curated TTM 派生字段")
    parser.add_argument(
        "--curated-root", default="data/curated", help="Curated 根目录，默认 data/curated"
    )
    parser.add_argument(
        "--datasets", nargs="+", choices=LIXINGER_INDUSTRY_FINANCIAL_DATASETS, default=None
    )
    parser.add_argument("--apply", action="store_true", help="确认后原子写入 Curated")
    args = parser.parse_args()
    summaries = rebuild_lixinger_industry_financial_ttm(
        args.curated_root,
        datasets=tuple(args.datasets) if args.datasets else LIXINGER_INDUSTRY_FINANCIAL_DATASETS,
        apply=args.apply,
    )
    print(
        json.dumps(
            {"mode": "apply" if args.apply else "dry-run", "datasets": summaries},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
