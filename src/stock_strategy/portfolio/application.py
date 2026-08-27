"""因子组合回测应用（数据装配 + 回测 + 产物发布）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, cast

import polars as pl

from stock_analytics.pipelines.factor_portfolio import (
    DEFAULT_CONFIG_PATH as FACTOR_PORTFOLIO_CONFIG,
)
from stock_analytics.pipelines.factor_portfolio import (
    BacktestArtifactPayload,
    build_backtest_manifest,
    build_backtest_run_paths,
    load_factor_portfolio_config,
    load_latest_scores,
    write_backtest_artifacts,
)
from stock_core.exceptions import DataValidationError
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog
from stock_strategy.portfolio.backtester import run_factor_backtest
from stock_strategy.portfolio.report import BacktestMeta, build_backtest_report

_DEFAULT_BACKTEST_ROOT = "data/analytics/factor_backtest"
_DEFAULT_PORTFOLIO_ROOT = "data/analytics/factor_portfolio"

RunClass = Literal["official", "backfill", "experiment"]


@dataclass(frozen=True, slots=True)
class BacktestApplicationResult:
    """一次因子组合回测应用运行的结构化结果。"""

    as_of_date: date
    paths: Any
    manifest: dict[str, Any]
    report_markdown: str
    report_json: dict[str, Any]
    nav: pl.DataFrame


def run_backtest_application(
    *,
    config_path: Path | str = FACTOR_PORTFOLIO_CONFIG,
    output_root: Path | str | None = None,
    storage_dir: Path | str | None = None,
    portfolio_root: Path | str | None = None,
    top_n: int | None = None,
    rebalance_days: int | None = None,
    prices: pl.DataFrame | None = None,
    run_class: RunClass = "official",
    update_latest: bool = True,
) -> BacktestApplicationResult:
    """装配组合分数与价格数据，执行回测并落盘报告。

    Args:
        config_path: 因子组合 YAML 配置（提供默认调仓参数与元信息）。
        output_root: 回测产物根目录（默认 data/analytics/factor_backtest）。
        storage_dir: Curated 数据根目录（构造 DataCatalog 用）。
        portfolio_root: 组合分数产物根（默认 data/analytics/factor_portfolio）。
        top_n: 覆盖默认每期持仓数量。
        rebalance_days: 覆盖默认调仓周期（交易日）。
        prices: 预装配价格面板（trade_date/symbol/close）；传入时跳过数据加载（供测试）。
        run_class: 产物运行分类。
        update_latest: 是否刷新 latest 副本。
    """
    config = load_factor_portfolio_config(config_path)
    effective_top_n = top_n if top_n is not None else config.top_n
    effective_rebalance = rebalance_days if rebalance_days is not None else config.rebalance_days

    portfolio_root_path = Path(portfolio_root) if portfolio_root else Path(_DEFAULT_PORTFOLIO_ROOT)
    artifact_root = Path(output_root) if output_root else Path(_DEFAULT_BACKTEST_ROOT)

    source_run, scores, summary = load_latest_scores(portfolio_root_path)
    if scores.is_empty():
        raise DataValidationError(f"组合分数面板为空: {portfolio_root_path}")
    min_date = cast("date", scores["trade_date"].min())
    max_date = cast("date", scores["trade_date"].max())

    if prices is None:
        catalog = DataCatalog(data_source="tushare", storage_dir=storage_dir)
        prices = catalog.load_dataset(
            "stock_daily_bar",
            start_date=min_date,
            end_date=max_date,
            columns=["symbol", "trade_date", "close"],
        )
    if prices.is_empty():
        raise DataValidationError("回测价格数据为空（stock_daily_bar 窗口内无数据）")

    result = run_factor_backtest(
        scores,
        prices,
        top_n=effective_top_n,
        rebalance_days=effective_rebalance,
    )

    as_of_date = date.fromisoformat(str(summary["as_of_date"]))
    factor_pool = tuple(str(item["feature_id"]) for item in summary.get("factors", []))
    meta = BacktestMeta(as_of_date=as_of_date, factor_pool=factor_pool, source_run=str(source_run))
    report_markdown, report_json = build_backtest_report(
        meta,
        result,
        rebalance_days=effective_rebalance,
        top_n=effective_top_n,
        window_days=int(summary.get("window_days", config.window_days)),
        price_col=str(summary.get("price_col", config.price_col)),
    )

    paths = build_backtest_run_paths(
        as_of_date,
        artifact_root,
        run_class=run_class,
        latest_root=artifact_root,
    )
    manifest = build_backtest_manifest(
        title="因子组合回测报告",
        run_id=paths.run_dir.name,
        as_of_date=as_of_date,
        artifact_root=artifact_root,
        config_path=config_path,
        inputs={
            "rebalance_days": effective_rebalance,
            "top_n": effective_top_n,
            "factor_pool_size": len(factor_pool),
            "price_col": str(summary.get("price_col", config.price_col)),
        },
        parents={
            "factor_portfolio": {"run_dir": str(source_run)},
        },
    )
    nav_with_benchmark = result.nav.join(
        result.benchmark_nav.rename({"nav": "benchmark_nav"}),
        on="trade_date",
        how="left",
    )
    write_backtest_artifacts(
        paths,
        BacktestArtifactPayload(
            manifest=manifest,
            report_markdown=report_markdown,
            report_json=report_json,
            nav=nav_with_benchmark,
        ),
        update_latest=update_latest,
    )
    logger.info(
        "因子组合回测完成: 组合年化 {:.2%}，产物: {}",
        result.stats.get("annual_return") or 0,
        paths.run_dir,
    )
    return BacktestApplicationResult(
        as_of_date=as_of_date,
        paths=paths,
        manifest=manifest,
        report_markdown=report_markdown,
        report_json=report_json,
        nav=nav_with_benchmark,
    )


__all__ = ["BacktestApplicationResult", "run_backtest_application"]
