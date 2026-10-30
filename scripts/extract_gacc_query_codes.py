"""从 good_h8_codes.csv 派生 GACC 查询码并落盘 gacc_query_codes.txt。"""

from __future__ import annotations

import sys

from stock_data.fetcher.industry.customs.parsers.gacc_catalog import (
    write_gacc_query_codes,
)


def main(argv: list[str] | None = None) -> int:
    """从主表派生 GACC 查询码，写单行逗号分隔清单到 config/data/customs。"""
    del argv
    codes = write_gacc_query_codes()
    print(f"已落盘 {len(codes)} 个 GACC 查询码 -> config/data/customs/gacc_query_codes.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
