"""资金流向与北向持仓 (hk_hold / moneyflow) 领域对账审计模块。"""

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_core.utils.logger import logger
from stock_data.storage.compat import StorageCompat


def run_hk_hold_audit(
    target_date: date, data_source: str = "tushare", quiet: bool = False
) -> dict[str, Any]:
    """审计 hk_hold (北向个股持仓明细) 数据集在开港通交易日的真实落盘记录与持股规模。"""
    logger.info(f"开始 hk_hold 北向持仓对账审计，目标日期: {target_date} [数据源: {data_source}]")

    hk_dir = Path(
        f"data/curated/{data_source}/market=CN/hk_hold/"
        f"year={target_date.year:04d}/month={target_date.month:02d}"
    )
    hk_files = (
        [p for p in hk_dir.glob("*.parquet") if not StorageCompat.is_artifact_path(p)]
        if hk_dir.exists()
        else []
    )
    try:
        hk_df = pl.read_parquet(hk_files) if hk_files else pl.DataFrame()
        hk_df = StorageCompat.safe_cast_date_col(hk_df, "trade_date")
        target_hk = hk_df.filter(pl.col("trade_date") == target_date)
        symbols_count = target_hk["symbol"].n_unique() if "symbol" in target_hk.columns else 0
        total_vol = (
            target_hk["vol"].sum() if "vol" in target_hk.columns and not target_hk.is_empty() else 0
        )
        total_vol_float = float(total_vol) if total_vol is not None else 0.0
    except Exception as exc:
        logger.debug(f"读取 hk_hold 对账失败: {exc}")
        symbols_count = 0
        total_vol_float = 0.0

    max_date_str = "N/A"
    try:
        base_dir = Path(f"data/curated/{data_source}/market=CN/hk_hold")
        all_hk_files = (
            [p for p in base_dir.rglob("*.parquet") if not StorageCompat.is_artifact_path(p)]
            if base_dir.exists()
            else []
        )
        if all_hk_files:
            summary_df = pl.read_parquet(all_hk_files)
            if "trade_date" in summary_df.columns:
                max_date_str = str(summary_df["trade_date"].max())[:10]
    except Exception:
        pass

    if not quiet:
        print("\n" + "=" * 65)
        print(f"       【hk_hold 北向持仓明细对账审计报告 ({target_date})】")
        print("=" * 65)
        print(f"北向资金持仓覆盖股票数 : {symbols_count:>6} 只")
        print(f"北向持股总量 (万股)    : {total_vol_float / 1e4:>10.2f} 万股")
        if symbols_count == 0 and max_date_str != "N/A":
            print(f"提示: 本地 hk_hold 自选池最新覆盖至 {max_date_str}，目标日期暂无落盘数据")
        print("=" * 65 + "\n")

    return {
        "target_date": target_date,
        "symbols_count": symbols_count,
        "total_vol": total_vol_float,
        "latest_local_date": max_date_str,
    }
