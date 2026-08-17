"""融资融券按交易日和交易所的覆盖完整性规则。"""

from datetime import date, datetime

import polars as pl

from stock_core.constants import EXCHANGE_START_DATES
from stock_core.utils.date import parse_mixed_date


def expected_margin_exchanges(trade_date: date) -> frozenset[str]:
    """返回指定交易日两融汇总应包含的交易所集合。"""
    starts = EXCHANGE_START_DATES.get("margin", {})
    return frozenset(
        exchange.upper()
        for exchange, start in starts.items()
        if trade_date >= date.fromisoformat(start)
    )


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _collect_exchange_groups(normalized: pl.DataFrame) -> dict[date, set[str]]:
    groups: dict[date, set[str]] = {}
    for row in normalized.select(["_margin_trade_date", "_margin_exchange_id"]).iter_rows(
        named=True
    ):
        parsed_date = _as_date(row["_margin_trade_date"])
        if parsed_date is None:
            continue
        exchange = row["_margin_exchange_id"]
        groups.setdefault(parsed_date, set()).add(
            str(exchange) if exchange is not None else "<NULL>"
        )
    return groups


def _coverage_issues(groups: dict[date, set[str]]) -> list[str]:
    issues: list[str] = []
    for parsed_date in sorted(groups):
        expected = expected_margin_exchanges(parsed_date)
        actual = groups[parsed_date]
        if actual != expected:
            issues.append(f"{parsed_date}: expected={sorted(expected)}, actual={sorted(actual)}")
    return issues


def _margin_exchange_groups(
    frame: pl.DataFrame,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[dict[date, set[str]], bool, list[str]]:
    required = {"trade_date", "exchange_id"}
    missing = sorted(required - set(frame.columns))
    if missing:
        return {}, False, [f"缺少主键列: {missing}"]
    if frame.is_empty():
        return {}, False, ["没有可用于覆盖校验的记录"]

    normalized = frame.with_columns(
        [
            parse_mixed_date("trade_date").alias("_margin_trade_date"),
            pl.col("exchange_id")
            .cast(pl.Utf8, strict=False)
            .str.strip_chars()
            .str.to_uppercase()
            .alias("_margin_exchange_id"),
        ]
    )
    invalid_dates = normalized.filter(pl.col("_margin_trade_date").is_null()).height
    if start_date is not None:
        normalized = normalized.filter(pl.col("_margin_trade_date") >= start_date)
    if end_date is not None:
        normalized = normalized.filter(pl.col("_margin_trade_date") <= end_date)
    if normalized.is_empty():
        range_issues = ["请求范围内没有可用于覆盖校验的记录"]
        if invalid_dates:
            range_issues.insert(0, f"存在 {invalid_dates} 条无法解析的 trade_date")
        return {}, False, range_issues

    groups = _collect_exchange_groups(normalized)
    issues: list[str] = []
    if invalid_dates:
        issues.append(f"存在 {invalid_dates} 条无法解析的 trade_date")
    issues.extend(_coverage_issues(groups))
    return groups, not issues, issues


def margin_coverage_issues(
    frame: pl.DataFrame,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[str]:
    """返回两融批次的交易所覆盖问题；空列表表示覆盖完整。"""
    _, _, issues = _margin_exchange_groups(frame, start_date, end_date)
    return issues


def is_margin_complete(
    frame: pl.DataFrame,
    start_date: date | None = None,
    end_date: date | None = None,
) -> bool:
    """判断两融数据在给定范围内是否按交易日完整覆盖应有交易所。"""
    _, complete, _ = _margin_exchange_groups(frame, start_date, end_date)
    return complete


def is_margin_date_complete(frame: pl.DataFrame, target_date: date) -> bool:
    """判断单个交易日是否包含该日应有的全部交易所。"""
    return is_margin_complete(frame, start_date=target_date, end_date=target_date)


def complete_margin_dates(
    frame: pl.DataFrame,
    start_date: date | None = None,
    end_date: date | None = None,
) -> set[date]:
    """返回覆盖完整的两融交易日集合。"""
    groups, _, _ = _margin_exchange_groups(frame, start_date, end_date)
    return {
        parsed_date
        for parsed_date, actual in groups.items()
        if actual == expected_margin_exchanges(parsed_date)
    }


def filter_complete_margin_dates(
    frame: pl.DataFrame,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pl.DataFrame:
    """仅保留交易所覆盖完整的两融交易日。"""
    if frame.is_empty():
        return frame
    complete_dates = complete_margin_dates(frame, start_date, end_date)
    if not complete_dates:
        return frame.head(0)
    normalized = frame.with_columns(parse_mixed_date("trade_date").alias("_margin_trade_date"))
    filtered = normalized.filter(pl.col("_margin_trade_date").is_in(list(complete_dates)))
    return filtered.drop("_margin_trade_date")
