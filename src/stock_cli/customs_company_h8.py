"""构建报告期无前视的公司-H8 出口暴露 Mart（可选：公司×产品面板 + 三层信号）。

用法：

.. code-block:: bash

   uv run python -m stock_cli.customs_company_h8
   uv run python -m stock_cli.customs_company_h8 --as-of-period 2026-06-30
   uv run python -m stock_cli.customs_company_h8 --with-signal  # 追加面板+三层信号
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stock_analytics.marts import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_CUSTOMS_TRADE_PATH,
    DEFAULT_MAINBZ_PATH,
    DEFAULT_MART_DIR,
    DEFAULT_STOCK_BASIC_PATH,
    build_customs_company_h8_marts,
    save_customs_company_h8_marts,
)
from stock_analytics.pipelines.customs_company_h8 import run_customs_company_h8_pipeline
from stock_core.utils.logger import logger, setup_logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stock_cli.customs_company_h8",
        description="主营构成 → H8 → 公司月度出口暴露 Mart（可选面板+三层信号）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--mainbz", type=Path, default=DEFAULT_MAINBZ_PATH, help="fina_mainbz 路径")
    parser.add_argument(
        "--stock-basic", type=Path, default=DEFAULT_STOCK_BASIC_PATH, help="公司维度表路径"
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH, help="H8 主表路径")
    parser.add_argument(
        "--customs-trade",
        type=Path,
        default=DEFAULT_CUSTOMS_TRADE_PATH,
        help="海关黄金事实表路径",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_MART_DIR, help="Mart 输出目录")
    parser.add_argument(
        "--as-of-period",
        default=None,
        help="只使用该报告期及以前的 fina_mainbz，例如 2026-06-30；默认使用全量历史",
    )
    parser.add_argument(
        "--with-signal",
        action="store_true",
        help="追加公司×产品面板与三层信号合成",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help="面板/信号产物输出目录（默认 data/analytics/industry）",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    setup_logger()
    try:
        mapping, exposure = build_customs_company_h8_marts(
            mainbz_path=args.mainbz,
            stock_basic_path=args.stock_basic,
            catalog_path=args.catalog,
            customs_trade_path=args.customs_trade,
            as_of_period=args.as_of_period,
        )
        outputs: dict[str, Path] = save_customs_company_h8_marts(mapping, exposure, args.output_dir)
        if args.with_signal:
            signal_outputs = run_customs_company_h8_pipeline(
                exposure_mart_path=args.output_dir / "customs_company_h8_exposure.parquet",
                customs_trade_path=args.customs_trade,
                artifact_root=args.artifact_root,
            )
            outputs.update(signal_outputs)
    except (FileNotFoundError, OSError, ValueError) as exc:
        logger.error("公司-H8 出口暴露 Mart 构建失败: %s", exc)
        sys.exit(1)
    print(f"公司产品映射: {mapping.height} 行")
    print(f"公司-H8 月度暴露: {exposure.height} 行")
    for name, path in outputs.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
