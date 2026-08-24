"""Features 与 Analytics Mart CLI。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from stock_analytics.features import FeatureStore, MarketDailyBuilder
from stock_analytics.marts import DomainMartBuilder
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="构建与管理 Analytics Mart 特征宽表",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="构建并物化市场/行业日频特征宽表")
    build_parser.add_argument(
        "--target",
        choices=[
            "market_daily",
            "industry_daily",
            "industry_panel_daily",
            "derived_facts",
            "domain_marts",
            "all",
        ],
        default="market_daily",
        help="待构建的目标宽表或领域 Mart",
    )
    build_parser.add_argument(
        "-s",
        "--start",
        dest="start_date",
        default=None,
        help="起始日期 (YYYY-MM-DD, 默认 2014-01-01)",
    )
    build_parser.add_argument(
        "-e",
        "--end",
        dest="end_date",
        default=None,
        help="结束日期 (YYYY-MM-DD, 默认最新落盘交易日)",
    )
    build_parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="是否全量覆写已存在的宽表",
    )
    build_parser.add_argument(
        "--storage-dir",
        dest="storage_dir",
        default=None,
        help="Curated 数据根目录",
    )

    return parser


def main() -> None:
    """CLI 主入口。"""
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "build":
        start_date = _parse_date(args.start_date) or date(2014, 1, 1)
        end_date = _parse_date(args.end_date)
        storage_dir = Path(args.storage_dir) if args.storage_dir else None

        catalog = DataCatalog(data_source="tushare", storage_dir=storage_dir)
        store = FeatureStore(mart_dir=storage_dir / "mart" if storage_dir else None)

        if args.target in ("market_daily", "all"):
            market_builder = MarketDailyBuilder(
                catalog=catalog, store=store, storage_dir=storage_dir
            )
            df = market_builder.build(
                start_date=start_date,
                end_date=end_date,
                save=True,
                overwrite=args.overwrite,
            )
            if df.is_empty():
                logger.error("构建 market_daily 失败: 产出数据为空")
                sys.exit(1)
            date_min = str(df["trade_date"].min())
            date_max = str(df["trade_date"].max())
            logger.info(
                f"成功构建并物化 market_daily: {len(df)} 行 (时间跨度: {date_min} ~ {date_max})"
            )

        if args.target in ("domain_marts", "all"):
            domain_builder = DomainMartBuilder(catalog=catalog, store=store)
            results = domain_builder.build_all(
                start_date=start_date,
                end_date=end_date,
                overwrite=args.overwrite,
            )
            output_count = 0
            for name, result in results.items():
                if isinstance(result, dict):
                    count = sum(frame.height for frame in result.values())
                else:
                    count = result.height
                output_count += count
                logger.info(f"领域 Mart [{name}] 构建完成: {count} 行")
            logger.info(f"领域 Mart 全部构建完成: {output_count} 行")
        elif args.target in ("industry_daily", "industry_panel_daily", "derived_facts"):
            domain_builder = DomainMartBuilder(catalog=catalog, store=store)
            if args.target == "industry_daily":
                result = domain_builder.build_industry_daily(
                    start_date=start_date,
                    end_date=end_date,
                    overwrite=args.overwrite,
                )
                logger.info(f"领域 Mart [industry_daily] 构建完成: {result.height} 行")
            elif args.target == "industry_panel_daily":
                result = domain_builder.build_industry_panel_daily(
                    start_date=start_date,
                    end_date=end_date,
                    overwrite=args.overwrite,
                )
                logger.info(f"领域 Mart [industry_panel_daily] 构建完成: {result.height} 行")
            else:
                result = domain_builder.build_market_temperature_derived_facts(
                    start_date=start_date,
                    end_date=end_date,
                    overwrite=args.overwrite,
                )
                logger.info(
                    f"领域 Mart [market_temperature_derived_facts] 构建完成: {result.height} 行"
                )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        logger.error("日期格式错误，请使用 YYYY-MM-DD: {}", value)
        sys.exit(1)


if __name__ == "__main__":
    main()
