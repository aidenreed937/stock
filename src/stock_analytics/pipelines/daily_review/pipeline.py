"""每日盘后全景量化复盘业务管线。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from stock_analytics.pipelines.artifacts import (
    ArtifactUnavailableError,
    resolve_artifact_run,
)
from stock_analytics.pipelines.daily_review.quant_brief_context import (
    resolve_quant_brief_context,
)
from stock_analytics.pipelines.industry_structure import run_industry_structure
from stock_analytics.pipelines.market_temperature import (
    MarketAnalysisContext,
    run_market_temperature,
)
from stock_analytics.pipelines.watchlist_scanner import run_watchlist_scanner
from stock_analytics.pipelines.watchlist_scanner.types import WatchlistScanResult
from stock_core.utils.logger import logger
from stock_reporting.engine import ReportRenderer
from stock_reporting.interpretation.market_temperature.bands import get_temperature_band

_DEFAULT_ANALYTICS_ROOT = Path("data/analytics")


@dataclass(frozen=True, slots=True)
class DailyReviewRunResult:
    """每日复盘一次运行的结果。"""

    as_of_date: date
    report_path: Path
    context_path: Path
    context: dict[str, Any]


def run_daily_review(
    *,
    target_date: date | None = None,
    output_dir: Path | str | None = None,
    storage_dir: Path | str | None = None,
    analytics_root: Path | str | None = None,
    refresh_upstream: bool = False,
) -> DailyReviewRunResult:
    """复用或生成上游产物，组装每日复盘上下文并渲染报告。"""
    logger.info("开始执行每日盘后全景量化复盘流水线...")
    analytics_base = Path(analytics_root) if analytics_root is not None else _DEFAULT_ANALYTICS_ROOT
    market_artifact_root = analytics_base / "market_temperature"
    industry_artifact_root = analytics_base / "industry_structure"
    scan_result = run_watchlist_scanner(target_date=target_date, storage_dir=storage_dir)
    as_of_date = date.fromisoformat(scan_result.as_of_date)

    if refresh_upstream:
        _refresh_stock_screen(as_of_date, storage_dir=storage_dir, analytics_base=analytics_base)

    market_context = _resolve_market_context(
        as_of_date,
        storage_dir=storage_dir,
        artifact_root=market_artifact_root,
        refresh_upstream=refresh_upstream,
    )
    top_industries, low_value_industries, industry_context = _resolve_industry_structure(
        as_of_date,
        storage_dir=storage_dir,
        artifact_root=industry_artifact_root,
        refresh_upstream=refresh_upstream,
    )
    temp_score, temp_band, dimensions = _build_temperature_summary(market_context)
    risk_info = market_context.get("risk", {})
    risk_dict = risk_info if isinstance(risk_info, dict) else {}
    systemic_risk_level = risk_dict.get("level", "低到中等")
    systemic_risk_message = risk_dict.get("message", "")
    quant_brief_context = resolve_quant_brief_context(
        as_of_date,
        analytics_base=analytics_base,
        storage_dir=storage_dir,
        refresh_upstream=refresh_upstream,
    )
    position_advice = _build_position_advice(temp_score)
    items_context = _build_watchlist_items(scan_result)

    context = {
        "as_of_date": scan_result.as_of_date,
        "temperature_score": f"{temp_score:.2f}" if temp_score is not None else None,
        "temperature_band": temp_band,
        "systemic_risk_level": systemic_risk_level,
        "systemic_risk_message": systemic_risk_message,
        "dimension_items": dimensions,
        "dimension_summary": (
            " ｜ ".join(f"{key}: {value:.1f}分" for key, value in dimensions.items())
            if dimensions
            else ""
        ),
        "position_advice": position_advice,
        "quant_brief": quant_brief_context,
        "macro_decoupling": _load_macro_decoupling_info(scan_result.as_of_date, market_context),
        "market_context": market_context,
        "industry_context": industry_context,
        "top_industries": top_industries,
        "low_val_industries": low_value_industries,
        "total_scanned": scan_result.total_scanned,
        "golden_pit_count": len(scan_result.golden_pit_candidates),
        "high_dividend_count": len(scan_result.high_dividend_candidates),
        "value_trap_count": len(scan_result.value_trap_candidates),
        "items": items_context,
    }

    report_content = ReportRenderer.get_instance().render(
        "review/daily_market_review.md.j2",
        context,
    )
    report_dir = Path(output_dir or "output/reports/daily")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{scan_result.as_of_date}_全景量化复盘报告.md"
    context_path = report_dir / f"{scan_result.as_of_date}_全景量化复盘上下文.json"
    report_path.write_text(report_content, encoding="utf-8")
    context_path.write_text(
        json.dumps(context, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("每日全景量化复盘研报已生成并落盘至: {}", report_path)
    return DailyReviewRunResult(
        as_of_date=as_of_date,
        report_path=report_path,
        context_path=context_path,
        context=context,
    )


def _resolve_market_context(
    as_of_date: date,
    *,
    storage_dir: Path | str | None,
    artifact_root: Path,
    refresh_upstream: bool,
) -> dict[str, Any]:
    if not refresh_upstream:
        try:
            run = resolve_artifact_run(
                artifact_root,
                as_of_date=as_of_date,
                expected_artifact_type="market_temperature",
            )
            return MarketAnalysisContext.load(
                artifact_root=artifact_root,
                as_of=as_of_date,
                run_id=str(run.manifest["run_id"]),
            ).query(("overview", "trend", "risk"))
        except ArtifactUnavailableError:
            pass

    run_result = run_market_temperature(
        target_date=as_of_date,
        storage_dir=storage_dir,
        output_root=artifact_root,
    )
    return MarketAnalysisContext.load(
        artifact_root=run_result.paths.root,
        as_of=as_of_date,
        run_id=run_result.paths.run_dir.name,
    ).query(("overview", "trend", "risk"))


def _resolve_industry_structure(
    as_of_date: date,
    *,
    storage_dir: Path | str | None,
    artifact_root: Path,
    refresh_upstream: bool,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    cached = (
        None
        if refresh_upstream
        else _load_industry_structure_artifact(as_of_date, artifact_root=artifact_root)
    )
    if cached is None:
        run_result = run_industry_structure(
            target_date=as_of_date,
            storage_dir=storage_dir,
            output_root=artifact_root,
        )
        scores = run_result.scores
        metadata = {
            "as_of_date": run_result.manifest.get("as_of_date"),
            "run_id": run_result.manifest.get("run_id"),
            "source": "fresh",
        }
    else:
        scores, metadata = cached
    return _industry_lists(scores), _industry_low_value_lists(scores), metadata


def _load_industry_structure_artifact(
    as_of_date: date,
    *,
    artifact_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    try:
        run = resolve_artifact_run(
            artifact_root,
            as_of_date=as_of_date,
            expected_artifact_type="industry_structure",
        )
        scores = run.read_json("scores.json")
    except ArtifactUnavailableError as exc:
        logger.warning(f"行业结构缓存产物不可用: {exc}")
        return None
    return scores, {
        "as_of_date": run.manifest.get("as_of_date"),
        "run_id": run.manifest.get("run_id"),
        "source": "cached",
    }


def _build_temperature_summary(
    market_context: dict[str, Any],
) -> tuple[float | None, str, dict[str, float]]:
    current = market_context.get("current", {})
    current = current if isinstance(current, dict) else {}
    composite = current.get("composite", {})
    composite = composite if isinstance(composite, dict) else {}
    dimensions = current.get("dimensions", [])
    dimensions = dimensions if isinstance(dimensions, list) else []
    temperature = composite.get("temperature")
    dimension_values = {
        str(item.get("name") or item.get("dimension_id")): float(item["temperature"])
        for item in dimensions
        if isinstance(item, dict)
        and item.get("temperature") is not None
        and (item.get("name") or item.get("dimension_id"))
    }
    numeric_temperature = float(temperature) if temperature is not None else None
    return numeric_temperature, get_temperature_band(numeric_temperature), dimension_values


def _build_position_advice(temp_score: float | None) -> str:
    if temp_score is None:
        return "50% - 60% (中性平衡，重结构轻指数)"
    if temp_score < 30.0:
        return "30% - 40% (冰点区域，保持耐心，分批逢低吸纳)"
    if temp_score > 70.0:
        return "30% - 50% (偏热过热，注意止盈，控制回撤)"
    return "50% - 60% (中性平衡，重结构轻指数)"


def _build_watchlist_items(scan_result: WatchlistScanResult) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in scan_result.items:
        pe_display = (
            f"{item.pe_ttm:.1f} ({item.pe_percentile_5y:.1f}%)"
            if item.pe_ttm is not None and item.pe_percentile_5y is not None
            else f"{item.pe_ttm:.1f}"
            if item.pe_ttm is not None
            else "--"
        )
        dividend_display = (
            f"{item.dv_ttm:.2f}% ({item.dividend_spread_10y:+.2f}%)"
            if item.dv_ttm is not None and item.dividend_spread_10y is not None
            else f"{item.dv_ttm:.2f}%"
            if item.dv_ttm is not None
            else "--"
        )
        items.append(
            {
                "symbol": item.symbol,
                "name": item.name,
                "industry": item.industry,
                "close": item.close,
                "pct_chg": item.pct_chg or 0.0,
                "pe_display": pe_display,
                "pb_display": f"{item.pb:.2f}" if item.pb is not None else "--",
                "dividend_display": dividend_display,
                "roe_display": f"{item.roe:.1f}%" if item.roe is not None else "--",
                "trend_status": item.trend_description.split(" ")[0],
                "tag_display": "、".join(item.tags) if item.tags else "常规",
            }
        )
    return items


def _load_macro_decoupling_info(
    as_of_date: str,
    market_context: dict[str, Any],
) -> dict[str, Any]:
    provenance = market_context.get("provenance", {})
    provenance = provenance if isinstance(provenance, dict) else {}
    source_cutoffs = provenance.get("source_cutoffs", {})
    source_cutoffs = source_cutoffs if isinstance(source_cutoffs, dict) else {}
    return {
        "review_cutoff": str(source_cutoffs.get("external_market") or "2026-08-20"),
        "forecast_cutoff": as_of_date,
        "proxies": [
            {"code": "FXI", "name": "富时中国 50 ETF", "role": "离岸中资大盘核心期权锚"},
            {"code": "ASHR", "name": "沪深 300 离岸 ETF", "role": "直接映射 A 股核心蓝筹定价"},
            {"code": "USD/CNH", "name": "离岸人民币汇率", "role": "反映外资跨境流动性与汇率偏好"},
            {"code": "^VIX", "name": "标普恐慌指数", "role": "全球宏观流动性与避险情绪风向标"},
        ],
    }


def _industry_lists(scores: dict[str, Any]) -> list[dict[str, str]]:
    return _format_industry_items(scores.get("top_structure"))


def _industry_low_value_lists(scores: dict[str, Any]) -> list[dict[str, str]]:
    return _format_industry_items(scores.get("undervalued_improving"))


def _format_industry_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {
            "name": str(item.get("industry_name", "")),
            "score": f"{item.get('structure_score', 0.0):.1f}",
            "tags": str(item.get("tags", "")),
        }
        for item in value[:5]
        if isinstance(item, dict)
    ]


def _refresh_stock_screen(
    as_of_date: date,
    *,
    storage_dir: Path | str | None,
    analytics_base: Path,
) -> None:
    try:
        from stock_analytics.pipelines.stock_screen import run_stock_screen

        logger.info("刷新全市场个股排雷与选股上游产物...")
        run_stock_screen(
            target_date=as_of_date,
            storage_dir=storage_dir,
            output_root=analytics_base / "stock_screen",
        )
    except Exception as exc:
        logger.warning(f"刷新个股排雷产物失败（继续执行复盘）: {exc}")


__all__ = ["DailyReviewRunResult", "run_daily_review"]
