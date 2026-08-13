"""DuckDB SQL 模版与构建器模块。"""

from datetime import date


def build_read_parquet_sql(
    matched_files: list[str],
    conditions: list[str] | None = None,
    order_clause: str = "",
) -> str:
    """构建基础的 read_parquet 查询 SQL。"""
    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    return (
        f"SELECT * FROM read_parquet({matched_files}, union_by_name=true)"
        f"{where_clause}{order_clause}"
    )


def build_daily_bars_sql(
    matched_files: list[str],
    symbol: str,
    data_source: str,
    min_price: float | None = None,
) -> str:
    """构建单股票 K 线检索 SQL。"""
    sql = (
        f"SELECT * FROM read_parquet({matched_files}, union_by_name=true)"
        f" WHERE symbol = '{symbol}' AND data_source = '{data_source}'"
    )
    if min_price is not None:
        sql += f" AND close >= {min_price}"
    sql += " ORDER BY trade_date ASC"
    return sql


def build_history_sql(
    matched_files: list[str],
    data_source: str,
    start_date: date | None = None,
    end_date: date | None = None,
    symbols: list[str] | None = None,
) -> str:
    """构建面板历史数据切片 SQL。"""
    conditions = []
    if start_date:
        conditions.append(f"trade_date >= '{start_date.strftime('%Y-%m-%d')}'")
    if end_date:
        conditions.append(f"trade_date <= '{end_date.strftime('%Y-%m-%d')}'")
    if symbols:
        symbols_str = ", ".join(f"'{s}'" for s in symbols)
        conditions.append(f"symbol IN ({symbols_str})")
    conditions.append(f"data_source = '{data_source}'")

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    return (
        f"SELECT * FROM read_parquet({matched_files}, union_by_name=true)"
        f"{where_clause} ORDER BY trade_date ASC, symbol ASC"
    )


def build_snapshot_sql(matched_files: list[str], as_of_date: date | str | None = None) -> str:
    """构建选股快照查询 SQL。"""
    where_clause = ""
    if as_of_date:
        d_str = as_of_date.strftime("%Y-%m-%d") if isinstance(as_of_date, date) else as_of_date
        where_clause = f" WHERE as_of_date = '{d_str}'"
    return (
        f"SELECT * FROM read_parquet({matched_files}, union_by_name=true)"
        f"{where_clause} ORDER BY as_of_date DESC, symbol ASC"
    )
