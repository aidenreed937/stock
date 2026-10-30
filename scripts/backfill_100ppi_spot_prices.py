#!/usr/bin/env python3
"""生意社 100ppi 现货出厂基准价批量回填与物化脚本。

获取轻质纯碱、重质纯碱、尿素、动力煤等 11 大核心化工大宗商品连续日度出厂基准价，
落盘 RAW JSON 快照并物化 Curated 黄金事实表 data/curated/industry/chemical_spot_price.parquet。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import polars as pl

# 将 src 加入模块搜索路径
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = WORKSPACE_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from stock_data.fetcher.industry.chemicals.collectors.spot_price import (  # noqa: E402
    COMMODITY_CATALOG,
    ChemicalSpotPriceCollector,
)


def run_backfill(
    raw_dir: Path | str,
    curated_dir: Path | str | None = None,
    symbols: list[str] | None = None,
    use_network: bool = True,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """执行 100ppi 现货价格批量回填。"""
    collector = ChemicalSpotPriceCollector(raw_dir=raw_dir, curated_dir=curated_dir)
    target_symbols = symbols or list(COMMODITY_CATALOG.keys())

    print(f"[*] 开始回填 100ppi 现货出厂基准价，共 {len(target_symbols)} 个品种...")
    print(f"[*] 网络模式: {'在线采集 (agent-browser)' if use_network else '离线回放'}")

    records_dict = collector.collect_all(symbols=target_symbols, use_network=use_network)
    curated_df = collector.materialize_curated(records_dict)

    summary: dict[str, Any] = {}
    for sym, recs in records_dict.items():
        meta = COMMODITY_CATALOG.get(sym, {})
        if recs:
            summary[sym] = {
                "product_name": meta.get("product_name", sym),
                "count": len(recs),
                "start_date": recs[0].trade_date.isoformat(),
                "end_date": recs[-1].trade_date.isoformat(),
                "latest_price": recs[-1].spot_price_cny,
                "unit": meta.get("unit", "元/吨"),
                "status": "SUCCESS",
            }
        else:
            summary[sym] = {
                "product_name": meta.get("product_name", sym),
                "count": 0,
                "status": "EMPTY_OR_FAILED",
            }

    return curated_df, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="生意社 100ppi 现货出厂基准价回填")
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=WORKSPACE_ROOT / "data" / "raw" / "industry",
        help="RAW 根目录",
    )
    parser.add_argument(
        "--curated-dir",
        type=Path,
        default=WORKSPACE_ROOT / "data" / "curated" / "industry",
        help="Curated 根目录",
    )
    parser.add_argument(
        "--symbol",
        action="append",
        dest="symbols",
        help="指定回填的品种 (默认全量 11 个品种)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="离线模式：仅从本地 RAW 快照重建 Curated",
    )
    args = parser.parse_args()

    use_network = not args.offline
    curated_df, summary = run_backfill(
        raw_dir=args.raw_dir,
        curated_dir=args.curated_dir,
        symbols=args.symbols,
        use_network=use_network,
    )

    print("\n" + "=" * 80)
    print(" 100ppi 现货出厂基准价回填汇总报告")
    print("=" * 80)
    print(
        f"{'Symbol':<10} | {'品名':<10} | {'点数':<6} | {'起始日期':<12} | {'最新日期':<12} | {'最新价格':<10} | {'单位':<8} | {'状态'}"
    )
    print("-" * 80)
    for sym, s in summary.items():
        if s.get("status") == "SUCCESS":
            print(
                f"{sym:<10} | {s['product_name']:<10} | {s['count']:<6} | {s['start_date']:<12} | {s['end_date']:<12} | {s['latest_price']:<10.2f} | {s['unit']:<8} | OK"
            )
        else:
            print(
                f"{sym:<10} | {s.get('product_name', ''):<10} | 0      | -            | -            | -          | -        | FAILED"
            )

    print("-" * 80)
    curated_file = args.curated_dir / "chemical_spot_price.parquet"
    print(f"Curated 物化路径: {curated_file} (共 {len(curated_df)} 行)")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
