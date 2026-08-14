"""数据质量与存储审计统一命令行 (CLI) 接口。"""

import argparse
import sys
from datetime import date
from typing import Any

import polars as pl

from stock.utils.logger import logger


def _dataframe_audit_failed(result: pl.DataFrame) -> bool:
    if result.is_empty():
        return True

    for column in ("审计错误数", "audit_errors"):
        if column not in result.columns:
            continue
        error_count = result.select(
            pl.col(column).fill_null(0).cast(pl.Int64, strict=False).sum()
        ).item()
        if error_count and error_count > 0:
            return True

    if "status" not in result.columns:
        return False
    statuses = {str(value).upper() for value in result.get_column("status").drop_nulls().to_list()}
    return "FAILED" in statuses


def _dict_audit_failed(result: dict[str, Any]) -> bool:
    if not result:
        return True
    status = result.get("status")
    if isinstance(status, str) and status.upper() == "FAILED":
        return True
    return any(_audit_result_failed(value) for value in result.values())


def _audit_result_failed(result: Any) -> bool:
    """将审计函数的结构化失败结果转换为 CLI 退出语义。"""
    if isinstance(result, dict):
        return _dict_audit_failed(result)
    if isinstance(result, pl.DataFrame):
        return _dataframe_audit_failed(result)

    if isinstance(result, list | tuple):
        return any(_audit_result_failed(value) for value in result)
    return False


AUDIT_DEFAULT_DATASETS: dict[str, str] = {
    "valuation": "daily_basic",
    "factor": "adj_factor",
    "moneyflow": "hk_hold",
    "reconciliation": "stock_daily_bar",
    "recon": "stock_daily_bar",
    "acceptance": "stock_daily_bar",
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

        catalog = DataCatalog(data_source=data_source)
        dates = catalog.latest_trade_dates(dataset=dataset, n=1)
        if dates:
            return dates[0], True
    except Exception as exc:
        logger.debug(f"自适应探测最新交易日失败 [{data_source}/{dataset}]: {exc}")

    from datetime import timedelta

    return date.today() - timedelta(days=1), True


def run_audit(
    audit_type: str = "master",
    data_source: str = "tushare",
    target_date: date | None = None,
    raw_root: str | None = None,
    min_raw_ratio: float | None = None,
) -> dict[str, Any]:
    """根据类型执行指定的审计套件。"""
    audit_type_lower = audit_type.lower()
    t_date, is_auto = _resolve_audit_target_date(audit_type_lower, data_source, target_date)
    auto_tag = " [自动探测最新交易日]" if is_auto else ""
    results: dict[str, Any] = {}

    if audit_type_lower in {"master", "all"}:
        from stock.data.audit.master_audit import print_master_audit_summary, run_master_audit

        logger.info(f"=== 开始执行 Master 全库主数据审计 [{data_source}] ===")
        master_df = run_master_audit()
        print_master_audit_summary(master_df)
        results["master"] = master_df

    if audit_type_lower in {"reconciliation", "recon", "all"}:
        from stock.data.audit.reconciliation import run_audit as recon_run_audit

        logger.info(
            f"=== 开始执行 RAW vs Curated 对账审计 [{data_source}] (日期: {t_date}{auto_tag}) ==="
        )
        results["reconciliation"] = recon_run_audit(target_date=t_date, data_source=data_source)

    if audit_type_lower in {"acceptance", "all"}:
        from stock.data.audit.backfill_acceptance import accept_backfill

        logger.info(f"=== 开始执行全量回填验收测试 [{data_source}] ===")
        accept_kwargs: dict[str, Any] = {
            "endpoint": "stock_daily_bar",
            "data_source": data_source,
        }
        if raw_root is not None:
            accept_kwargs["raw_root"] = raw_root
        if min_raw_ratio is not None:
            accept_kwargs["min_raw_ratio"] = min_raw_ratio
        results["acceptance"] = accept_backfill(**accept_kwargs)

    if audit_type_lower in {"valuation", "all"}:
        from stock.data.audit.valuation_audit import run_daily_basic_audit, run_sw_industry_audit

        logger.info(f"=== 开始执行估值指标专项审计 [{data_source}] (日期: {t_date}{auto_tag}) ===")
        results["daily_basic"] = run_daily_basic_audit(t_date, data_source=data_source)
        sw_source = "lixinger" if data_source == "tushare" else data_source
        results["sw_industry"] = run_sw_industry_audit(t_date, data_source=sw_source)

    if audit_type_lower in {"factor", "all"}:
        from stock.data.audit.factor_audit import run_adj_factor_audit, run_sw_daily_audit

        logger.info(f"=== 开始执行技术指标因子审计 [{data_source}] (日期: {t_date}{auto_tag}) ===")
        results["adj_factor"] = run_adj_factor_audit(t_date, data_source=data_source)
        results["sw_daily"] = run_sw_daily_audit(t_date, data_source=data_source)

    if audit_type_lower in {"moneyflow", "all"}:
        from stock.data.audit.moneyflow_audit import run_hk_hold_audit

        logger.info(f"=== 开始执行资金流向数据审计 [{data_source}] (日期: {t_date}{auto_tag}) ===")
        results["hk_hold"] = run_hk_hold_audit(t_date, data_source=data_source)

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
            "all",
        ],
        help="审计套件类型 (master / reconciliation / acceptance / valuation / factor / all)",
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
        help="指定审计目标日期 (YYYY-MM-DD，默认最新或当日)",
    )
    parser.add_argument(
        "--raw-root",
        default=None,
        help="回填验收时 RAW 数据根目录（启用 RAW/Curated 行数对比）",
    )
    parser.add_argument(
        "--min-raw-ratio",
        type=float,
        default=None,
        help="回填验收要求的最小 Curated/RAW 行数比例（0~1）",
    )

    args = parser.parse_args()
    target_dt = date.fromisoformat(args.date) if args.date else None
    logger.info(
        f"启动数据审计套件: 类型=[{args.audit_type}], "
        f"数据源=[{args.source}], 目标日期=[{target_dt or '最新'}]"
    )
    try:
        run_kwargs: dict[str, Any] = {
            "audit_type": args.audit_type,
            "data_source": args.source,
            "target_date": target_dt,
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
