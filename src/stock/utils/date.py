"""日期字段解析辅助函数。"""

import polars as pl


def parse_mixed_date(column: str) -> pl.Expr:
    """将紧凑、ISO、斜线和 ISO 时间戳日期解析为 Date。"""
    text = pl.col(column).cast(pl.Utf8, strict=False).str.strip_chars()
    normalized = text.str.replace_all("/", "-")
    return pl.coalesce(
        [
            normalized.str.slice(0, 10).str.to_date("%Y-%m-%d", strict=False),
            text.str.to_date("%Y%m%d", strict=False),
        ]
    )
