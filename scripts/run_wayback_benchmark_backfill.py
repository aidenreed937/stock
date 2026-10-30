#!/usr/bin/env python3
"""执行基于 Wayback Machine 的半导体内存基准价格 16 个月缺口回补。

使用正式采集器 WaybackMemoryPriceBenchmarkCollector:
1. 抓取 2021-08 至 2022-11（共 16 个月）的 DRAM Spot 与 NAND Wafer 现货快照；
2. 按方案 A 采样计算月度均值，存入 RAW 目录并归档 Gzip 存证；
3. 将回补记录合并至 RAW 与 Curated 事实表；
4. 重新计算 60 个月的环比 (MoM) 与同比 (YoY)，彻底达成 5Y 滚动分位门槛。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.semiconductor.collectors.wayback_memory_benchmark import (
    DEFAULT_BACKFILL_MONTHS,
    WaybackMemoryPriceBenchmarkCollector,
)
from stock_data.fetcher.industry.semiconductor.transforms import (
    records_to_memory_benchmark_frame,
    records_to_raw_memory_benchmark_frame,
)

RAW_PARQUET_PATH = Path(
    "data/raw/industry/semiconductor/price/semiconductor_memory_benchmark.parquet"
)
CURATED_PARQUET_PATH = Path(
    "data/curated/industry/semiconductor/price/semiconductor_memory_benchmark.parquet"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Wayback 内存基准价格回补运行器")
    parser.add_argument(
        "--raw-dir",
        default="data/raw/industry",
        help="RAW 根目录路径（默认 data/raw/industry）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新下载网络快照，不使用本地已缓存的 html.gz",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="两次网络请求间隔秒数（默认 0.5s）",
    )
    parser.add_argument(
        "--start-month",
        default="2021-08",
        help="起始月份 (YYYY-MM，默认 2021-08)",
    )
    parser.add_argument(
        "--end-month",
        default="2022-11",
        help="结束月份 (YYYY-MM，默认 2022-11；若延伸至 2026 可指定 2026-08)",
    )
    parser.add_argument(
        "--dram-only",
        action="store_true",
        help="仅回补 DRAM 61050 (DDR4 16Gb)，不回补 NAND 6106（推荐在 >=2022-12 阶段启用，避免干扰官方 NAND 序列）",
    )
    args = parser.parse_args()

    if args.start_month and args.end_month:
        start_y, start_m = map(int, args.start_month.split("-"))
        end_y, end_m = map(int, args.end_month.split("-"))
        target_months = []
        cur_y, cur_m = start_y, start_m
        while (cur_y, cur_m) <= (end_y, end_m):
            target_months.append(f"{cur_y:04d}-{cur_m:02d}")
            cur_m += 1
            if cur_m > 12:
                cur_m = 1
                cur_y += 1
    else:
        target_months = list(DEFAULT_BACKFILL_MONTHS)

    products = ("DRAM",) if args.dram_only else ("DRAM", "NAND")

    print("=================================================================")
    print("  半导体存储价格基准 5Y 门槛历史回补 (Wayback Machine 方案 A)  ")
    print("=================================================================")
    print(f"RAW 目录: {args.raw_dir}")
    print(f"产品范围: {products}")
    print(f"回补月份: {target_months[0]} .. {target_months[-1]} (共 {len(target_months)} 个月)")

    collector = WaybackMemoryPriceBenchmarkCollector(
        raw_dir=args.raw_dir,
        request_delay=args.delay,
    )

    # 1. 采集回补记录
    print("\n[Step 1/3] 开始执行多点快照采样采集...")
    records = collector.collect(force=args.force, target_months=target_months, products=products)
    if not records:
        print("错误: 未采集到任何有效记录，终止回补！", file=sys.stderr)
        return 1

    print(f"-> 成功生成 {len(records)} 条基准价格记录 ({', '.join(products)})")

    # 2. 合并 RAW 表
    print("\n[Step 2/3] 合并更新 RAW 事实表...")
    new_raw_df = records_to_raw_memory_benchmark_frame(records)
    if args.dram_only:
        new_raw_df = new_raw_df.filter(pl.col("indicator_id_raw") == "61050")

    if RAW_PARQUET_PATH.exists():
        existing_raw_df = pl.read_parquet(RAW_PARQUET_PATH)
        merged_raw_df = (
            pl.concat([existing_raw_df, new_raw_df], how="diagonal_relaxed")
            .unique(subset=["report_month", "product_family", "indicator_id_raw"], keep="last")
            .sort(["product_family", "indicator_id_raw", "trade_date"])
        )
    else:
        merged_raw_df = new_raw_df

    RAW_PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged_raw_df.write_parquet(RAW_PARQUET_PATH)
    print(f"-> RAW 表已落盘: {RAW_PARQUET_PATH} (总行数: {len(merged_raw_df)})")

    # 3. 合并 Curated 表并重新计算 MoM / YoY
    print("\n[Step 3/3] 合并更新 Curated 黄金表 (重新计算 MoM / YoY 并绑定见报日)...")
    existing_curated_df = (
        pl.read_parquet(CURATED_PARQUET_PATH) if CURATED_PARQUET_PATH.exists() else None
    )

    # 利用 records_to_memory_benchmark_frame 自动对齐日历与计算 60 个月连续增长率
    curated_df = records_to_memory_benchmark_frame(records, existing_df=existing_curated_df)

    CURATED_PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
    curated_df.write_parquet(CURATED_PARQUET_PATH)
    print(f"-> Curated 表已落盘: {CURATED_PARQUET_PATH} (总行数: {len(curated_df)})")

    # 4. 验证 5Y 门槛
    print("\n=================================================================")
    print("  对账与 5Y 门槛验证报告                                         ")
    print("=================================================================")
    # 按指标 (product_family, indicator_id) 分组统计；NAND 6106 达成 60 月，
    # DRAM 61050 为 DDR4 回补单列（规格与 DataTrack 6105 不同，达成 60 月即可独立分位）。
    nand_ok = False
    for (_fam, _ind), sub in curated_df.group_by(
        ["product_family", "indicator_id"], maintain_order=True
    ):
        sub = sub.sort("trade_date")
        month_cnt = len(sub)
        first_m = str(sub["report_month"].min())
        last_m = str(sub["report_month"].max())
        srcs = sub["source"].unique().to_list()
        print(
            f"[{_fam} #{_ind}] 月份总数: {month_cnt} | 区间: {first_m} .. {last_m} | 来源: {srcs}"
        )
        if _fam == "NAND" and _ind == 6106:
            if month_cnt < 60:
                print(
                    f"  ❌ NAND 6106 未达到 5Y (60个月) 门槛！当前仅 {month_cnt} 月",
                    file=sys.stderr,
                )
                return 2
            nand_ok = True
            print("  ✓ NAND 6106 满足 5Y 滚动分位门槛 (>= 60 个月)")
        elif _fam == "DRAM" and _ind == 61050:
            print(
                f"  ✓ DRAM 61050 为 DDR4 独立序列，当前覆盖 {month_cnt} 个月 ({first_m} .. {last_m})"
            )
            if month_cnt >= 60:
                print("    -> 已达成 5Y (60个月) 滚动分位门槛！")
        elif _fam == "DRAM" and _ind == 6105:
            print("  ℹ DRAM 6105 为 DataTrack 官方序列 (DDR5 16G)，保持原 44 个月，不掺入回补数据")

    if not nand_ok:
        print("错误: NAND 6106 未达成 5Y 门槛", file=sys.stderr)
        return 2

    print("\n回补交接期连续性抽样 (2021-08 ~ 2023-02):")
    sample_df = (
        curated_df.filter(
            pl.col("report_month").is_in(
                ["2021-08", "2021-12", "2022-06", "2022-11", "2022-12", "2023-01"]
            )
        )
        .select(
            [
                "report_month",
                "product_family",
                "price_usd",
                "price_mom",
                "price_yoy",
                "release_date",
                "source",
            ]
        )
        .sort(["product_family", "report_month"])
    )
    print(sample_df)

    print("\n回补全部完成！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
