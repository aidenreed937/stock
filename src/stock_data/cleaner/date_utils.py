"""数据清洗与标准化阶段的日期字段解析辅助函数。"""

import polars as pl


def parse_mixed_date(column: str) -> pl.Expr:
    """将紧凑、ISO、斜线、浮点格式和 ISO 时间戳日期解析为 Date。"""
    text = pl.col(column).cast(pl.Utf8, strict=False).str.strip_chars()
    stripped = text.str.replace(r"\.0+$", "")
    normalized = stripped.str.replace_all("/", "-")
    compact_digits = stripped.str.replace_all("-", "").str.slice(0, 8)
    return pl.coalesce(
        [
            normalized.str.slice(0, 10).str.to_date("%Y-%m-%d", strict=False),
            stripped.str.slice(0, 8).str.to_date("%Y%m%d", strict=False),
            compact_digits.str.to_date("%Y%m%d", strict=False),
        ]
    )
