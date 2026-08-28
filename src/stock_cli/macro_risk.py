"""宏观系统性风险 CLI 入口。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.macro_risk import MacroRiskPipeline
from stock_core.utils.logger import logger, setup_logger


def _parse_date(v: str | None) -> date | None:
    return date.fromisoformat(v) if v else None


def main() -> None:
    parser = argparse.ArgumentParser(description="生成全市场系统性风险双轨制雷达指数。")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/analytics/macro_risk",
        help="产物输出目录",
    )
    parser.add_argument(
        "--as-of",
        type=_parse_date,
        default=None,
        help="指定单日基准日期 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--start",
        type=_parse_date,
        default=None,
        help="连续区间起始日期 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=_parse_date,
        default=None,
        help="连续区间截止日期 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--last-n",
        type=int,
        default=None,
        help="最近 N 个连续交易日",
    )
    parser.add_argument(
        "--no-publish-latest",
        action="store_true",
        help="不更新 latest 软链/视图",
    )
    args = parser.parse_args()
    setup_logger()

    out_dir = Path(args.output_dir)
    pipeline = MacroRiskPipeline()

    try:
        # 获取全部有效交易日列表
        all_dates = (
            pipeline._market_daily()
            .filter(pl.col("trade_date") >= date(2015, 1, 1))["trade_date"]
            .sort()
            .to_list()
        )

        target_dates: list[date] = []
        if args.as_of is not None:
            target_dates = [args.as_of]
        elif args.last_n is not None:
            target_dates = all_dates[-args.last_n :]
        elif args.start is not None or args.end is not None:
            s_date = args.start or all_dates[0]
            e_date = args.end or all_dates[-1]
            target_dates = [d for d in all_dates if s_date <= d <= e_date]
        else:
            target_dates = [all_dates[-1]]

        logger.info(f"即将执行宏观风险管线 (共 {len(target_dates)} 个交易日)")
        for idx, d in enumerate(target_dates):
            is_last = idx == len(target_dates) - 1
            update_latest = not args.no_publish_latest and is_last
            logger.info(f"[{idx + 1}/{len(target_dates)}] 运行宏观风控管线 as_of={d!s}")
            pipeline.run(
                as_of=d,
                output_dir=out_dir,
                update_latest=update_latest,
            )
        logger.info(f"全部 {len(target_dates)} 个交易日宏观风控产物落盘完成")
    except Exception as exc:
        logger.exception(f"系统性风险管线运行失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
