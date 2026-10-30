"""chemical_spreads 的「配置驱动计算 -> Curated」重建工具。

背景：``ChemicalSpreadCalculator`` 过去只读取 ``data/raw/industry/chemicals/
chemical_spreads.csv`` 这份人工维护的 355 行旧表（仅覆盖纯碱联碱双吨与氯碱
ECU），``cost_models.yaml`` 里的单耗系数与本地现货价从未参与价差计算。

现在价差由 ``build_computed_spreads`` 按各品种 cost_models.yaml 系数与
Curated 现货/期货/煤炭价格实算，再与存量人工事实行合并。端点 ``chemical_spreads``
已改走计算路径，但端点调度只物化增量窗口内的行，历史区间需要一次性回填。

用法::

    uv run python -m stock_data.governance.ops.rebuild_chemical_spreads
    uv run python -m stock_data.governance.ops.rebuild_chemical_spreads --apply
"""

import argparse
import shutil
from pathlib import Path

import polars as pl

from stock_core.utils.logger import logger
from stock_data.fetcher.industry.chemicals.collectors.spreads import ChemicalSpreadCalculator

_TARGET_FILE = "chemical_spreads.parquet"
_DEFAULT_RAW_DIR = Path("data/raw/industry")
_DEFAULT_CURATED_DIR = Path("data/curated/industry")


def rebuild_chemical_spreads(
    raw_dir: str | Path = _DEFAULT_RAW_DIR,
    curated_dir: str | Path = _DEFAULT_CURATED_DIR,
    *,
    apply: bool = False,
) -> dict[str, object]:
    """按配置系数与本地价格重算价差并写回 Curated Parquet。"""
    calc = ChemicalSpreadCalculator(raw_dir=Path(raw_dir), curated_dir=Path(curated_dir))
    frame = calc.build_historical_spreads()

    target = Path(curated_dir) / _TARGET_FILE
    profile = (
        frame.group_by("product_name", "process_type")
        .agg(
            pl.len().alias("rows"),
            pl.col("trade_date").min().alias("start"),
            pl.col("trade_date").max().alias("end"),
            pl.col("spread_margin_cny").last().alias("latest_margin"),
        )
        .sort("product_name", "process_type")
    )

    for row in profile.iter_rows(named=True):
        logger.info(
            f"[chemical_spreads] {row['product_name']}/{row['process_type']}: "
            f"{row['rows']} 行 {row['start']} ~ {row['end']} "
            f"最新理论利润 {row['latest_margin']:.2f} 元/吨"
        )
    logger.info(
        f"chemical_spreads 重算完成 [apply={apply}]: {frame.height:,} 行, "
        f"{profile.height} 个工艺口径 -> {target}"
    )

    if not apply:
        return {
            "rows": frame.height,
            "products": profile.height,
            "target": str(target),
            "applied": False,
        }

    if target.exists():
        backup = target.with_suffix(".bak.parquet")
        shutil.copy2(target, backup)
        logger.info(f"已备份原 Curated 文件到 {backup}")

    target.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(target)
    return {
        "rows": frame.height,
        "products": profile.height,
        "target": str(target),
        "applied": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="chemical_spreads 配置驱动重算与物化工具")
    parser.add_argument("--raw-root", default=str(_DEFAULT_RAW_DIR), help="RAW industry 根目录")
    parser.add_argument("--curated-root", default=str(_DEFAULT_CURATED_DIR), help="Curated 根目录")
    parser.add_argument("--apply", action="store_true", help="执行实际写入 (默认只读预览)")
    args = parser.parse_args()

    rebuild_chemical_spreads(args.raw_root, args.curated_root, apply=args.apply)


if __name__ == "__main__":
    main()
