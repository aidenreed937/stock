"""因子准入评估管线编排。

对评估窗口内的注册 STOCK 宽表因子执行质量检验：Rank IC / ICIR / t 统计量 /
分层单调性 / 多空价差，并按配置阈值给出准入结论（pass / fail / insufficient），
产出 markdown + json 报告（未复权价格口径标注见报告说明）。

数据装配：以 ``stock_daily_bar`` 为主数据集（fail-closed），``daily_basic`` 与
``moneyflow`` 为可选增强（缺失时因子列自然为空，不阻塞评估）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
from stock_analytics.pipelines.artifacts import RunClass, build_manifest_base
from stock_analytics.pipelines.factor_research.artifacts import (
    FactorResearchArtifactPayload,
    FactorResearchRunPaths,
    build_run_paths,
    write_artifacts,
)
from stock_analytics.pipelines.factor_research.config import (
    DEFAULT_CONFIG_PATH,
    FactorResearchConfig,
    load_factor_research_config,
)
from stock_analytics.pipelines.factor_research.report import build_report
from stock_analytics.primitives.factor_evaluation import (
    add_forward_returns,
    ic_summary,
    rank_ic_series,
)
from stock_analytics.primitives.factor_quantile import (
    quantile_forward_returns,
    quantile_summary,
)
from stock_core.exceptions import DataValidationError
from stock_core.utils.logger import logger


@dataclass(frozen=True, slots=True)
class FactorResearchRunResult:
    """一次因子准入评估运行结果。"""

    as_of_date: date
    paths: FactorResearchRunPaths
    manifest: dict[str, Any]
    report_markdown: str
    report_json: dict[str, Any]


def _select_factor_pool(config: FactorResearchConfig, wide_columns: Sequence[str]) -> list[str]:
    """按 D4 规则筛选可评估因子池（白名单覆盖规则；其余由 spec 单位/方向驱动）。"""
    if config.factor_whitelist:
        return [fid for fid in config.factor_whitelist if fid in wide_columns]
    allowed = set(config.allowed_units)
    pool = [
        spec.feature_id
        for spec in FACTOR_ENGINE_SPECS
        if spec.unit.value in allowed and spec.direction != "neutral"
    ]
    return [fid for fid in pool if fid in wide_columns]


def _field(row: pl.DataFrame, column: str) -> float | None:
    """取统计表单行单列标量；缺失/空返回 None。"""
    if row.is_empty() or column not in row.columns:
        return None
    value = row[0, column]
    return None if value is None else float(value)


def _evaluate_factor(
    wide: pl.DataFrame,
    feature_id: str,
    spec_map: Mapping[str, Any],
    config: FactorResearchConfig,
) -> dict[str, Any]:
    """对单个因子执行 IC 与分层评估并给出准入结论。"""
    forward_cols = [f"fwd_ret_{h}d" for h in config.horizons]
    ic_long = rank_ic_series(wide, feature_id, forward_cols)
    stats = ic_summary(ic_long)

    decision = f"fwd_ret_{config.decision_horizon}d"
    decision_row = stats.filter(pl.col("horizon") == decision)
    n_days = int(_field(decision_row, "n_days") or 0)
    icir = _field(decision_row, "icir")
    t_stat = _field(decision_row, "t_stat")
    ic_mean = _field(decision_row, "ic_mean")

    horizon_stats: dict[str, dict[str, float | None]] = {}
    for horizon in config.horizons:
        row = stats.filter(pl.col("horizon") == f"fwd_ret_{horizon}d")
        horizon_stats[str(horizon)] = {
            "n_days": _field(row, "n_days"),
            "ic_mean": _field(row, "ic_mean"),
            "ic_std": _field(row, "ic_std"),
            "icir": _field(row, "icir"),
            "t_stat": _field(row, "t_stat"),
            "ic_positive_ratio": _field(row, "ic_positive_ratio"),
        }

    quantile: dict[str, Any] = {}
    quantile_horizon = f"fwd_ret_{config.quantile_horizon}d"
    if quantile_horizon in wide.columns and config.n_bins > 1:
        panel = quantile_forward_returns(wide, feature_id, quantile_horizon, n_bins=config.n_bins)
        quantile = quantile_summary(panel, config.n_bins)

    direction = spec_map.get(feature_id, {}).get("direction", "neutral")
    direction_sign = -1.0 if direction == "negative" else 1.0
    long_short_mean = float(quantile.get("long_short_mean") or 0.0)
    monotonicity = quantile.get("monotonicity_spearman")
    thresholds = config.thresholds

    reasons: list[str] = []
    verdict = "pass"
    if n_days < config.min_ic_days:
        verdict = "insufficient"
        reasons.append(f"有效IC天数不足（{n_days} < {config.min_ic_days}）")
    else:
        if icir is None or abs(icir) < thresholds.icir:
            verdict = "fail"
            reasons.append(f"ICIR 不足（{icir} < {thresholds.icir}）")
        if t_stat is None or abs(t_stat) < thresholds.t_stat:
            verdict = "fail"
            reasons.append(f"t 统计量不足（{t_stat} < {thresholds.t_stat}）")
        if long_short_mean * direction_sign < thresholds.long_short_mean:
            verdict = "fail"
            reasons.append(f"多空价差方向不符（{long_short_mean:+.3f}，direction={direction}）")
        if verdict == "pass" and ic_mean is not None and direction != "neutral":
            if (direction == "positive" and ic_mean < 0) or (
                direction == "negative" and ic_mean > 0
            ):
                verdict = "fail"
                reasons.append(f"IC 符号与 direction 冲突（IC均值={ic_mean:+.4f}）")

    return {
        "feature_id": feature_id,
        "unit": spec_map.get(feature_id, {}).get("unit", "unknown"),
        "direction": direction,
        "n_days": n_days,
        "icir": icir,
        "t_stat": t_stat,
        "ic_mean": ic_mean,
        "long_short_mean": long_short_mean,
        "monotonicity_spearman": monotonicity,
        "horizon_stats": horizon_stats,
        "verdict": verdict,
        "reasons": reasons,
    }


def run_factor_research(
    *,
    end_date: date | None = None,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    output_root: Path | str | None = None,
    storage_dir: Path | str | None = None,
    catalog: Any | None = None,
    panel: pl.DataFrame | None = None,
    run_class: RunClass = "official",
    update_latest: bool = True,
) -> FactorResearchRunResult:
    """运行因子准入评估并落盘报告。

    Args:
        end_date: 评估窗口截止日（默认今天）。
        config_path: 评估配置 YAML 路径。
        output_root: 覆盖产物根目录。
        storage_dir: Curated 数据根目录（构造 DataCatalog 用）。
        catalog: DataCatalog 实例；与 ``panel`` 二选一（测试注入）。
        panel: 预装配的完整基础列面板；传入时跳过数据加载（供测试）。
        run_class: 产物运行分类。
        update_latest: 是否刷新 latest 副本。
    """
    config = load_factor_research_config(config_path).with_artifact_root(output_root)
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

    wide = FactorEngine.compute_all_factors(panel, price_col=config.price_col, normalize=False)
    factor_cols = _select_factor_pool(config, wide.columns)
    if not factor_cols:
        raise DataValidationError("评估窗口内无可用因子（因子池为空，请检查配置与引擎产出）")

    spec_by_id = {
        spec.feature_id: {"unit": spec.unit.value, "direction": spec.direction}
        for spec in FACTOR_ENGINE_SPECS
    }
    wide = add_forward_returns(wide, config.horizons, price_col=config.price_col)
    factors = [_evaluate_factor(wide, fid, spec_by_id, config) for fid in factor_cols]

    report_markdown, report_json = build_report(config, as_of_date, window_start, factors)

    paths = build_run_paths(
        as_of_date,
        config.artifact_root,
        run_class=run_class,
        latest_root=config.artifact_root,
    )
    manifest = build_manifest_base(
        artifact_type="factor_research",
        schema_version=config.schema_version,
        title=config.title,
        run_id=paths.run_dir.name,
        as_of_date=as_of_date,
        artifact_root=config.artifact_root,
        config_path=config_path,
        inputs={
            "window_start": window_start.isoformat(),
            "window_days": config.window_days,
            "horizons": list(config.horizons),
            "decision_horizon": config.decision_horizon,
            "price_col": config.price_col,
            "factor_pool_size": len(factors),
        },
    )
    write_artifacts(
        paths,
        FactorResearchArtifactPayload(
            manifest=manifest,
            report_markdown=report_markdown,
            report_json=report_json,
        ),
        update_latest=update_latest,
    )
    logger.info("因子准入评估完成: {} 个因子，产物: {}", len(factors), paths.run_dir)
    return FactorResearchRunResult(
        as_of_date=as_of_date,
        paths=paths,
        manifest=manifest,
        report_markdown=report_markdown,
        report_json=report_json,
    )


__all__ = [
    "FactorResearchRunResult",
    "run_factor_research",
]
