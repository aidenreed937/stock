"""公司海外营收布局 Mart CLI（overseas_revenue）。

构建并落盘 ``data/curated/mart/overseas_revenue.parquet``：海外营收 / 占总营收比例 /
同比，ann_date 无前视。属于 ``DomainMartBuilder.build_all`` 成员，本命令用于单独刷新。

用法:
    uv run python -m stock_cli.overseas_revenue
    uv run python -m stock_cli.overseas_revenue --overwrite
"""

from __future__ import annotations

import argparse
import sys

from stock_analytics.features import FeatureStore
from stock_analytics.marts import DomainMartBuilder
from stock_core.utils.logger import logger, setup_logger
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext

_MART_NAME = "overseas_revenue"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock_cli.overseas_revenue",
        description="公司海外营收布局 Mart: 海外营收/占比/同比 (ann_date 无前视)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data-root",
        default="data",
        help="数据根目录（缺省 data）",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖已有 Mart（默认增量合并）",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    setup_logger()

    try:
        runtime = DataRuntimeContext.from_root(args.data_root)
        catalog = DataCatalog(data_source="tushare", runtime=runtime)
        store = FeatureStore(mart_dir=runtime.curated_root / "mart", runtime=runtime)
        builder = DomainMartBuilder(catalog, store, runtime=runtime)
        mart = builder.build_overseas_revenue(overwrite=args.overwrite)
    except (ValueError, OSError) as exc:
        logger.error("海外营收布局 Mart 构建失败: %s", exc)
        sys.exit(1)

    print(f"已生成海外营收布局 Mart: {mart.height} 行")
    print(f"落盘: {runtime.curated_root / 'mart' / _MART_NAME}.parquet")


if __name__ == "__main__":
    main()
