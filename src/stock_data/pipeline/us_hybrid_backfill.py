"""美股双源历史回填：先补 yfinance，再以 Alpha Vantage 最小次数兜底。"""

from __future__ import annotations

from datetime import date
from typing import Any

import exchange_calendars as xcals

from stock_core.exceptions import DataFetchError
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog
from stock_data.pipeline.backfill_runner import BackfillRequest, run_backfill

US_HYBRID_SOURCE = "us_hybrid"
_PRIMARY_SOURCE = "yfinance"
_FALLBACK_SOURCE = "alphavantage"
_DAILY_COMPACT_SESSIONS = 100


def _resolve_symbols(symbol: str | None, data_cfg: Any) -> list[str]:
    requested = (symbol or "watchlist").strip()
    if requested not in {"", "all", "watchlist"}:
        return list(dict.fromkeys(item.strip() for item in requested.split(",") if item.strip()))

    watchlist = getattr(getattr(data_cfg, "watchlists", None), "yfinance", None)
    symbols = list(getattr(watchlist, "stocks", []) or []) if watchlist is not None else []
    if not symbols:
        raise DataFetchError("美股混合回填缺少 yfinance 股票观察池")
    return list(dict.fromkeys(str(item).strip() for item in symbols if str(item).strip()))


def _sessions(start_date: date, end_date: date) -> list[date]:
    calendar = xcals.get_calendar("XNYS")
    return [
        session.date()
        for session in calendar.sessions_in_range(start_date.isoformat(), end_date.isoformat())
    ]


def _coverage(
    data_source: str,
    symbols: list[str],
    start_date: date,
    end_date: date,
) -> dict[str, set[date]]:
    covered: dict[str, set[date]] = {symbol: set() for symbol in symbols}
    try:
        frame = DataCatalog(data_source=data_source).load_dataset(
            "stock_daily_bar",
            start_date=start_date,
            end_date=end_date,
            market="US",
            symbols=symbols,
            columns=["symbol", "trade_date"],
        )
    except FileNotFoundError:
        return covered
    if frame.is_empty() or not {"symbol", "trade_date"}.issubset(frame.columns):
        return covered

    for row in frame.iter_rows(named=True):
        symbol = str(row["symbol"])
        value = row["trade_date"]
        if symbol not in covered or not isinstance(value, date):
            continue
        covered[symbol].add(value)
    return covered


def _missing_by_symbol(
    expected_sessions: list[date], coverage: dict[str, set[date]], symbols: list[str]
) -> dict[str, set[date]]:
    expected = set(expected_sessions)
    return {symbol: expected - coverage.get(symbol, set()) for symbol in symbols}


def _summary(
    *,
    start_date: date,
    end_date: date,
    symbols: list[str],
    alpha_requests: int,
    missing_before_alpha: int,
    missing_after_alpha: int,
    primary_failed_days: int,
    primary_failed_symbols: list[str],
) -> dict[str, Any]:
    return {
        "data_source": US_HYBRID_SOURCE,
        "endpoint": "stock_daily_bar",
        "symbol": ",".join(symbols),
        "total_days": (end_date - start_date).days + 1,
        "open_days": 0,
        "synced_days": 0,
        "skipped_days": 0,
        "failed_days": 1 if missing_after_alpha else 0,
        "alpha_requests": alpha_requests,
        "missing_before_alpha": missing_before_alpha,
        "missing_after_alpha": missing_after_alpha,
        "primary_source": _PRIMARY_SOURCE,
        "primary_failed_days": primary_failed_days,
        "primary_failed_symbols": ",".join(primary_failed_symbols),
    }


