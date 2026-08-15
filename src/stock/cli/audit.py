"""数据质量与存储审计统一命令行 (CLI) 接口。"""

import argparse
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import polars as pl

from stock.utils.logger import logger


def _dataframe_audit_failed(result: pl.DataFrame) -> bool:
    if result.is_empty():
        return True
    for col in ("审计错误数", "audit_errors"):
        if col in result.columns:
            err = result.select(pl.col(col).fill_null(0).cast(pl.Int64, strict=False).sum()).item()
            if err and err > 0:
                return True
    if "status" in result.columns:
        return "FAILED" in {str(v).upper() for v in result["status"].drop_nulls().to_list()}
    return False


def _dict_audit_failed(result: dict[str, Any]) -> bool:
    if not result:
        return True
    if str(result.get("status", "")).upper() == "FAILED":
        return True
    return any(_audit_result_failed(v) for v in result.values())


def _audit_result_failed(result: Any) -> bool:
    """将审计函数的结构化失败结果转换为 CLI 退出语义。"""
    if isinstance(result, dict):
        return _dict_audit_failed(result)
    if isinstance(result, pl.DataFrame):
        return _dataframe_audit_failed(result)
    if isinstance(result, list | tuple):
        return any(_audit_result_failed(v) for v in result)
    return False


AUDIT_DEFAULT_DATASETS: dict[str, str] = {
    "valuation": "daily_basic",
    "factor": "adj_factor",
    "moneyflow": "hk_hold",
    "reconciliation": "stock_daily_bar",
    "recon": "stock_daily_bar",
    "acceptance": "stock_daily_bar",
    "distribution": "sw_daily",
}


def _resolve_audit_target_date(
    audit_type: str,
    data_source: str,
    target_date: date | None,
) -> tuple[date, bool]:
    """解析审计基准日期，若未显式指定则自适应探测核心数据集最新有效交易日。"""
    if target_date is not None:
        return target_date, False
    dataset = AUDIT_DEFAULT_DATASETS.get(audit_type.lower(), "stock_daily_bar")
    try:
        from stock.data.catalog import DataCatalog

        dates = DataCatalog(data_source=data_source).latest_trade_dates(dataset=dataset, n=1)
        if dates:
            return dates[0], True
    except Exception as exc:
        logger.debug(f"自适应探测最新交易日失败 [{data_source}/{dataset}]: {exc}")
    return date.today() - timedelta(days=1), True


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


def _run_range_audit(req: AuditRequest) -> dict[str, Any]:
    """执行历史时间段多交易日批量对账。"""
    s_d, e_d = req.start_date, req.end_date
    logger.info(f"=== 开始执行历史区间对账审计 [{req.data_source}] ({s_d} ~ {e_d}) ===")
    if req.audit_type.lower() == "index" and s_d and e_d:
        from stock.data.audit.reconciliation import run_index_audit_range

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
        from stock.data.audit.reconciliation import run_audit_range

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
    t_date: date,
    auto_tag: str,
    results: dict[str, Any],
) -> None:
    """执行各专项业务指标（估值、因子、资金流、分布）审计。"""
    a_type = req.audit_type.lower()
    src = req.data_source
    if a_type in {"valuation", "all"}:
        from stock.data.audit.valuation_audit import run_daily_basic_audit, run_sw_industry_audit

        logger.info(f"=== 开始执行估值指标专项审计 [{src}] (日期: {t_date}{auto_tag}) ===")
        results["daily_basic"] = run_daily_basic_audit(t_date, data_source=src)
        sw_src = "lixinger" if src == "tushare" else src
        results["sw_industry"] = run_sw_industry_audit(t_date, data_source=sw_src)

    if a_type in {"factor", "all"}:
        from stock.data.audit.factor_audit import run_adj_factor_audit, run_sw_daily_audit

        logger.info(f"=== 开始执行技术指标因子审计 [{src}] (日期: {t_date}{auto_tag}) ===")
        results["adj_factor"] = run_adj_factor_audit(t_date, data_source=src)
        results["sw_daily"] = run_sw_daily_audit(t_date, data_source=src)

    if a_type in {"moneyflow", "all"}:
        from stock.data.audit.moneyflow_audit import run_hk_hold_audit

        logger.info(f"=== 开始执行资金流向数据审计 [{src}] (日期: {t_date}{auto_tag}) ===")
        results["hk_hold"] = run_hk_hold_audit(t_date, data_source=src)

    if a_type in {"distribution", "all"}:
        from stock.data.audit.distribution_audit import run_distribution_audit

        logger.info(f"=== 开始执行 Curated 数值分布与阶跃异动审计 [{src}] ===")
        results["distribution"] = run_distribution_audit(
            dataset_name=req.dataset,
            data_source=src,
        )


def _run_domain_audit(req: AuditRequest, t_date: date) -> dict[str, Any]:
    """根据指定的领域或周期过滤并执行通用审计引擎。"""
    from stock.data.audit.engine import UniversalAuditEngine, print_audit_summary_report
    from stock.data.audit.registry import AUDIT_DATASET_REGISTRY

    engine = UniversalAuditEngine()
    t_domain = req.domain.lower() if req.domain else None
    t_freq = req.frequency.lower() if req.frequency else None
    matched_specs = [
        spec
        for spec in AUDIT_DATASET_REGISTRY.values()
        if (t_domain is None or spec.domain.value == t_domain)
        and (t_freq is None or spec.frequency.value == t_freq)
        and (req.data_source in {spec.data_source, "tushare"})
    ]
    reports = []
    for spec in matched_specs:
        logger.info(
            f"=== 执行领域 [{spec.domain.value}] 数据集 [{spec.dataset}] 审计 ({t_date}) ==="
        )
        reports.append(engine.audit_single_day(spec.dataset, t_date, data_source=spec.data_source))
    print_audit_summary_report(reports)
    return {"domain_reports": reports}


