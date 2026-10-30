"""将光伏产业 Curated 增长率从百分数点迁移为小数比例。

RAW 保留源端百分数文本；Curated 统一采用 ``0.1 == 10%``。默认只做影响预览，
传入 ``--apply`` 才会覆写目标 Parquet。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

CURATED_ROOT = Path("data/curated/industry")

_RATE_COLUMNS: dict[str, tuple[str, ...]] = {
    "silicon_wafer_monthly": ("polysilicon_output_yoy", "wafer_output_yoy"),
    "solar_cell_production": ("output_yoy", "output_cum_yoy"),
    "polysilicon_supply_monthly": ("production_yoy", "production_mom"),
    "pv_wafer_monthly": ("wafer_output_yoy", "wafer_output_mom"),
    "polysilicon_balance": ("supply_yoy", "demand_yoy", "scissors_spread_yoy"),
    "solar_supply_demand": (
        "supply_cell_yoy",
        "scissors_spread_yoy",
        "domestic_absorption_ratio",
    ),
}

_UNIT_VALUES = {
    "silicon_wafer_monthly": "ten_thousand_tons/gw/ratio",
    "solar_cell_production": "ten_thousand_kw/ratio",
    "solar_capacity": "gw/ratio",
    "polysilicon_supply_monthly": "ten_thousand_tons/ratio",
    "pv_wafer_monthly": "gw/ten_thousand_tons/ratio",
    "polysilicon_balance": "ten_thousand_tons/gw/ratio",
    "solar_supply_demand": "gw/ratio",
}


def _normalize_frame(dataset: str, frame: pl.DataFrame) -> pl.DataFrame:
    """在内存中完成单表比例归一化，并重算平衡表周期分。"""
    columns = [column for column in _RATE_COLUMNS.get(dataset, ()) if column in frame.columns]
    unit_values = (
        {str(value) for value in frame["unit"].drop_nulls().unique().to_list()}
        if "unit" in frame.columns
        else set()
    )
    already_ratio = bool(unit_values) and all("ratio" in value for value in unit_values)
    if columns and not already_ratio:
        frame = frame.with_columns([(pl.col(column) / 100.0).alias(column) for column in columns])

    if dataset == "polysilicon_balance" and {
        "scissors_spread_yoy",
        "inventory_weeks",
    }.issubset(frame.columns):
        frame = frame.with_columns(
            pl.when(
                pl.col("scissors_spread_yoy").is_not_null()
                & pl.col("inventory_weeks").is_not_null()
            )
            .then(
                (pl.col("scissors_spread_yoy") * 50.0 - (pl.col("inventory_weeks") - 2.0) * 8.0)
                .clip(-100.0, 100.0)
                .round(2)
            )
            .otherwise(None)
            .alias("cycle_score")
        )

    unit = _UNIT_VALUES.get(dataset)
    if unit and "unit" in frame.columns:
        frame = frame.with_columns(pl.lit(unit).alias("unit"))
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description="归一化光伏产业 Curated 增长率单位")
    parser.add_argument("--curated-root", default=str(CURATED_ROOT))
    parser.add_argument("--apply", action="store_true", help="确认后覆写 Curated Parquet")
    args = parser.parse_args()

    root = Path(args.curated_root)
    for dataset in (*_RATE_COLUMNS, "solar_capacity"):
        path = root / f"{dataset}.parquet"
        if not path.exists():
            print(f"[{dataset}] 缺失，跳过")
            continue
        before = pl.read_parquet(path)
        after = _normalize_frame(dataset, before)
        changed = {
            column: int((before[column].is_not_null() & (before[column] != after[column])).sum())
            for column in _RATE_COLUMNS.get(dataset, ())
            if column in before.columns
        }
        mode = "apply" if args.apply else "dry-run"
        print(f"[{dataset}] {mode}: rows={before.height}, changed={changed}")
        if args.apply:
            after.write_parquet(path)


if __name__ == "__main__":
    main()