def run_us_hybrid_backfill(
    *,
    symbol: str | None,
    start_date: date,
    end_date: date,
    data_cfg: Any,
    force_refresh: bool = False,
    max_workers: int = 1,
) -> list[dict[str, Any]]:
    """先执行 yfinance 缺口回填，再按标的一次请求 Alpha Vantage 兜底。"""
    if end_date < start_date:
        raise ValueError("美股混合回填的结束日期不能早于开始日期")

    symbols = _resolve_symbols(symbol, data_cfg)
    expected_sessions = _sessions(start_date, end_date)
    if not expected_sessions:
        raise DataFetchError(f"XNYS 在区间 [{start_date} ~ {end_date}] 没有交易日")

    primary_coverage = _coverage(_PRIMARY_SOURCE, symbols, start_date, end_date)
    fallback_coverage = _coverage(_FALLBACK_SOURCE, symbols, start_date, end_date)
    initial_coverage = {
        item: primary_coverage.get(item, set()) | fallback_coverage.get(item, set())
        for item in symbols
    }
    initial_missing = _missing_by_symbol(expected_sessions, initial_coverage, symbols)
    initial_missing_count = sum(len(values) for values in initial_missing.values())
    primary_symbols = [item for item in symbols if initial_missing.get(item)]
    primary_summaries: list[dict[str, Any]] = []

    if force_refresh or primary_symbols:
        requested_primary_symbols = symbols if force_refresh else primary_symbols
        logger.info(
            f"[us_hybrid] 先回填 yfinance：标的={len(symbols)}，"
            f"初始综合缺口={initial_missing_count} 个交易日记录"
        )
        try:
            primary_summaries.extend(
                run_backfill(
                    BackfillRequest(
                        data_source=_PRIMARY_SOURCE,
                        endpoint="stock_daily_bar",
                        symbol=",".join(requested_primary_symbols),
                        start_date=start_date,
                        end_date=end_date,
                        force_refresh=force_refresh,
                        max_workers=max_workers,
                    ),
                    data_cfg=data_cfg,
                )
            )
        except Exception as exc:
            primary_summaries = [
                {"symbol": item, "failed_days": 1} for item in requested_primary_symbols
            ]
            logger.warning("[us_hybrid] yfinance 回填异常，继续计算 Alpha 缺口: %s", exc)
    else:
        logger.info("[us_hybrid] 请求区间已由现有 Provider 覆盖，跳过 yfinance 与 Alpha 请求")

    primary_coverage = _coverage(_PRIMARY_SOURCE, symbols, start_date, end_date)
    fallback_coverage = _coverage(_FALLBACK_SOURCE, symbols, start_date, end_date)
    combined_coverage = {
        item: primary_coverage.get(item, set()) | fallback_coverage.get(item, set())
        for item in symbols
    }
    missing = _missing_by_symbol(expected_sessions, combined_coverage, symbols)
    missing_before_alpha = sum(len(values) for values in missing.values())

    compact_sessions = expected_sessions[-_DAILY_COMPACT_SESSIONS:]
    compact_start = compact_sessions[0]
    alpha_symbols = [item for item in symbols if missing.get(item, set()) & set(compact_sessions)]
    alpha_requests = len(alpha_symbols)
    primary_failed_days = sum(
        int(item.get("failed_days", 0))
        for item in primary_summaries
        if isinstance(item.get("failed_days", 0), int | float)
    )
    primary_failed_symbols = [
        str(item.get("symbol"))
        for item in primary_summaries
        if isinstance(item.get("failed_days", 0), int | float)
        and item.get("failed_days", 0) > 0
        and item.get("symbol")
    ]
    primary_failed_symbols = list(dict.fromkeys(primary_failed_symbols))
    alpha_summaries: list[dict[str, Any]] = []
    if alpha_symbols:
        logger.info(
            f"[us_hybrid] Alpha Vantage 兜底：每个缺口标的一次请求，"
            f"标的={alpha_requests}，窗口={compact_start} ~ {end_date}"
        )
        try:
            alpha_summaries.extend(
                run_backfill(
                    BackfillRequest(
                        data_source=_FALLBACK_SOURCE,
                        endpoint="stock_daily_bar",
                        symbol=",".join(alpha_symbols),
                        start_date=compact_start,
                        end_date=end_date,
                        force_refresh=False,
                        max_workers=1,
                    ),
                    data_cfg=data_cfg,
                )
            )
        except Exception as exc:
            logger.warning("[us_hybrid] Alpha Vantage 兜底回填异常: %s", exc)
    else:
        logger.info("[us_hybrid] 没有需要 Alpha Vantage 兜底的近期缺口，跳过请求")

    primary_coverage = _coverage(_PRIMARY_SOURCE, symbols, start_date, end_date)
    fallback_coverage = _coverage(_FALLBACK_SOURCE, symbols, start_date, end_date)
    final_coverage = {
        item: primary_coverage.get(item, set()) | fallback_coverage.get(item, set())
        for item in symbols
    }
    missing_after_alpha = sum(
        len(values)
        for values in _missing_by_symbol(expected_sessions, final_coverage, symbols).values()
    )
    summaries = alpha_summaries
    summaries.append(
        _summary(
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            alpha_requests=alpha_requests,
            missing_before_alpha=missing_before_alpha,
            missing_after_alpha=missing_after_alpha,
            primary_failed_days=primary_failed_days,
            primary_failed_symbols=primary_failed_symbols,
        )
    )
    if missing_after_alpha:
        logger.warning(
            "[us_hybrid] 仍有 %d 个交易日记录缺失；Alpha Vantage 免费 compact 仅覆盖最近 %d 个交易日",
            missing_after_alpha,
            _DAILY_COMPACT_SESSIONS,
        )
    return summaries


__all__ = ["US_HYBRID_SOURCE", "run_us_hybrid_backfill"]
