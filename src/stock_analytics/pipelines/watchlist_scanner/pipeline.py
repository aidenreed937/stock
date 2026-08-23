"""自选池批量量化雷达执行管线。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from stock_analytics.pipelines.stock_diagnostics import run_stock_diagnostics
from stock_analytics.pipelines.watchlist_scanner.types import (
    WatchlistItemSummary,
    WatchlistScanResult,
)
from stock_core.utils.logger import logger


def _load_watchlist_stock_symbols(config_path: Path | str | None = None) -> list[str]:
    """从 watchlist.yaml 中读取 A 股核心自选股票代码列表。"""
    path = Path(config_path or "config/universe/watchlist.yaml")
    if not path.exists():
        logger.warning(f"未找到自选池配置文件: {path}")
        return ["600519.SH", "000001.SZ", "300750.SZ"]

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        stocks = data.get("universe", {}).get("a_shares", {}).get("stocks", [])
        symbols = [str(s.get("code")) for s in stocks if s.get("code")]
        return symbols if symbols else ["600519.SH", "000001.SZ", "300750.SZ"]
    except Exception as exc:
        logger.warning(f"解析 watchlist.yaml 失败: {exc}")
        return ["600519.SH", "000001.SZ", "300750.SZ"]


def run_watchlist_scanner(
    target_date: date | None = None,
    config_path: Path | str | None = None,
    storage_dir: Path | str | None = None,
    symbols: list[str] | None = None,
) -> WatchlistScanResult:
    """执行自选池全量扫描并生成多维特征排序雷达。"""
    target_symbols = symbols or _load_watchlist_stock_symbols(config_path)
    summaries: list[WatchlistItemSummary] = []
    as_of_date_val = str(target_date or date.today().isoformat())

    for sym in target_symbols:
        try:
            diag = run_stock_diagnostics(
                symbol=sym,
                target_date=target_date,
                storage_dir=storage_dir,
            )
            as_of_date_val = diag.as_of_date

            tags: list[str] = []
            if (
                diag.valuation.pe_percentile_5y is not None
                and diag.valuation.pe_percentile_5y <= 15.0
                and not diag.valuation.value_trap_warning
            ):
                tags.append("极低估值")

            if (
                diag.valuation.dividend_spread_10y is not None
                and diag.valuation.dividend_spread_10y >= 2.0
            ):
                tags.append("高股息利差")

            if diag.valuation.value_trap_warning:
                tags.append("⚠️价值陷阱")

            if "多头" in diag.technicals.trend_description:
                tags.append("多头排列")

            summaries.append(
                WatchlistItemSummary(
                    symbol=diag.symbol,
                    name=diag.name,
                    industry=diag.industry,
                    close=diag.technicals.close,
                    pct_chg=diag.technicals.pct_chg,
                    pe_ttm=diag.valuation.pe_ttm,
                    pe_percentile_5y=diag.valuation.pe_percentile_5y,
                    pb=diag.valuation.pb,
                    dv_ttm=diag.valuation.dv_ttm,
                    dividend_spread_10y=diag.valuation.dividend_spread_10y,
                    roe=diag.financials.roe,
                    trend_description=diag.technicals.trend_description,
                    value_trap_warning=diag.valuation.value_trap_warning,
                    screen_status=diag.screen.status,
                    tags=tags,
                )
            )
        except Exception as exc:
            logger.warning(f"扫描自选标的 {sym} 失败: {exc}")

    # 分类聚类
    golden_pits = [
        item
        for item in summaries
        if item.pe_percentile_5y is not None
        and item.pe_percentile_5y <= 15.0
        and not item.value_trap_warning
    ]
    high_dv = [
        item
        for item in summaries
        if item.dividend_spread_10y is not None and item.dividend_spread_10y >= 2.0
    ]
    traps = [item for item in summaries if item.value_trap_warning]

    return WatchlistScanResult(
        as_of_date=as_of_date_val,
        total_scanned=len(summaries),
        items=summaries,
        golden_pit_candidates=golden_pits,
        high_dividend_candidates=high_dv,
        value_trap_candidates=traps,
    )