def run_audit(req: AuditRequest | None = None, **kwargs: Any) -> dict[str, Any]:
    """根据类型执行指定的审计套件 (支持单日与历史区间批量对账)。"""
    request = req or AuditRequest(**kwargs)
    audit_type_lower = request.audit_type.lower()
    if request.start_date is not None and request.end_date is not None:
        return _run_range_audit(request)

    t_date, is_auto = _resolve_audit_target_date(
        audit_type_lower, request.data_source, request.target_date
    )
    auto_tag = " [自动探测最新交易日]" if is_auto else ""

    if request.domain is not None or request.frequency is not None:
        return _run_domain_audit(request, t_date)

    results: dict[str, Any] = {}
    if audit_type_lower in {"master", "all"}:
        from stock.data.audit.master_audit import print_master_audit_summary, run_master_audit

        logger.info(f"=== 开始执行 Master 全库主数据审计 [{request.data_source}] ===")
        master_df = run_master_audit()
        print_master_audit_summary(master_df)
        results["master"] = master_df

    if audit_type_lower in {"reconciliation", "recon", "all"}:
        from stock.data.audit.reconciliation import run_audit as recon_run_audit

        logger.info(
            f"=== 开始执行 RAW vs Curated 对账审计 [{request.data_source}] ({t_date}{auto_tag}) ==="
        )
        results["reconciliation"] = recon_run_audit(
            target_date=t_date, data_source=request.data_source
        )

    if audit_type_lower in {"acceptance", "all"}:
        from stock.data.audit.backfill_acceptance import accept_backfill

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

    _run_specialized_audits(request, t_date, auto_tag, results)
    return results


def main() -> None:
    """Audit CLI 入口函数。"""
    parser = argparse.ArgumentParser(description="金融数据质量、存储对账与指标专项审计 CLI")
    parser.add_argument(
        "-t",
        "--type",
        dest="audit_type",
        type=str,
        default="master",
        choices=[
            "master",
            "reconciliation",
            "recon",
            "acceptance",
            "valuation",
            "factor",
            "moneyflow",
            "distribution",
            "all",
        ],
        help="审计套件类型 (master / reconciliation / acceptance / valuation / "
        "factor / distribution / all)",
    )
    parser.add_argument(
        "-s",
        "--source",
        "--data-source",
        dest="source",
        type=str,
        default="tushare",
        help="待审计数据源标识 (默认 tushare)",
    )
    parser.add_argument(
        "-d",
        "--date",
        dest="date",
        type=str,
        default=None,
        help="指定审计目标日期 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--start",
        dest="start",
        type=str,
        default=None,
        help="指定历史对账起始日期 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        dest="end",
        type=str,
        default=None,
        help="指定历史对账结束日期 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--max-workers",
        dest="max_workers",
        type=int,
        default=4,
        help="批量对账并发线程数 (默认 4)",
    )
    parser.add_argument(
        "--show-details",
        dest="show_details",
        action="store_true",
        help="是否打印历史区间每日对账明细",
    )
    parser.add_argument(
        "--domain",
        dest="domain",
        type=str,
        default=None,
        choices=[
            "equity",
            "industry",
            "index",
            "macro_liquidity",
            "macro_econ",
            "fundamental",
            "metadata",
        ],
        help="按业务领域过滤审计",
    )
    parser.add_argument(
        "--frequency",
        "--freq",
        dest="frequency",
        type=str,
        default=None,
        choices=["daily", "monthly", "quarterly", "static"],
        help="按时态周期过滤审计",
    )
    parser.add_argument(
        "--dataset",
        dest="dataset",
        type=str,
        default=None,
        help="指定审计的数据集名称 (如 sw_daily, daily_basic, stock_daily_bar 等)",
    )
    parser.add_argument(
        "--raw-root",
        default=None,
        help="回填验收时 RAW 数据根目录",
    )
    parser.add_argument(
        "--min-raw-ratio",
        type=float,
        default=None,
        help="回填验收要求的最小 Curated/RAW 行数比例",
    )

    args = parser.parse_args()
    target_dt = date.fromisoformat(args.date) if args.date else None
    start_dt = date.fromisoformat(args.start) if args.start else None
    end_dt = date.fromisoformat(args.end) if args.end else None

    logger.info(
        f"启动数据审计套件: 类型=[{args.audit_type}], 数据源=[{args.source}], "
        f"目标范围=[{f'{start_dt} ~ {end_dt}' if start_dt and end_dt else (target_dt or '最新')}]"
    )
    try:
        run_kwargs: dict[str, Any] = {
            "audit_type": args.audit_type,
            "data_source": args.source,
            "target_date": target_dt,
            "start_date": start_dt,
            "end_date": end_dt,
            "domain": args.domain,
            "frequency": args.frequency,
            "dataset": args.dataset,
            "max_workers": args.max_workers,
            "show_details": args.show_details,
        }
        if args.raw_root is not None:
            run_kwargs["raw_root"] = args.raw_root
        if args.min_raw_ratio is not None:
            run_kwargs["min_raw_ratio"] = args.min_raw_ratio
        result = run_audit(**run_kwargs)
        if _audit_result_failed(result):
            logger.error("数据审计存在失败项")
            sys.exit(1)
        logger.info("数据审计执行完毕！")
    except Exception as e:
        logger.error(f"数据审计执行失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
