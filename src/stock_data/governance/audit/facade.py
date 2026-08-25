"""数据质量审计套件的领域 Facade。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import polars as pl

from stock_core.utils.logger import logger

AUDIT_DEFAULT_DATASETS: dict[str, str] = {
    "valuation": "daily_basic",
    "factor": "adj_factor",
    "moneyflow": "hk_hold",
    "reconciliation": "stock_daily_bar",
    "recon": "stock_daily_bar",
    "acceptance": "stock_daily_bar",
    "distribution": "sw_daily",
}


@dataclass
class AuditRequest:
    """数据审计请求参数模型。"""

    audit_type: str = "master"
    data_source: str = "tushare"
    target_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    domain: str | None = None
    frequency: str | None = None
    dataset: str | None = None
    raw_root: str | None = None
    min_raw_ratio: float | None = None
    max_workers: int = 4
    show_details: bool = False


def resolve_audit_target_date(
    audit_type: str,
    data_source: str,
    target_date: date | None,
) -> tuple[date, bool]:
    """解析审计基准日期，未指定时探测核心数据集最新交易日。"""
    if target_date is not None:
        return target_date, False
    dataset = AUDIT_DEFAULT_DATASETS.get(audit_type.lower(), "stock_daily_bar")
    try:
        from stock_data.catalog import DataCatalog

        dates = DataCatalog(data_source=data_source).latest_trade_dates(dataset=dataset, n=1)
        if dates:
            return dates[0], True
    except Exception as exc:
        logger.debug(f"自适应探测最新交易日失败 [{data_source}/{dataset}]: {exc}")
    return date.today() - timedelta(days=1), True


def _run_range_audit(req: AuditRequest) -> dict[str, Any]:
    s_d, e_d = req.start_date, req.end_date
    logger.info(f"=== 开始执行历史区间对账审计 [{req.data_source}] ({s_d} ~ {e_d}) ===")
    if req.audit_type.lower() == "index" and s_d and e_d:
        from stock_data.governance.audit.reconciliation import run_index_audit_range

        return {
            "index_range": run_index_audit_range(
                s_d,
                e_d,
                data_source=req.data_source,
                max_workers=req.max_workers,
                show_details=req.show_details,
            )
        }
    if s_d and e_d:
        from stock_data.governance.audit.reconciliation import run_audit_range

        return {
            "reconciliation_range": run_audit_range(
                s_d,
                e_d,
                data_source=req.data_source,
                max_workers=req.max_workers,
                show_details=req.show_details,
            )
        }
    return {}


def _run_specialized_audits(
    req: AuditRequest,
    target_date: date,
    auto_tag: str,
    results: dict[str, Any],
) -> None:
    audit_type = req.audit_type.lower()
    source = req.data_source
    if audit_type in {"valuation", "all"}:
        from stock_data.governance.audit.valuation_audit import (
            run_daily_basic_audit,
            run_sw_industry_audit,
        )

        logger.info(f"=== 开始执行估值指标专项审计 [{source}] (日期: {target_date}{auto_tag}) ===")
        results["daily_basic"] = run_daily_basic_audit(target_date, data_source=source)
        sw_source = "lixinger" if source == "tushare" else source
        results["sw_industry"] = run_sw_industry_audit(target_date, data_source=sw_source)

    if audit_type in {"factor", "all"}:
        from stock_data.governance.audit.factor_audit import (
            run_adj_factor_audit,
            run_sw_daily_audit,
        )

        logger.info(f"=== 开始执行技术指标因子审计 [{source}] (日期: {target_date}{auto_tag}) ===")
        results["adj_factor"] = run_adj_factor_audit(target_date, data_source=source)
        results["sw_daily"] = run_sw_daily_audit(target_date, data_source=source)

    if audit_type in {"moneyflow", "all"}:
        from stock_data.governance.audit.moneyflow_audit import run_hk_hold_audit

        logger.info(f"=== 开始执行资金流向数据审计 [{source}] (日期: {target_date}{auto_tag}) ===")
        results["hk_hold"] = run_hk_hold_audit(target_date, data_source=source)

    if audit_type in {"distribution", "all"}:
        from stock_data.governance.audit.distribution_audit import run_distribution_audit

        logger.info(f"=== 开始执行 Curated 数值分布与阶跃异动审计 [{source}] ===")
        results["distribution"] = run_distribution_audit(
            dataset_name=req.dataset,
            data_source=source,
            start_date=req.start_date,
            end_date=req.end_date,
        )


def _run_domain_audit(req: AuditRequest, target_date: date) -> dict[str, Any]:
    from stock_data.governance.audit.engine import UniversalAuditEngine, print_audit_summary_report
    from stock_data.governance.audit.registry import AUDIT_DATASET_REGISTRY

    engine = UniversalAuditEngine()
    domain = req.domain.lower() if req.domain else None
    frequency = req.frequency.lower() if req.frequency else None
    matched_specs = [
        spec
        for spec in AUDIT_DATASET_REGISTRY.values()
        if (domain is None or spec.domain.value == domain)
        and (frequency is None or spec.frequency.value == frequency)
        and (req.data_source in {spec.data_source, "tushare"})
    ]
    reports = []
    for spec in matched_specs:
        logger.info(
            f"=== 执行领域 [{spec.domain.value}] 数据集 [{spec.dataset}] 审计 ({target_date}) ==="
        )
        reports.append(
            engine.audit_single_day(spec.dataset, target_date, data_source=spec.data_source)
        )
    print_audit_summary_report(reports)
    return {"domain_reports": reports}


def run_audit(req: AuditRequest | None = None, **kwargs: Any) -> dict[str, Any]:
    """执行指定的审计套件，支持单日与历史区间对账。"""
    request = req or AuditRequest(**kwargs)
    audit_type = request.audit_type.lower()
    if (
        request.start_date is not None
        and request.end_date is not None
        and audit_type in {"reconciliation", "recon", "index"}
    ):
        return _run_range_audit(request)

    target_date, is_auto = resolve_audit_target_date(
        audit_type, request.data_source, request.target_date
    )
    auto_tag = " [自动探测最新交易日]" if is_auto else ""
    if request.domain is not None or request.frequency is not None:
        return _run_domain_audit(request, target_date)

    results: dict[str, Any] = {}
    if audit_type in {"master", "all"}:
        from stock_data.governance.audit.master_audit import (
            print_master_audit_summary,
            run_master_audit,
        )

        logger.info(f"=== 开始执行 Master 全库主数据审计 [{request.data_source}] ===")
        master_df = run_master_audit()
        print_master_audit_summary(master_df)
        results["master"] = master_df

    if audit_type in {"reconciliation", "recon", "all"}:
        from stock_data.governance.audit.reconciliation import run_audit as run_reconciliation

        logger.info(
            f"=== 开始执行 RAW vs Curated 对账审计 [{request.data_source}] "
            f"({target_date}{auto_tag}) ==="
        )
        results["reconciliation"] = run_reconciliation(
            target_date=target_date,
            data_source=request.data_source,
        )

    if audit_type in {"acceptance", "all"}:
        from stock_data.governance.audit.backfill_acceptance import accept_backfill

        logger.info(f"=== 开始执行全量回填验收测试 [{request.data_source}] ===")
        accept_kwargs: dict[str, Any] = {
            "endpoint": "stock_daily_bar",
            "data_source": request.data_source,
        }
        if request.raw_root is not None:
            accept_kwargs["raw_root"] = request.raw_root
        if request.min_raw_ratio is not None:
            accept_kwargs["min_raw_ratio"] = request.min_raw_ratio
        results["acceptance"] = accept_backfill(**accept_kwargs)

    _run_specialized_audits(request, target_date, auto_tag, results)
    return results


def audit_result_failed(result: Any) -> bool:
    """将审计结果转换为命令退出语义。"""
    if isinstance(result, dict):
        if not result or str(result.get("status", "")).upper() == "FAILED":
            return True
        return any(audit_result_failed(value) for value in result.values())
    if isinstance(result, pl.DataFrame):
        if result.is_empty():
            return True
        for column in ("审计错误数", "audit_errors"):
            if column in result.columns:
                errors = result.select(
                    pl.col(column).fill_null(0).cast(pl.Int64, strict=False).sum()
                ).item()
                if errors and errors > 0:
                    return True
        if "status" in result.columns:
            return "FAILED" in {str(value).upper() for value in result["status"].drop_nulls()}
        return False
    if isinstance(result, list | tuple):
        return any(audit_result_failed(value) for value in result)
    return False


run_audit_suite = run_audit


__all__ = [
    "AUDIT_DEFAULT_DATASETS",
    "AuditRequest",
    "audit_result_failed",
    "resolve_audit_target_date",
    "run_audit",
    "run_audit_suite",
]
