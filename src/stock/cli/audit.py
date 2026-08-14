"""数据质量与存储审计统一命令行 (CLI) 接口。"""

import argparse
import sys
from datetime import date
from typing import Any

from stock.utils.logger import logger


def run_audit(
    audit_type: str = "master",
    data_source: str = "tushare",
    target_date: date | None = None,
) -> dict[str, Any]:
    """根据类型执行指定的审计套件。"""
    audit_type_lower = audit_type.lower()
    t_date = target_date or date.today()
    results: dict[str, Any] = {}

    if audit_type_lower in {"master", "all"}:
        from stock.data.audit.master_audit import print_master_audit_summary, run_master_audit

        logger.info(f"=== 开始执行 Master 全库主数据审计 [{data_source}] ===")
        master_df = run_master_audit()
        print_master_audit_summary(master_df)
        results["master"] = master_df

    if audit_type_lower in {"reconciliation", "recon", "all"}:
        from stock.data.audit.reconciliation import run_audit as recon_run_audit

        logger.info(f"=== 开始执行 RAW vs Curated 对账审计 [{data_source}] (日期: {t_date}) ===")
        results["reconciliation"] = recon_run_audit(target_date=t_date, data_source=data_source)

    if audit_type_lower in {"acceptance", "all"}:
        from stock.data.audit.backfill_acceptance import accept_backfill

        logger.info(f"=== 开始执行全量回填验收测试 [{data_source}] ===")
        results["acceptance"] = accept_backfill(endpoint="stock_daily_bar")

    if audit_type_lower in {"valuation", "all"}:
        from stock.data.audit.valuation_audit import run_daily_basic_audit, run_sw_industry_audit

        logger.info(f"=== 开始执行估值指标专项审计 [{data_source}] (日期: {t_date}) ===")
        results["daily_basic"] = run_daily_basic_audit(t_date, data_source=data_source)
        sw_source = "lixinger" if data_source == "tushare" else data_source
        results["sw_industry"] = run_sw_industry_audit(t_date, data_source=sw_source)

    if audit_type_lower in {"factor", "all"}:
        from stock.data.audit.factor_audit import run_adj_factor_audit, run_sw_daily_audit

        logger.info(f"=== 开始执行技术指标因子审计 [{data_source}] (日期: {t_date}) ===")
        results["adj_factor"] = run_adj_factor_audit(t_date, data_source=data_source)
        results["sw_daily"] = run_sw_daily_audit(t_date, data_source=data_source)

    if audit_type_lower in {"moneyflow", "all"}:
        from stock.data.audit.moneyflow_audit import run_hk_hold_audit

        logger.info(f"=== 开始执行资金流向数据审计 [{data_source}] (日期: {t_date}) ===")
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

    args = parser.parse_args()
    target_dt = date.fromisoformat(args.date) if args.date else None
    logger.info(
        f"启动数据审计套件: 类型=[{args.audit_type}], "
        f"数据源=[{args.source}], 目标日期=[{target_dt or '最新'}]"
    )
    try:
        run_audit(audit_type=args.audit_type, data_source=args.source, target_date=target_dt)
        logger.info("数据审计执行完毕！")
    except Exception as e:
        logger.error(f"数据审计执行失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
