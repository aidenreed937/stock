"""因子组合分数管线编排。

对评估窗口内的注册 STOCK 宽表因子，按因子准入报告（``factor_research``）通过
的因子子集执行横截面标准化（z-score，direction 对齐）与等权合成，输出每日
组合分数面板（``trade_date x symbol x composite_score``）与组合说明产物，
供策略层回测器（stock_strategy）消费（未复权价格口径标注见组合说明）。

数据装配：以 ``stock_daily_bar`` 为主数据集（fail-closed），``daily_basic`` 与
``moneyflow`` 为可选增强（缺失时因子列自然为空，不阻塞合成）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.catalog_compat import load_dataset_compat
from stock_analytics.features.builtin_factor_specs import FACTOR_ENGINE_SPECS
from stock_analytics.features.factors import FactorEngine
from stock_analytics.pipelines._shared.panel import (
    BAR_COLUMNS,
    BASIC_COLUMNS,
    FLOW_COLUMNS,
    assemble_panel,
    load_optional_dataset,
)
from stock_analytics.pipelines.artifacts import (
    ArtifactUnavailableError,
    RunClass,
    build_manifest_base,
    resolve_artifact_run,
)
from stock_analytics.pipelines.factor_portfolio.artifacts import (
    FactorPortfolioArtifactPayload,
    FactorPortfolioRunPaths,
    build_run_paths,
    write_artifacts,
)
from stock_analytics.pipelines.factor_portfolio.config import (
    DEFAULT_CONFIG_PATH,
    FactorPortfolioConfig,
    load_factor_portfolio_config,
)
from stock_analytics.primitives import cross_sectional_zscore
from stock_core.exceptions import DataValidationError
from stock_core.utils.logger import logger

_REPORT_FILENAME = "factor_research.json"


@dataclass(frozen=True, slots=True)
class FactorPortfolioRunResult:
    """一次因子组合分数运行的结果。"""

    as_of_date: date
    paths: FactorPortfolioRunPaths
    manifest: dict[str, Any]
    summary: dict[str, Any]
    scores: pl.DataFrame


@dataclass(frozen=True, slots=True)
class _FactorSource:
    """准入因子池及其来源定位。"""

    research_root: Path
    run_dir: Path
    factor_ids: tuple[str, ...]


def _resolve_research_root(config: FactorPortfolioConfig) -> Path:
    """确定因子准入报告产物根：显式配置优先，否则取产物根相邻的 factor_research。"""
    if config.factor_research_dir:
        return Path(config.factor_research_dir)
    return Path(config.artifact_root).parent / "factor_research"


def _load_factor_source(
    config: FactorPortfolioConfig, wide_columns: Sequence[str]
) -> _FactorSource:
    """读取准入因子池：白名单显式覆盖，否则取准入报告 pass 因子（fail-closed）。"""
    if config.factor_whitelist:
        pool = tuple(fid for fid in config.factor_whitelist if fid in wide_columns)
        if not pool:
            raise DataValidationError("因子白名单均为引擎未产出列，无法合成组合分数")
        research_root = _resolve_research_root(config)
        return _FactorSource(research_root=research_root, run_dir=research_root, factor_ids=pool)

    research_root = _resolve_research_root(config)
    try:
        run = resolve_artifact_run(research_root, expected_artifact_type="factor_research")
        report = run.read_json(_REPORT_FILENAME)
    except ArtifactUnavailableError as exc:
        raise DataValidationError(
            f"无法读取因子准入报告（{research_root}）："
            f"请先运行 factor-research 或指定 factor_research_dir（{exc}）"
        ) from exc
    factors = report.get("factors")
    if not isinstance(factors, list) or not factors:
        raise DataValidationError(f"因子准入报告缺少 factors 列表: {run.run_dir}")
    pass_ids = tuple(
        str(factor["feature_id"]) for factor in factors if factor.get("verdict") == "pass"
    )
    pool = tuple(fid for fid in pass_ids if fid in wide_columns)
    if not pool:
        raise DataValidationError(
            "因子准入报告无通过因子（或通过因子均不在引擎产出列中），组合分数为空"
        )
    return _FactorSource(research_root=research_root, run_dir=run.run_dir, factor_ids=pool)


def _direction_map(factor_ids: Sequence[str]) -> dict[str, str]:
    """取自注册 spec 的因子方向（未注册列默认 positive）。"""
    spec_by_id = {spec.feature_id: spec.direction for spec in FACTOR_ENGINE_SPECS}
    return {fid: spec_by_id.get(fid, "positive") for fid in factor_ids}


def _compute_composite_scores(
    wide: pl.DataFrame,
    factor_ids: Sequence[str],
    direction_map: Mapping[str, str],
    min_valid_factors: int,
) -> pl.DataFrame:
    """对因子列做方向对齐的截面 z-score 等权合成，输出每日组合分数面板。

    截面标准化按交易日分组独立进行（``group_by="trade_date"``），避免跨日混算
    引入未来信息；当日有效因子少于 ``min_valid_factors`` 时该日分数为缺失。
    """
    zdf = cross_sectional_zscore(
        wide.select(["trade_date", "symbol", *factor_ids]),
        list(factor_ids),
        group_by="trade_date",
    )
    zcols = [f"{fid}_cs_zscore" for fid in factor_ids]
    for fid in factor_ids:
        sign = -1.0 if direction_map.get(fid, "positive") == "negative" else 1.0
        zdf = zdf.with_columns((pl.col(f"{fid}_cs_zscore") * sign).alias(f"{fid}_cs_zscore"))
    valid_count = sum(pl.col(col).is_not_null() for col in zcols)
    composite = (
        pl.when(valid_count >= min_valid_factors)
        .then(pl.mean_horizontal(zcols))
        .otherwise(None)
        .alias("composite_score")
    )
    return (
        zdf.with_columns(composite)
        .select("trade_date", "symbol", "composite_score")
        .sort(["trade_date", "symbol"])
    )


def run_factor_portfolio(
    *,
    end_date: date | None = None,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    output_root: Path | str | None = None,
    storage_dir: Path | str | None = None,
    catalog: Any | None = None,
    panel: pl.DataFrame | None = None,
    research_dir: Path | str | None = None,
    run_class: RunClass = "official",
    update_latest: bool = True,
) -> FactorPortfolioRunResult:
    """运行因子组合分数合成并落盘产物。

    Args:
        end_date: 组合窗口截止日（默认今天）。
        config_path: 组合配置 YAML 路径。
        output_root: 覆盖产物根目录。
        storage_dir: Curated 数据根目录（构造 DataCatalog 用）。
        catalog: DataCatalog 实例；与 ``panel`` 二选一（测试注入）。
        panel: 预装配的完整基础列面板；传入时跳过数据加载（供测试）。
        research_dir: 覆盖因子准入报告产物根（CLI --factor-research-dir）。
        run_class: 产物运行分类。
        update_latest: 是否刷新 latest 副本。
    """
    config = load_factor_portfolio_config(config_path).with_artifact_root(output_root)
    if research_dir is not None:
        config = replace(config, factor_research_dir=str(Path(research_dir)))
    as_of_date = end_date or date.today()
    window_start = as_of_date - timedelta(days=config.window_days)

    if panel is None:
        if catalog is None:
            from stock_data.catalog import DataCatalog

            catalog = DataCatalog(data_source="tushare", storage_dir=storage_dir)
        bar = load_dataset_compat(
            catalog,
            "stock_daily_bar",
            start_date=window_start,
            end_date=as_of_date,
            columns=list(BAR_COLUMNS),
        )
        basic = load_optional_dataset(
            catalog, "daily_basic", BASIC_COLUMNS, window_start, as_of_date
        )
        flow = load_optional_dataset(catalog, "moneyflow", FLOW_COLUMNS, window_start, as_of_date)
        panel = assemble_panel(bar, basic, flow)

    trade_days = panel.select(pl.col("trade_date").n_unique()).item()
    if trade_days < config.min_trade_days:
        raise DataValidationError(
            f"组合窗口可回溯交易日不足（{trade_days} < {config.min_trade_days}），无法合成组合分数"
        )

    wide = FactorEngine.compute_all_factors(panel, price_col=config.price_col, normalize=False)
    source = _load_factor_source(config, wide.columns)
    direction_map = _direction_map(source.factor_ids)
    scores = _compute_composite_scores(
        wide, source.factor_ids, direction_map, config.min_valid_factors
    )

    weight = 1.0 / len(source.factor_ids)
    summary = {
        "as_of_date": as_of_date.isoformat(),
        "window_start": window_start.isoformat(),
        "window_days": config.window_days,
        "horizons": (config.rebalance_days,),
        "rebalance_days": config.rebalance_days,
        "top_n": config.top_n,
        "min_valid_factors": config.min_valid_factors,
        "price_col": config.price_col,
        "factor_research_dir": str(source.research_root),
        "factor_research_run": str(source.run_dir),
        "factor_pool_size": len(source.factor_ids),
        "factors": [
            {"feature_id": fid, "direction": direction_map[fid], "weight": weight}
            for fid in source.factor_ids
        ],
        "score_rows": scores.height,
        "data_note": "组合分数基于未复权收盘价计算；除权日可能失真，结论仅供研究参考。",
    }

    paths = build_run_paths(
        as_of_date,
        config.artifact_root,
        run_class=run_class,
        latest_root=config.artifact_root,
    )
    manifest = build_manifest_base(
        artifact_type="factor_portfolio",
        schema_version=config.schema_version,
        title=config.title,
        run_id=paths.run_dir.name,
        as_of_date=as_of_date,
        artifact_root=config.artifact_root,
        config_path=config_path,
        inputs={
            "window_start": window_start.isoformat(),
            "window_days": config.window_days,
            "price_col": config.price_col,
            "rebalance_days": config.rebalance_days,
            "top_n": config.top_n,
            "factor_pool_size": len(source.factor_ids),
        },
        parents={
            "factor_research": {
                "root": str(source.research_root),
                "run_dir": str(source.run_dir),
            }
        },
    )
    write_artifacts(
        paths,
        FactorPortfolioArtifactPayload(manifest=manifest, scores=scores, summary=summary),
        update_latest=update_latest,
    )
    logger.info(
        "因子组合分数完成: {} 个因子，{} 行分数，产物: {}",
        len(source.factor_ids),
        scores.height,
        paths.run_dir,
    )
    return FactorPortfolioRunResult(
        as_of_date=as_of_date,
        paths=paths,
        manifest=manifest,
        summary=summary,
        scores=scores,
    )


__all__ = ["FactorPortfolioRunResult", "run_factor_portfolio"]
