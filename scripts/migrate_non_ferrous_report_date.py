"""迁移有色金属 Curated 的 report_date 日期类型。"""

from __future__ import annotations

import argparse
import uuid
from pathlib import Path

import polars as pl

DEFAULT_PATH = Path("data/curated/industry/non_ferrous_metals.parquet")


def migrate(path: Path, *, apply: bool) -> None:
    """将 report_date 转为 pl.Date，并保留其余金属事实值不变。"""
    if not path.exists():
        raise FileNotFoundError(path)

    before = pl.read_parquet(path)
    if "report_date" not in before.columns:
        raise ValueError(f"缺少 report_date: {path}")
    if before.schema["report_date"] == pl.Date:
        print(f"[{path}] 已是 pl.Date，跳过")
        return
    if before.schema["report_date"] != pl.String:
        raise TypeError(f"report_date 类型不符合预期: {before.schema['report_date']}")

    after = before.with_columns(
        pl.col("report_date").str.to_date(format="%Y-%m-%d", strict=True).alias("report_date")
    )
    if after["report_date"].null_count():
        raise ValueError("report_date 转换后存在空值")
    if after.height != before.height:
        raise ValueError("迁移改变了行数")
    if after["report_date"].n_unique() != before["report_date"].n_unique():
        raise ValueError("迁移改变了 report_date 唯一值数量")
    other_columns = [column for column in before.columns if column != "report_date"]
    if not before.select(other_columns).equals(after.select(other_columns)):
        raise ValueError("迁移改变了 report_date 以外的字段值")

    print(
        f"[{path}] {'apply' if apply else 'dry-run'}: "
        f"rows={before.height}, report_date String -> Date, nulls=0, "
        f"unique_dates={after['report_date'].n_unique()}"
    )
    if not apply:
        return

    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        after.write_parquet(temp_path)
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移有色金属 report_date 日期类型")
    parser.add_argument("--path", default=str(DEFAULT_PATH))
    parser.add_argument("--apply", action="store_true", help="覆写目标 Parquet")
    args = parser.parse_args()
    migrate(Path(args.path), apply=args.apply)


if __name__ == "__main__":
    main()
