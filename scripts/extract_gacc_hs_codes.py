#!/usr/bin/env python3
"""GACC 海关 54 个有效子税号提取与导出辅助脚本。

用法:
    uv run python scripts/extract_gacc_hs_codes.py
    uv run python scripts/extract_gacc_hs_codes.py --format comma   # 打印单行逗号分隔
    uv run python scripts/extract_gacc_hs_codes.py --format lines   # 打印逐行列表
    uv run python scripts/extract_gacc_hs_codes.py --format chunks  # 按25个切分批次
    uv run python scripts/extract_gacc_hs_codes.py --format table   # 打印产业赛道对照表
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


def get_gacc_hs_codes(
    raw_csv_path: Path | str = "data/raw/industry/customs/comtrade/gacc_2025.csv",
) -> list[str]:
    """从已验证的 2025 GACC 原始快照中提取去重后的 54 个末级子税号。"""
    p = Path(raw_csv_path)
    if not p.exists():
        raise FileNotFoundError(f"未找到 GACC 原始数据文件: {p}")

    df = pd.read_csv(p, encoding="utf-8-sig")
    codes = df["商品编码"].astype(str).str.strip().str.zfill(8).unique()
    return sorted(list(codes))


def main() -> int:
    parser = argparse.ArgumentParser(description="抽取 GACC 54 个有效报关子税号")
    parser.add_argument(
        "--format",
        choices=["comma", "lines", "table", "chunks"],
        default="comma",
        help="输出格式: comma(单行逗号), lines(逐行), table(明细表), chunks(按25个切分批次)",
    )
    parser.add_argument(
        "--source",
        default="data/raw/industry/customs/comtrade/gacc_2025.csv",
        help="GACC 2025 原始文件路径",
    )
    args = parser.parse_args()

    codes = get_gacc_hs_codes(args.source)

    if args.format == "comma":
        comma_str = ",".join(codes)
        print(f"\n=== GACC 54 个有效子税号 (单行逗号分隔，共 {len(codes)} 个) ===\n")
        print(comma_str)
        print("\n")
    elif args.format == "lines":
        print(f"\n=== GACC 54 个有效子税号 (逐行列表，共 {len(codes)} 个) ===\n")
        for c in codes:
            print(c)
    elif args.format == "chunks":
        chunk_size = 25
        print(f"\n=== 按每批 {chunk_size} 个切分 (应对单次输入限制) ===\n")
        for idx, i in enumerate(range(0, len(codes), chunk_size), 1):
            chunk = codes[i : i + chunk_size]
            print(f"--- 批次 {idx} ({len(chunk)} 个) ---")
            print(",".join(chunk))
            print()
    elif args.format == "table":
        df = pd.read_csv(args.source, encoding="utf-8-sig")
        sub_df = (
            df[["商品编码", "商品名称", "第一计量单位"]]
            .drop_duplicates(subset=["商品编码"])
            .sort_values(by="商品编码")
        )
        print(f"\n=== GACC 54 个子税号明细表 (共 {len(sub_df)} 个) ===\n")
        print(sub_df.to_string(index=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
